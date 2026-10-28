# Step 04 pilot: results and bounded interpretation

Protocol: [predefined sensitivity design](04_sensitivity_protocol.md).
Evidence: [complete study report](../results/research/d0069867-5e8c-4353-ab0b-a821931bfd52/report.md),
[metrics](../results/research/d0069867-5e8c-4353-ab0b-a821931bfd52/metrics.csv),
[paired differences](../results/research/d0069867-5e8c-4353-ab0b-a821931bfd52/paired_effects.csv).

All values are synthetic outputs of model 0.3.0. This pilot evaluates software
behaviour and sensitivity within explicitly assumed equations. It is not an
engine calibration, supervisor-approved final method or completed dissertation.

## Coverage and integrity

The study completed 63/63 conditions with no failed condition, comprising
63,063 reported samples. Each of the three operating scenarios was tested
with three maps under seven parameter cases. All sampled values passed the
finite/grid/domain checks; the integrator also checks its intermediate states.
Two additional nominal throttle/baseline simulations produced matching numerical
trace hashes. Repetitions test reproducibility, not independent physical validity.

The automated suite passed 50 tests. Desktop checks exercised the existing
controls and recording, real child-process study execution, UI responsiveness,
all three figure previews, and cancellation with a preserved partial report.
The saved package contains source/config/map/data hashes and figure provenance.

## Observed dependence on assumptions

For the throttle-step scenario, the following AFR errors use the predefined
RMSE window from 5 s to 20 s, including endpoints:

| ECU airflow-efficiency estimate | Baseline AFR RMSE | +10% fuel AFR RMSE | -10% fuel AFR RMSE | Lowest tested error |
| --- | ---: | ---: | ---: | --- |
| 0.72 | 2.0589 | 0.9164 | 3.8035 | +10% fuel |
| 0.80 | 0.8640 | 1.3895 | 2.0589 | Baseline |
| 0.88 | 1.3895 | 2.4871 | 0.9164 | -10% fuel |

The plant's volumetric efficiency remains 0.80 throughout this comparison.
Changing the ECU estimate therefore changes which map best compensates its
airflow bias. These conditional rankings do not identify a generally better tune.
The nominal baseline result also reflects an ECU estimate matched to the plant
by construction; it is not independent evidence of calibration quality.

The assumed lambda penalty has a substantial effect on the rich-map speed
prediction. Under the nominal penalty coefficient of 2, final-window mean speed
for the throttle step is 1983.71 RPM with baseline fuel and 1955.28 RPM with
+10% fuel. With that extra penalty removed, the corresponding means are both
approximately 1983.71 RPM. Their remaining sub-0.002 RPM difference is a finite
transient, not evidence of a physical power gain. The model's air/fuel energy
limit remains active even when the additional penalty is removed.

For the baseline throttle step, reducing the fuel time constant from 0.20 s
to 0.10 s reduces AFR RMSE from 0.8640 to 0.5335; increasing it to 0.40 s raises
RMSE to 1.3337. Final-window mean AFR stays close to 14.7. The response constant
thus affects transient error even when the model approaches the same steady
mixture. This is consistent with the predefined expectation, within this model.

## What can be claimed

The implementation supports matched map comparisons, documents sensitivity to
three provisional assumptions, and records enough information for numerical
reproduction and replotting. Deterministic min/max ranges summarise only the
tested parameter cases. No p-values, confidence intervals or real-engine tuning
gains are inferred. One-at-a-time changes do not estimate interactions or a
probability distribution over realistic engines.

Independent archived-source replay evidence is recorded in
[verification.json](../results/research/d0069867-5e8c-4353-ab0b-a821931bfd52/verification.json).
Its scope is numerical reproducibility and integrity of the saved package.

## Next research work

Justify or replace provisional laws and parameter levels through a critical
scholarly review; model and evaluate ignition effects; review the method with
the supervisor; and conduct E4 separately using wall-clock jitter, loss and
logging-overhead measurements. A simulator's consistent reporting grid alone
does not establish real-time telemetry performance.
