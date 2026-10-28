"""Three-state air, speed and delivered-fuel model with an assumed torque law.

The lambda loss curve is synthetic and uncalibrated. It verifies a causal
software connection, not real-engine tuning gains. See docs/03_fuel_coupling.md.
"""

import copy
import math
from dataclasses import asdict, dataclass, replace

from ecu_bench import FuelMap
from engine_dynamics import (Inputs, Parameters, State as AirState, check_state,
    default_config as air_config, equilibrium as air_equilibrium, number,
    observe as air_observe, validate_scenario as validate_air_scenario)

MODEL_VERSION = "0.3.0-fuel-map-coupling"


@dataclass(frozen=True)
class FuelParameters:
    ecu_volumetric_efficiency: float = 0.8
    afr_target: float = 14.7
    response_time_s: float = 0.2
    lambda_loss_coefficient: float = 2.0

    def __post_init__(self):
        for key, value in asdict(self).items():
            number(value, key, inclusive=key == "lambda_loss_coefficient")
        if self.ecu_volumetric_efficiency > 1:
            raise ValueError("ECU volumetric efficiency must be in (0, 1]")


@dataclass(frozen=True)
class State(AirState):
    fuel_mass_flow_kg_s: float

    @classmethod
    def from_readings(cls, rpm, map_kpa, fuel_mass_flow_kg_s):
        number(fuel_mass_flow_kg_s, "Delivered fuel", inclusive=False)
        air = AirState.from_readings(rpm, map_kpa)
        return cls(air.pressure_pa, air.omega_rad_s, fuel_mass_flow_kg_s)


def observe(state, inputs, parameters, fuel_parameters, fuel_map, time_s=0.0):
    values = air_observe(state, inputs, parameters, time_s)
    number(state.fuel_mass_flow_kg_s, "Delivered fuel", inclusive=False)
    air_flow = values["cylinder_air_g_s"] / 1000
    estimated_air = air_flow * fuel_parameters.ecu_volumetric_efficiency / parameters.volumetric_efficiency
    multiplier = fuel_map.lookup(state.rpm, state.pressure_pa / 1000)
    fuel_command = estimated_air / fuel_parameters.afr_target * multiplier
    afr = air_flow / state.fuel_mass_flow_kg_s
    relative_afr = afr / parameters.assumed_afr
    # Limited by both available fuel and stoichiometric air capacity. The
    # additional lambda loss is an explicit illustrative model assumption.
    burnable_fuel = min(state.fuel_mass_flow_kg_s, air_flow / parameters.assumed_afr)
    mixture_factor = math.exp(-fuel_parameters.lambda_loss_coefficient * (relative_afr - 1)**2)
    torque = (parameters.indicated_efficiency * parameters.heating_value_j_kg
              * burnable_fuel * mixture_factor / state.omega_rad_s)
    net_torque = torque - values["model_friction_torque_nm"] - inputs.load_nm
    values.update({
        "ecu_estimated_air_g_s": estimated_air * 1000,
        "fuel_multiplier": multiplier,
        "fuel_command_g_s": fuel_command * 1000,
        "fuel_delivered_g_s": state.fuel_mass_flow_kg_s * 1000,
        "fuel_rate_g_s2": (fuel_command - state.fuel_mass_flow_kg_s) / fuel_parameters.response_time_s * 1000,
        "afr": afr,
        "afr_target": fuel_parameters.afr_target,
        "lambda": relative_afr,
        "assumed_mixture_efficiency": mixture_factor,
        "model_indicated_torque_nm": torque,
        "net_torque_nm": net_torque,
        "speed_rate_rpm_s": net_torque / parameters.inertia_kg_m2 * 60 / (2*math.pi),
    })
    return values


def derivatives(state, inputs, parameters, fuel_parameters, fuel_map):
    values = observe(state, inputs, parameters, fuel_parameters, fuel_map)
    return (values["pressure_rate_kpa_s"] * 1000,
            values["speed_rate_rpm_s"] * 2*math.pi/60,
            values["fuel_rate_g_s2"] / 1000)


