# First fuel map verification experiment

All data are synthetic. This is software verification, not validation against an engine.

Model version: 0.1.0-fixed-operating-point
Operating point: 3000 RPM, 60 kPa absolute, 20 g/s prescribed air flow.
Protocol: 10 s, 50 Hz; map activation at 5 s.

| Condition | Post change AFR RMSE | Final window mean AFR | Analytical steady AFR |
| --- | ---: | ---: | ---: |
| baseline | 0.000000 | 14.700000 | 14.700000 |
| candidate | 1.296168 | 13.363636 | 13.363636 |

The analytical result follows from AFR_target / fuel_multiplier. Agreement verifies the
implementation of the chosen equations; it is not independent physical evidence or a tuning improvement.
The baseline is deliberately matched to the reference AFR by construction.

The fuel time constant is an illustrative assumption, not a measured injector or engine parameter.
Sampling here is the reporting grid of an exact first-order update. Logging latency is not measured.

Reproduce the numerical traces from this directory using:

```text
python model_snapshot.py --protocol protocol.json --baseline baseline_map.json --candidate candidate_map.json --output-dir reproduced
```

New run identifiers and creation times are expected; numerical telemetry must be identical.
