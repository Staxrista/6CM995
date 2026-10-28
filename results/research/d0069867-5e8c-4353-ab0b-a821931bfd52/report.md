# Controlled fuel map comparisons and sensitivity

Study status: complete. Model: 0.3.0-fuel-map-coupling. Study protocol: 0.1.0.
All data are synthetic. Results concern the stated equations, not measured vehicle performance.

## Method

Completed 63 of 63 conditions; 0 failed conditions. One deterministic execution per condition.
One-at-a-time parameter levels are illustrative probes, not measured tolerances. All cases preserve
the stored initial states, scenarios, maps, integration step and reporting rate except the named parameter.
Repeated identical traces verify software reproducibility and do not create independent physical samples.

## Tested sensitivity ranges

These are deterministic min/max ranges across completed cases, not confidence intervals.

| Scenario | Map | Cases | Final mean RPM range | AFR RMSE range |
| --- | --- | ---: | ---: | ---: |
| steady_idle | baseline | 7 | 795.28–900.00 | 0.0000–1.6333 |
| steady_idle | plus10 | 7 | 850.55–900.00 | 0.1485–2.5512 |
| steady_idle | minus10 | 7 | 654.92–891.46 | 0.1485–3.4482 |
| throttle_step | baseline | 7 | 1766.28–1983.71 | 0.5335–2.0589 |
| throttle_step | plus10 | 7 | 1881.23–1983.71 | 0.9164–2.4871 |
| throttle_step | minus10 | 7 | 1471.98–1966.04 | 0.9164–3.8035 |
| load_step | baseline | 7 | 1340.91–1555.11 | 0.0289–1.6063 |
| load_step | plus10 | 7 | 1454.10–1555.11 | 0.1365–2.5705 |
| load_step | minus10 | 7 | 1051.73–1537.69 | 0.1365–3.4062 |

## AFR error ranking

The smallest AFR RMSE in each case is listed for the tested maps only. Ties within 1e-9 are retained.
This does not identify an optimal real-engine tune.

| Case | Scenario | Lowest AFR RMSE map |
| --- | --- | --- |
| nominal | steady_idle | baseline |
| nominal | throttle_step | baseline |
| nominal | load_step | baseline |
| mixture_loss_none | steady_idle | baseline |
| mixture_loss_none | throttle_step | baseline |
| mixture_loss_none | load_step | baseline |
| mixture_loss_high | steady_idle | baseline |
| mixture_loss_high | throttle_step | baseline |
| mixture_loss_high | load_step | baseline |
| fuel_response_fast | steady_idle | baseline |
| fuel_response_fast | throttle_step | baseline |
| fuel_response_fast | load_step | baseline |
| fuel_response_slow | steady_idle | baseline |
| fuel_response_slow | throttle_step | baseline |
| fuel_response_slow | load_step | baseline |
| ecu_air_underestimate | steady_idle | plus10 |
| ecu_air_underestimate | throttle_step | plus10 |
| ecu_air_underestimate | load_step | plus10 |
| ecu_air_overestimate | steady_idle | minus10 |
| ecu_air_overestimate | throttle_step | minus10 |
| ecu_air_overestimate | load_step | minus10 |

## Reproducibility

Additional repeat checks: 2; matching numerical trace hashes: 2.
Per-run config, frozen map, CSV, numerical hash and metrics are linked by the manifest.

## Figures

![Nominal trace comparisons](figures/nominal_traces.png)

![Tested RPM sensitivity ranges](figures/sensitivity_ranges.png)

![ECU estimate and AFR error](figures/ecu_estimate_sweep.png)

Figures are also saved as PDFs. figure_provenance.json identifies plotted conditions and dependency versions.

## Limitations and interpretation

The nominal ECU estimate matches the plant by construction. The lambda penalty and its coefficient are assumed.
Map rankings and RPM effects are conditional on these assumptions. Changing the ECU estimate can change
which map compensates its bias. This is internal robustness evidence, not independent validation.
One-at-a-time variation does not estimate interactions or probabilistic uncertainty.
Settling and overshoot refer to the same-model equilibrium with the predefined band and confirmation period.
Unavailable settling time means it was not observed by the end; it is not replaced by zero.
Ignition, external calibration, critical literature review and the E4 wall-clock logging experiment remain open.

## Reproduction

Install the recorded plotting requirements once, then reproduce from this directory:

```text
python -m pip install --target .deps/research -r requirements-research-lock.txt
python research_study.py --plan study_plan.json --output-dir reproduced
```

To regenerate figures from these stored datasets without rerunning simulations:

```text
python research_study.py --render-only .
```

Use --plot-deps PATH to reuse an existing matching plotting environment. Use --no-plots for numerical-only replay.
UUIDs, wall times and file metadata may differ; compare numerical telemetry and metrics.