def advance(state, inputs, parameters, fuel_parameters, fuel_map, dt):
    number(dt, "Integration step", inclusive=False)
    def shifted(slope, fraction):
        return State(state.pressure_pa + dt*fraction*slope[0],
                     state.omega_rad_s + dt*fraction*slope[1],
                     state.fuel_mass_flow_kg_s + dt*fraction*slope[2])
    def slope(at):
        return derivatives(at, inputs, parameters, fuel_parameters, fuel_map)
    k1 = slope(state)
    k2 = slope(shifted(k1, 0.5))
    k3 = slope(shifted(k2, 0.5))
    k4 = slope(shifted(k3, 1))
    increments = [dt/6*(k1[i]+2*k2[i]+2*k3[i]+k4[i]) for i in range(3)]
    result = State(state.pressure_pa+increments[0], state.omega_rad_s+increments[1],
                   state.fuel_mass_flow_kg_s+increments[2])
    check_state(result, parameters)
    number(result.fuel_mass_flow_kg_s, "Delivered fuel", inclusive=False)
    return result


def validate_map_domain(fuel_map, parameters):
    for rpm in (parameters.minimum_rpm, parameters.maximum_rpm):
        for pressure in (parameters.minimum_pressure_pa, parameters.ambient_pressure_pa):
            fuel_map.lookup(rpm, pressure / 1000)


def validate_scenario(scenario, parameters, dt, sample_hz):
    air_scenario = {**scenario, "initial": {key: scenario["initial"][key] for key in ("rpm", "map_kpa")}}
    _, stride, count, indices = validate_air_scenario(air_scenario, parameters, dt, sample_hz)
    state = State.from_readings(**scenario["initial"])
    fuel_map = FuelMap.from_dict(scenario["fuel_map"])
    validate_map_domain(fuel_map, parameters)
    return state, stride, count, indices


def simulate_scenario(scenario, parameters, fuel_parameters, dt=0.001, sample_hz=50.0):
    state, stride, count, indices = validate_scenario(scenario, parameters, dt, sample_hz)
    fuel_map = FuelMap.from_dict(scenario["fuel_map"])
    samples = []
    position = 0
    for tick in range(count + 1):
        while position+1 < len(indices) and indices[position+1] <= tick:
            position += 1
        event = scenario["events"][position]
        inputs = Inputs(event["throttle"], event["load_nm"])
        if tick % stride == 0:
            samples.append(observe(state, inputs, parameters, fuel_parameters, fuel_map, tick*dt))
        if tick < count:
            state = advance(state, inputs, parameters, fuel_parameters, fuel_map, dt)
    return samples


def uniform_map(name, value):
    return FuelMap(name, (400, 3000, 7000), (5, 60, 100), ((value,)*3,)*3)


def uniform_equilibrium(inputs, parameters, fuel_parameters, fuel_map):
    multiplier = fuel_map.values[0][0]
    if any(abs(v-multiplier) > 1e-12 for row in fuel_map.values for v in row):
        raise ValueError("Closed-form reference is defined only for uniform fuel maps")
    afr = fuel_parameters.afr_target * parameters.volumetric_efficiency / fuel_parameters.ecu_volumetric_efficiency / multiplier
    relative_afr = afr / parameters.assumed_afr
    factor = min(1.0, 1/relative_afr) * math.exp(-fuel_parameters.lambda_loss_coefficient*(relative_afr-1)**2)
    effective = replace(parameters, indicated_efficiency=parameters.indicated_efficiency*factor)
    air = air_equilibrium(inputs, effective)
    actual_flow = (parameters.volumetric_efficiency * parameters.displacement_m3 * air.omega_rad_s
                   / (4*math.pi) * air.pressure_pa / parameters.rt)
    return State(air.pressure_pa, air.omega_rad_s, actual_flow / afr)


def default_config():
    config = air_config()
    parameters = Parameters(**config["parameters"])
    config["schema"] = "fuel_coupled_suite_v1"
    config["fuel_parameters"] = asdict(FuelParameters())
    for scenario in config["scenarios"]:
        scenario["operating_scenario"] = scenario["name"]
        scenario["condition"] = "baseline"
        scenario["fuel_map"] = uniform_map("dynamic_baseline", 1.0).to_dict()
        air = AirState.from_readings(**scenario["initial"])
        first = scenario["events"][0]
        air_flow = air_observe(air, Inputs(first["throttle"], first["load_nm"]), parameters)["cylinder_air_g_s"] / 1000
        scenario["initial"]["fuel_mass_flow_kg_s"] = air_flow / parameters.assumed_afr
    return config


def comparison_config(fuel_maps):
    config = default_config()
    scenarios = config["scenarios"]
    config["scenarios"] = []
    for original in scenarios:
        for fuel_map in fuel_maps:
            scenario = copy.deepcopy(original)
            scenario["name"] = original["name"] + "__" + fuel_map.name
            scenario["condition"] = fuel_map.name
            scenario["fuel_map"] = fuel_map.to_dict()
            config["scenarios"].append(scenario)
    return config
