# Controlled comparisons and sensitivity protocol

Status: predefined Step 04 pilot protocol, written before collecting its study
results. It develops experiments E2 and E3 in the supplied proposed dissertation
specification. It is not supervisor approval or a completed dissertation method.

## Research questions

How do fuel-map effects change when the assumed mixture-loss coefficient,
fuel-response time and ECU airflow estimate change? Which conclusions depend
on these assumptions? Can the same stored conditions reproduce the same data
and figures? Ignition and real-time logging performance are separate future work.

## Design and controlled variables

Use model 0.3.0, the existing three operating scenarios and three uniform fuel
maps: 1.00, 1.10 and 0.90. Each scenario lasts 20 s; operating input steps are
at 5 s. Integration is RK4 at 1 ms and reporting is 50 Hz including endpoints.
Within each scenario, preserve initial pressure, speed, delivered fuel and
throttle/load history across all parameter cases. Do not re-equilibrate the
initial state after changing an ECU assumption.

Use one-at-a-time variations around the nominal settings:

| Case | Parameter | Value | Interpretation |
| --- | --- | ---: | --- |
| nominal | All parameters | Existing defaults | Reference case |
| mixture_loss_none | Lambda loss coefficient | 0 | Remove the assumed extra lambda loss |
| mixture_loss_high | Lambda loss coefficient | 4 | Double the nominal coefficient of 2 |
| fuel_response_fast | Fuel time constant | 0.1 s | Half the nominal 0.2 s |
| fuel_response_slow | Fuel time constant | 0.4 s | Twice the nominal 0.2 s |
| ecu_air_underestimate | ECU volumetric efficiency | 0.72 | 10% below the plant value of 0.8 |
| ecu_air_overestimate | ECU volumetric efficiency | 0.88 | 10% above the plant value of 0.8 |

The full study contains 7 cases × 3 scenarios × 3 maps = 63 conditions.
The smaller map-comparison pilot contains the 9 nominal conditions only.
These parameter levels are illustrative engineering probes, not measured
tolerances or a probability distribution. Only one parameter is changed per case;
interactions and joint uncertainty are not estimated by this design.

Each condition has one deterministic execution. Repeat the nominal throttle-step
baseline twice additionally to verify numerical reproducibility. The full study
therefore performs 65 simulations and stores 63 unique condition datasets plus
repeat-check evidence. Repetitions are not independent physical observations.

## Predefined expectations

1. Removing the extra lambda penalty changes the predicted rich-map RPM effect;
   this exposes dependence on a torque assumption rather than proving a tune gain.
2. ECU airflow-estimate bias can change which fuel map has the smallest AFR error.
   Interpret any ranking as conditional on that estimate and this model.
3. Fuel-response time changes transient AFR error. The equation-derived steady
   mixture for a uniform map is independent of that time constant; a finite run
   may still contain residual transients.

## Measures and analysis

For each run, retain all existing Step 03 metrics and add minimum/maximum AFR,
maximum absolute AFR target error after the final operating-input change, and
RPM settling time and overshoot relative to the same-model static equilibrium.
The response interval starts at the final input change, or at 0 s for a constant
scenario. The RPM band is max(1 RPM, 2% of the change from speed at that event
to the equilibrium reference). Settling requires all subsequent samples in band
and at least one further simulated second of confirmation. If not observed by
the end, report no settling time. With no nonzero speed change, overshoot percent
is unavailable. These definitions concern model response, not a vehicle test.

Report paired absolute differences from the baseline map in the same parameter
case and scenario. Report deterministic min/max metric ranges across the seven
cases for each scenario/map. Do not label these ranges confidence intervals,
standard errors or statistical significance. Do not compute p-values or a
variance-based effect size from repeated identical traces.

Produce nominal AFR/RPM overlay plots, final-RPM sensitivity ranges, and AFR-error
curves against the ECU estimate. Figures must have units, map labels and captions
identifying synthetic data and the tested deterministic ranges.

## Acceptance and failures

Check expected sample count and grid, finite outputs, positive delivered fuel,
and RPM/pressure within the existing model domain. Retain every attempted
condition in the study manifest, including domain failures and their errors.
Do not hide failed conditions or silently replace parameter values. Compare
canonical numerical trace hashes for the repeat checks. Generate three PNG and
three PDF figures when plotting dependencies are available. A partial or failed
study must be labelled accordingly.

## Reproduction and traceability

Store the full plan before the first run, one config and CSV per condition,
map snapshots, run IDs, model version, source hashes, runtime/dependency versions,
metrics, repeat evidence, a data dictionary, report and figures. A source snapshot
and documented command must reproduce the numerical datasets and figures.
Keep figure generation available separately from simulation so saved data can
be re-plotted. PDF file bytes can differ because of metadata; numerical evidence
is compared using the saved telemetry and metrics.

## Limits and next work

This is an internal robustness pilot. It does not validate real-engine behaviour,
establish realistic parameter bounds or complete the ignition-map investigation.
E4 still requires a separate wall-clock logging experiment measuring dropped
samples, jitter and overhead; changing this simulator's reporting grid alone
does not demonstrate those properties.
