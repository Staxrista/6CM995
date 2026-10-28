# Air path and speed experiment

Synthetic data from an uncalibrated model. Verification only; no real-engine performance claim.

Fuel mixture and indicated efficiency are assumed constant. Fuel and ignition maps are not coupled to torque yet.

Model: 0.2.0-air-path-and-speed. Internal integration step: 0.001 s. Reporting: 50 Hz.

| Scenario | Initial RPM | Final window mean RPM | Analytical final equilibrium RPM |
| --- | ---: | ---: | ---: |
| steady_idle | 900.00 | 900.00 | 900.00 |
| throttle_step | 900.00 | 1983.65 | 1983.71 |
| load_step | 1983.71 | 1555.11 | 1555.11 |

The analytical equilibrium is a reference from the same model, not independent engine evidence.
The final measurement window is the last simulated second, including endpoints.
For a short recording it may include a transient; the analytical equilibrium need not be reached.

Reproduce from this directory:

```text
python run_dynamics.py --config config.json --output-dir reproduced
```

Numerical traces should match under the recorded Python runtime. IDs and creation times will differ.
