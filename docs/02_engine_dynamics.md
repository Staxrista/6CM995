# Air path and crankshaft dynamics

Status: second implementation milestone. Model version 0.2.0. All numerical
parameters are illustrative, uncalibrated assumptions. This is a mean-value
model: individual combustion events and crank angles are not resolved.

This preserves the Step 02 air-only bench. The current desktop uses the
[Step 03 fuel-coupled model](03_fuel_coupling.md).

## Purpose and separation from the first experiment

Replace prescribed RPM and manifold pressure with evolving states driven by
throttle and an external resisting torque. Keep the Step 01 fuel-map experiment
as an independent verification bench. The new model assumes a fixed mixture
and efficiency; it does not yet connect fuel or ignition map edits to torque.

## State inputs and units

The states are manifold absolute pressure `p` in Pa and crankshaft speed `w` in
rad/s. User inputs are dimensionless throttle `u` in [0,1] and external resisting
torque `T_load` in Nm. Interface readings use kPa and RPM, with
`RPM = w * 60 / (2*pi)`. Internally, all flow rates are kg/s.

## Equations

At fixed air temperature, the manifold is an ideal-gas control volume:

`dp/dt = (R*T/V_manifold) * (m_in - m_out)`

For a four-stroke engine with total displacement `V_d`:

`m_out = eta_v * V_d * w/(4*pi) * p/(R*T)`

The four-stroke factor is equivalent to `RPM/120` cycles per second. The
volumetric efficiency is fixed in this version; it is a plant parameter,
independent of the editable fuel correction maps.

The first throttle law is a deliberately reduced conductance approximation:

`m_in = (G_leak + G_gain*u) * (p_ambient - p)`

`G` has units kg/(s Pa). This is our simplification, not the nonlinear/choked
throttle law used in the referenced MathWorks example. It supports a transparent
closed-form equilibrium, but cannot represent sonic flow or a physical throttle
plate geometry. The slider is an abstract opening fraction, not a measured angle.

For a constant assumed AFR and indicated efficiency, fuel energy per 720-degree
cycle gives the following provisional torque closure:

`T_ind = eta_i * LHV * (eta_v * V_d * p/(R*T) / AFR_assumed) / (4*pi)`

`T_friction = T_constant + c_friction*w`

`dw/dt = (T_ind - T_friction - T_load) / J`

This energy-based torque closure and linear friction are modelling assumptions.
They are not a calibrated power curve or an ignition/mixture sensitivity model.

## Default parameters

| Parameter | Assumed value |
| --- | ---: |
| Total displacement | 0.002 m3 or 2 L |
| Manifold volume | 0.003 m3 or 3 L |
| Air temperature | 300 K |
| Ambient pressure | 100000 Pa |
| Specific gas constant | 287.05 J/(kg K) |
| Volumetric efficiency | 0.80 |
| Indicated efficiency | 0.25 |
| Fuel heating value | 44 MJ/kg |
| Assumed AFR | 14.7 |
| Crankshaft equivalent inertia | 0.25 kg m2 |
| Constant friction torque | 12 Nm |
| Speed friction coefficient | 0.12 Nm s/rad |
| Leakage conductance | 1e-8 kg/(s Pa) |
| Throttle conductance gain | 8e-7 kg/(s Pa) |

The implementation domain is 400–7000 RPM and 5 kPa to ambient pressure.
States leaving this domain terminate a run explicitly; no RPM or pressure
clipping conceals the event. Startup, stall physics, boost, thermal dynamics,
pumping-loss detail, ignition timing and closed-loop idle control are absent.

## Experimental protocol

Use RK4 integration at 1 ms and report at 50 Hz. These are separate settings:
changing reporting frequency must not change the internal trajectory. Inputs are
held over each integration interval, and changes apply at their stated time.
Each fixture lasts 20 s, including both endpoints, giving 1001 samples.

| Scenario | Initial state and change at 5 s | Qualitative check |
| --- | --- | --- |
| steady_idle | Analytical 900 RPM equilibrium, constant throttle and 8 Nm load | RPM and pressure remain stationary |
| throttle_step | Same initial state; throttle changes to 0.25, load remains 8 Nm | Pressure rises first and speed subsequently rises |
| load_step | Equilibrium at throttle 0.25 and 8 Nm; load changes to 20 Nm | Initial net torque is -12 Nm and speed falls |

The idle fixture starts at equilibrium; this does not demonstrate recovery
under an idle controller. In the load-step fixture, pressure can rise as lower
speed reduces cylinder pumping at the same throttle. Increased external load
therefore does not imply that both pressure and RPM must fall.

Before accepting this version, require stationary idle drift below 1e-8 RPM;
correct step signs; final RPM within 0.01 of the independently solved static
equilibrium for these fixtures; and less than 0.001 RPM difference when halving
the integration step. These are software/model consistency criteria, not
physical validation criteria. The first 15 s pilot was too short to meet the
chosen final-equilibrium tolerance; the documented fixture therefore uses 20 s.

Reported outcomes include final-window mean RPM and pressure, extrema, and
error against the model's analytical equilibrium. The measurement window is
the last simulated second including endpoints. Short manual recordings may
remain transient. If the final inputs have no supported equilibrium, the
recording is preserved and that reference is reported as unavailable.

## Reproducibility and desktop interaction

The batch runner stores all parameters, input events, initial states, grid
settings, source snapshots, hashes, CSV files, summaries and unique identifiers.
It records Python version and synthetic provenance. Exact trace equality is
checked in the same runtime; cross-platform floating-point identity is not claimed.

At this milestone, the desktop used the same `advance` and `observe` functions. In manual mode,
changes are recorded at reporting boundaries; pause advances no simulation time.
Saved manual event sequences can be replayed by the batch runner. GUI timer
latency is not treated as a measurement of engine or communication latency.

## Sources and limits of the evidence

1. [MathWorks SI Engine Speed-Density Air Mass Flow Model](https://www.mathworks.com/help/autoblks/ug/spark-ignition-engine-simple-speed-density-breathing-model-1.html)
   supports the pressure/temperature/speed formulation and the need for measured
   data to calibrate volumetric efficiency. This version substitutes constant VE.
2. [MathWorks Model Engine Timing Using Triggered Subsystems](https://www.mathworks.com/help/simulink/slref/modeling-engine-timing-using-triggered-subsystems.html)
   documents manifold mass balance and rotational dynamics. Its nonlinear
   throttle and empirical torque equations are not imported into this project.

These sources justify the model structure, not our chosen coefficients. Future
work needs scholarly comparison, parameter sensitivity, independent reference
data and a justified coupling between fuel/ignition settings and model outputs.
