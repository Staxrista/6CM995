"""Two-state, uncalibrated mean-value air-path and crankshaft model.

SI units internally: Pa, kg, seconds, radians, Nm. See docs/02_engine_dynamics.md.
Fuel-map and ignition effects on torque are deliberately outside this version.
"""

import math
from dataclasses import asdict, dataclass

MODEL_VERSION = "0.2.0-air-path-and-speed"


def number(value, name, minimum=0.0, inclusive=True):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number")
    if value < minimum or (not inclusive and value == minimum):
        raise ValueError(f"{name} must be {'at least' if inclusive else 'greater than'} {minimum}")


@dataclass(frozen=True)
class Parameters:
    displacement_m3: float = 0.002
    manifold_volume_m3: float = 0.003
    air_temperature_k: float = 300.0
    gas_constant_j_kg_k: float = 287.05
    ambient_pressure_pa: float = 100000.0
    volumetric_efficiency: float = 0.8
    indicated_efficiency: float = 0.25
    heating_value_j_kg: float = 44000000.0
    assumed_afr: float = 14.7
    inertia_kg_m2: float = 0.25
    friction_constant_nm: float = 12.0
    friction_speed_nm_s_rad: float = 0.12
    throttle_leak_kg_s_pa: float = 1e-8
    throttle_gain_kg_s_pa: float = 8e-7
    minimum_pressure_pa: float = 5000.0
    minimum_rpm: float = 400.0
    maximum_rpm: float = 7000.0

    def __post_init__(self):
        for name, value in asdict(self).items():
            number(value, name, inclusive=name in ("friction_constant_nm", "throttle_leak_kg_s_pa"))
        if not 0 < self.volumetric_efficiency <= 1 or not 0 < self.indicated_efficiency <= 1:
            raise ValueError("Efficiencies must be in (0, 1] for this model")
        if self.minimum_rpm >= self.maximum_rpm:
            raise ValueError("Minimum RPM must be below maximum RPM")
        if self.minimum_pressure_pa >= self.ambient_pressure_pa:
            raise ValueError("Minimum pressure must be below ambient pressure")

    @property
    def rt(self):
        return self.gas_constant_j_kg_k * self.air_temperature_k

    @property
    def torque_per_pa(self):
        # Work per 720-degree engine cycle divided by 4*pi radians.
        return (self.indicated_efficiency * self.heating_value_j_kg * self.volumetric_efficiency
                * self.displacement_m3 / (4 * math.pi * self.rt * self.assumed_afr))


@dataclass(frozen=True)
class State:
    pressure_pa: float
    omega_rad_s: float

    @property
    def rpm(self):
        return self.omega_rad_s * 60 / (2 * math.pi)

    @classmethod
    def from_readings(cls, rpm, map_kpa):
        number(rpm, "RPM", inclusive=False)
        number(map_kpa, "MAP kPa", inclusive=False)
        return cls(map_kpa * 1000, rpm * 2 * math.pi / 60)


@dataclass(frozen=True)
class Inputs:
    throttle: float
    load_nm: float

    def __post_init__(self):
        number(self.throttle, "Throttle")
        number(self.load_nm, "Load")
        if self.throttle > 1:
            raise ValueError("Throttle must be in [0, 1]")


def check_state(state, parameters):
    number(state.pressure_pa, "Manifold pressure")
    number(state.omega_rad_s, "Angular speed")
    if not parameters.minimum_pressure_pa <= state.pressure_pa <= parameters.ambient_pressure_pa:
        raise ValueError("Pressure left the model domain; no clipping is applied")
    if not parameters.minimum_rpm <= state.rpm <= parameters.maximum_rpm:
        raise ValueError("RPM left the model domain; stall and overspeed are not modelled")


def observe(state, inputs, parameters, time_s=0.0):
    check_state(state, parameters)
    conductance = parameters.throttle_leak_kg_s_pa + parameters.throttle_gain_kg_s_pa * inputs.throttle
    throttle_flow = conductance * (parameters.ambient_pressure_pa - state.pressure_pa)
    cylinder_flow = (parameters.volumetric_efficiency * parameters.displacement_m3
                     * state.omega_rad_s / (4 * math.pi) * state.pressure_pa / parameters.rt)
    indicated_torque = parameters.torque_per_pa * state.pressure_pa
    friction_torque = parameters.friction_constant_nm + parameters.friction_speed_nm_s_rad * state.omega_rad_s
    net_torque = indicated_torque - friction_torque - inputs.load_nm
    pressure_rate = parameters.rt / parameters.manifold_volume_m3 * (throttle_flow - cylinder_flow)
    speed_rate = net_torque / parameters.inertia_kg_m2
    return {
        "time_s": time_s,
        "throttle_fraction": inputs.throttle,
        "external_load_nm": inputs.load_nm,
        "rpm": state.rpm,
        "map_kpa": state.pressure_pa / 1000,
        "throttle_air_g_s": throttle_flow * 1000,
        "cylinder_air_g_s": cylinder_flow * 1000,
        "model_indicated_torque_nm": indicated_torque,
        "model_friction_torque_nm": friction_torque,
        "net_torque_nm": net_torque,
        "manifold_air_mass_g": state.pressure_pa * parameters.manifold_volume_m3 / parameters.rt * 1000,
        "pressure_rate_kpa_s": pressure_rate / 1000,
        "speed_rate_rpm_s": speed_rate * 60 / (2 * math.pi),
    }


def derivatives(state, inputs, parameters):
    values = observe(state, inputs, parameters)
    return (values["pressure_rate_kpa_s"] * 1000,
            values["speed_rate_rpm_s"] * 2 * math.pi / 60)


