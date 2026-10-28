# Initial model and verification protocol

Status: first implementation milestone and working research specification.
This document develops the supplied proposed dissertation scope; it does not
record supervisor approval or replace the official assessment brief.

## Research aim

Design and experimentally evaluate a virtual ECU tuning and telemetry platform
using explicit model assumptions, controlled comparisons and reproducible data.
The broader question concerns the effects of fuel and ignition map changes in
defined simulated operating scenarios. This first milestone verifies only the
fuel-map calculation at one prescribed operating point.

## System boundary

The initial bench prescribes RPM, manifold absolute pressure and air mass flow.
It contains an interpolated fuel correction map, a first-order delivered-fuel
state and a calculated air-to-fuel ratio. RPM and pressure are inputs, not solved
engine states. There is no throttle, torque, ignition or combustion model yet.
All maps and telemetry in this milestone are synthetic project-owned examples.

The intended next model is a simplified warmed-up, four-stroke, naturally
aspirated spark-ignition engine. Its displacement, airflow, pressure and speed
dynamics require a separate justified specification before implementation.

## Variables and assumptions

| Symbol | Meaning | First experiment |
| --- | --- | --- |
| N | Prescribed engine speed | 3000 RPM |
| p | Prescribed manifold absolute pressure | 60 kPa |
| A | Prescribed air mass flow | 20 g/s |
| R | Reference AFR for this experiment | 14.7 g air / g fuel |
| M(N,p) | Interpolated fuel correction multiplier | 1.00 or 1.10 at the test point |
| F_cmd | Commanded fuel mass flow | g/s |
| F | Delivered fuel mass flow | g/s |
| tau | Illustrative fuel-response time constant | 0.2 s |

These values define a software test fixture; their combination has not been
calibrated against a vehicle. The reference AFR is not a universal tuning target.
The time constant is an explicit modelling assumption, not a measured injector
response. Fixed air flow is independent of the tunable map.

## Equations and map conventions

The reference fuel flow is `F_ref = A / R`. The controller commands
`F_cmd = F_ref * M(N,p)`. The delivered-fuel state follows
`dF/dt = (F_cmd - F) / tau`, and the reported mixture is `AFR = A / F`.

For a command held over a sampling interval, use the exact update
`F_next = F_cmd + (F - F_cmd) * exp(-dt/tau)`. The analytical steady-state
AFR is `R / M`. The initial state is `F(0) = A / R` in both runs.

Map rows correspond to increasing MAP in kPa; columns correspond to increasing
RPM. Values are dimensionless fuel multipliers, not Speeduino VE percentages
or injector pulse widths. Bilinear interpolation uses actual axis distances.
Axes must be strictly increasing and contain at least two points. Extrapolation
is rejected. The multiplier range [0.5, 1.5] is an implementation boundary of
this bench, not a statement about suitable vehicle settings.

## Controlled comparison

- Conditions: baseline map and a map whose centre cell increases from 1.00 to 1.10.
- Duration: 10 seconds; map activation: 5 seconds; reporting rate: 50 Hz.
- Both runs use multiplier 1.00 before activation and the same initial state.
- The command at time `t_k` affects the interval starting at `t_k`; the recorded
  AFR at `t_k` uses the state at that instant. The final endpoint is included.
- Controlled variables: operating point, air flow, reference AFR, initial state,
  model source, time constant, duration and sample grid.
- Metrics: AFR RMSE against R over [5,10] s, and mean AFR and signed error over
  [9,10] s. Endpoints are included, giving 501 samples/run and 51 in the final window.
- Hypothesis: at unchanged air flow, multiplier 1.10 converges to AFR
  `14.7 / 1.10 = 13.363636...`; baseline remains at 14.7.
- Software acceptance: baseline AFR error below 1e-12, final candidate AFR
  within 1e-9 of its analytical limit, correct interpolation and repeatable traces.

Agreement with an equation-derived answer is a verification check. It cannot
independently validate engine physics or demonstrate a better tune. Identical
deterministic reruns do not justify confidence intervals. Sensitivity analysis
and external validity belong to later research stages.

## Reproducibility

Each experiment gets a new directory, unique experiment/run identifiers, map
snapshots, a protocol snapshot, source snapshot, hashes, CSV files and metrics.
CSV time is simulation time. No real-time scheduling or logging-latency claim
is made. New identifiers differ between reruns; numerical traces must match.

## Next model decisions

Specify airflow independently of the ECU's airflow estimate; define RPM and
manifold-pressure dynamics; justify an ignition-to-output relationship; then
add idle, acceleration and load-step scenarios. Keep the GUI separate from
the model so batch experiments remain possible.

## Initial sources

- [Speeduino fuel table documentation](https://wiki.speeduino.com/en/configuration/VE_table):
  engineering reference for interpolated RPM/load maps, not physical validation
  of this bench or an assertion of Speeduino firmware compatibility.
- [Speeduino tuning documentation](https://wiki.speeduino.com/en/tuning/Tuning):
  reference for the separation of VE, spark and AFR tables.
- [Speeduino Tunes](https://github.com/speeduino/Tunes): possible future reference
  inputs; no tune files have been imported. The repository declares CC BY-NC 4.0.
- [TunerStudio tuning views](https://www.tunerstudio.com/index.php/products/114-tunerstudio-tuning-and-dyno-views):
  product reference for eventual tables, gauges and comparison views.

These engineering and product sources are a starting reference list. The
dissertation still needs scholarly literature on modelling and validation.
