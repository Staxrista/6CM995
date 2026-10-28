# Fuel map coupling and comparative experiments

Status: third implementation milestone. Model version 0.3.0. This model adds
delivered fuel as a state and connects fuel-map changes to AFR and crankshaft
response. The relationship between mixture and torque is an explicit,
uncalibrated assumption. It is not evidence of real-engine tuning gains.

## Research question for this milestone

Under identical initial states and throttle/load histories, how do baseline,
+10% and -10% fuel correction maps affect calculated AFR and simulated speed?
Distinguish verification of that causal software connection from validating
the chosen torque relationship with independent measurements.

## State inputs and independent plant behaviour

The state is now `(p, w, F)`: manifold absolute pressure in Pa, angular speed in
rad/s and delivered fuel mass flow in kg/s. The air-path and friction equations
from Step 02 remain unchanged. Air mass flow is determined by plant volumetric
efficiency, displacement, pressure, temperature and speed.

The ECU has its own volumetric-efficiency estimate. At the default settings
both efficiencies are 0.8, but they are separate parameters. Editing a fuel
correction map does not directly change plant volumetric efficiency or airflow.
Later changes in speed and pressure can affect airflow through the dynamics.

## Fuel and mixture equations

Let `A` be actual cylinder air flow and `A_est` the ECU estimate, both in kg/s.
Let `M(N,p)` be the interpolated, dimensionless fuel map value.

`A_est = A * eta_v_ecu / eta_v_plant`

`F_cmd = A_est / AFR_target * M(N,p)`

`dF/dt = (F_cmd - F) / tau_fuel`

`AFR = A / F`

`lambda = AFR / AFR_reference`

Default `AFR_target = AFR_reference = 14.7` and `tau_fuel = 0.2 s`. These are
test assumptions, not universal operating targets or measured injector data.
The legacy plant parameter `assumed_afr` supplies `AFR_reference` in this version.
The calculated AFR is a mass-flow ratio; no physical lambda sensor is simulated.

## Provisional torque closure

The effective burnable fuel flow is constrained by fuel and air availability:

`F_burnable = min(F, A / AFR_reference)`

Use an illustrative mixture multiplier and energy-to-torque relationship:

`phi(lambda) = exp(-k_lambda * (lambda - 1)^2)`

`T_ind = eta_i * LHV * F_burnable * phi(lambda) / w`

`dw/dt = (T_ind - T_friction - T_load) / J`

The default `k_lambda = 2.0` is chosen for this demonstrator. It was not taken
from a measured engine, fitted dataset or published calibration. This closure
puts the assumed optimum at lambda 1 and bounds torque by available chemical
energy at the chosen efficiency. Additional rich fuel therefore does not
produce unlimited torque. It does not model knock, optimum power enrichment,
misfire, wall wetting, emissions, transport delay or ignition timing.

The direction and size of RPM differences are conditional on this closure.
A different mixture-loss relationship can produce different conclusions.
The baseline estimate matches the plant by construction, so its lower target
error is not a discovery of an optimal real-world tune.

## Maps and activation in the application

The three supplied dynamic maps cover the full implementation domain:
400–7000 RPM and 5–100 kPa at the default ambient pressure. They contain
uniform multipliers 1.00, 1.10 and 0.90. These are synthetic project-owned
fixtures, not imported Speeduino VE tables.

The editor queues a map using **Use on next run**. The next Dashboard **Reset**
or scenario change activates it. Editing or queueing during a recording leaves
that recording's active map fixed. The dashboard identifies both the current
map and any queued map. Each saved run includes its actual map snapshot/hash.
The original Step 01 fixed-point check remains a separate verification option.

## Controlled protocol

Compare each map under steady idle, a throttle step and a load step: nine runs.
Within each scenario group, hold plant parameters, initial pressure/speed/fuel,
input events, ECU parameters, integration step and reporting grid constant.
All runs start from the same reference fuel state; their map is active from
time zero. The protocol is 20 s with input steps at 5 s where applicable,
1 ms RK4 integration and 50 Hz reporting including both endpoints.

Outcome measures:

- Mean AFR and RPM over the last simulated second including endpoints.
- AFR RMSE against the target over [5 s, end]. For manual recordings shorter
  than 5 s, the report explicitly uses the final sample only.
- Model indicated torque and fuel flow; fuel used is trapezoidal integration
  of reported mass flow, not measured vehicle consumption.

Uniform-map steady-state AFR has the equation-derived reference:

`AFR_steady = AFR_target * eta_v_plant / eta_v_ecu / M`

For the default equal estimates, values are 14.7, 13.363636 and 16.333333.
Uniform maps also allow an independently solved static speed reference: apply
`min(1, 1/lambda) * phi(lambda)` to the Step 02 indicated-efficiency coefficient,
then solve the static air/torque balances. Nonuniform edited maps have no
closed-form reference in this implementation; their reference is unavailable.

## Acceptance checks and current evidence

Require baseline idle drift below 1e-8 RPM; final AFR within 1e-4 of its
uniform-map reference; final RPM within 0.02 of its same-model equilibrium;
and differences below 0.01 RPM and 1e-4 AFR when halving the integration step.
Reporting-rate changes must leave internal trajectories unchanged.

Checks also cover fuel/air energy bounds, positive finite fuel flow, separate
ECU/plant estimates, immutable run-map snapshots, same-runtime trace replay,
and sensitivity of point torque to the assumed loss coefficient. These are
verification and internal-consistency checks. They do not independently
validate combustion physics. Full parameter-sensitivity experiments and
external calibration remain research work to complete.

## Reproduction

Run `python run_fuel_dynamics.py` for the nine fixture comparisons. Each output
directory contains config, embedded map data and separate map snapshots, CSVs,
summary metrics, hashes, source snapshots and a replay command. Config schema
`fuel_coupled_suite_v1` distinguishes this model from the older air-only model.
The older experiment runners and their source archives remain available.

## Sources and interpretation

- [MathWorks SI Core Engine](https://www.mathworks.com/help/autoblks/ref/sicoreengine.html)
  provides the mass-flow definitions of AFR and relative AFR. It does not
  supply our first-order fuel time constant or ECU calibration.
- [MathWorks SI Engine Torque Structure Model](https://www.mathworks.com/help/autoblks/ug/si-engine-torque-structure-model.html)
  describes a lambda multiplier within a calibrated torque structure. This
  motivates separating mixture effects from other torque terms. Our Gaussian
  loss and its coefficient are project assumptions, not that calibrated model.

Scholarly literature and independent reference measurements are still required
to justify or replace these provisional assumptions before drawing claims about
real engines. Ignition-map coupling is a subsequent modelling decision.