def advance(state, inputs, parameters, dt):
    """One fourth-order Runge-Kutta step with inputs held constant."""
    number(dt, "Integration step", inclusive=False)
    def shifted(slope, fraction):
        return State(state.pressure_pa + dt * fraction * slope[0],
                     state.omega_rad_s + dt * fraction * slope[1])
    k1 = derivatives(state, inputs, parameters)
    k2 = derivatives(shifted(k1, 0.5), inputs, parameters)
    k3 = derivatives(shifted(k2, 0.5), inputs, parameters)
    k4 = derivatives(shifted(k3, 1), inputs, parameters)
    result = State(state.pressure_pa + dt / 6 * (k1[0] + 2*k2[0] + 2*k3[0] + k4[0]),
                   state.omega_rad_s + dt / 6 * (k1[1] + 2*k2[1] + 2*k3[1] + k4[1]))
    check_state(result, parameters)
    return result


def equilibrium(inputs, parameters):
    """Independent closed-form positive equilibrium of the two model equations."""
    conductance = parameters.throttle_leak_kg_s_pa + parameters.throttle_gain_kg_s_pa * inputs.throttle
    a = parameters.rt / parameters.manifold_volume_m3 * conductance
    b = parameters.volumetric_efficiency * parameters.displacement_m3 / (4 * math.pi * parameters.manifold_volume_m3)
    resistance = parameters.friction_constant_nm + inputs.load_nm
    qa = parameters.friction_speed_nm_s_rad * b
    qb = parameters.friction_speed_nm_s_rad * a + resistance * b
    qc = resistance * a - parameters.torque_per_pa * parameters.ambient_pressure_pa * a
    if qc >= 0:
        raise ValueError("Inputs have no positive-speed equilibrium in this model")
    omega = -2 * qc / (qb + math.sqrt(qb*qb - 4*qa*qc))
    result = State(parameters.ambient_pressure_pa * a / (a + b * omega), omega)
    check_state(result, parameters)
    return result


def throttle_for_equilibrium(rpm, load_nm, parameters):
    number(rpm, "RPM", inclusive=False)
    number(load_nm, "Load")
    omega = rpm * 2 * math.pi / 60
    pressure = (parameters.friction_constant_nm + parameters.friction_speed_nm_s_rad * omega
                + load_nm) / parameters.torque_per_pa
    state = State(pressure, omega)
    check_state(state, parameters)
    if pressure >= parameters.ambient_pressure_pa:
        raise ValueError("Requested equilibrium cannot be supplied by this throttle model")
    flow = parameters.volumetric_efficiency * parameters.displacement_m3 * omega / (4*math.pi) * pressure / parameters.rt
    conductance = flow / (parameters.ambient_pressure_pa - pressure)
    throttle = (conductance - parameters.throttle_leak_kg_s_pa) / parameters.throttle_gain_kg_s_pa
    Inputs(throttle, load_nm)
    return throttle


def grid_index(seconds, dt):
    number(seconds, "Time")
    index = round(seconds / dt)
    if not math.isclose(seconds / dt, index, rel_tol=0, abs_tol=1e-7):
        raise ValueError("Time does not align with the integration grid")
    return index


def validate_scenario(scenario, parameters, dt, sample_hz):
    number(dt, "Integration step", inclusive=False)
    number(sample_hz, "Sampling frequency", inclusive=False)
    stride = grid_index(1 / sample_hz, dt)
    if stride < 1:
        raise ValueError("Sampling frequency exceeds integration frequency")
    count = grid_index(scenario["duration_s"], dt)
    if count < stride or count % stride:
        raise ValueError("Duration must end on the reporting grid")
    state = State.from_readings(**scenario["initial"])
    check_state(state, parameters)
    events = scenario["events"]
    if not events or events[0]["time_s"] != 0:
        raise ValueError("Scenario must have an input event at time zero")
    indices = []
    for event in events:
        index = grid_index(event["time_s"], dt)
        if index > count or (indices and index <= indices[-1]):
            raise ValueError("Events must be strictly ordered within the scenario")
        indices.append(index)
        Inputs(event["throttle"], event["load_nm"])
    return state, stride, count, indices


def simulate_scenario(scenario, parameters, dt=0.001, sample_hz=50.0):
    state, stride, count, event_indices = validate_scenario(scenario, parameters, dt, sample_hz)
    samples = []
    event_position = 0
    for tick in range(count + 1):
        while event_position + 1 < len(event_indices) and event_indices[event_position + 1] <= tick:
            event_position += 1
        event = scenario["events"][event_position]
        inputs = Inputs(event["throttle"], event["load_nm"])
        if tick % stride == 0:
            samples.append(observe(state, inputs, parameters, tick * dt))
        if tick < count:
            state = advance(state, inputs, parameters, dt)
    return samples


def default_config():
    parameters = Parameters()
    idle = Inputs(throttle_for_equilibrium(900, 8, parameters), 8)
    running = Inputs(0.25, 8)
    def scenario(name, initial_inputs, final_inputs=None):
        initial = equilibrium(initial_inputs, parameters)
        events = [{"time_s": 0.0, "throttle": initial_inputs.throttle, "load_nm": initial_inputs.load_nm}]
        if final_inputs is not None:
            events.append({"time_s": 5.0, "throttle": final_inputs.throttle, "load_nm": final_inputs.load_nm})
        return {"name": name, "duration_s": 20.0,
                "initial": {"rpm": initial.rpm, "map_kpa": initial.pressure_pa/1000}, "events": events}
    return {
        "schema": "air_path_speed_suite_v1", "parameters": asdict(parameters),
        "integration_step_s": 0.001, "sampling_rate_hz": 50.0,
        "scenarios": [scenario("steady_idle", idle), scenario("throttle_step", idle, running),
                      scenario("load_step", running, Inputs(0.25, 20))],
    }
