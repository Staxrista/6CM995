# Fuel map and engine response comparison

Synthetic data from an uncalibrated model with an assumed lambda-to-torque relationship.
Results describe these equations and parameters; they do not establish real-engine tuning gains.

Model 0.3.0-fuel-map-coupling. Integration 0.001 s; reporting 50 Hz.

| Scenario | Fuel map | Final mean AFR | Final mean RPM | AFR RMSE after 5 s |
| --- | --- | ---: | ---: | ---: |
| steady_idle | dynamic_baseline | 14.7000 | 900.00 | 0.0000 |
| steady_idle | dynamic_plus_10_percent | 13.3636 | 886.27 | 1.3364 |
| steady_idle | dynamic_minus_10_percent | 16.3333 | 795.28 | 1.6333 |
| throttle_step | dynamic_baseline | 14.7000 | 1983.71 | 0.8640 |
| throttle_step | dynamic_plus_10_percent | 13.3636 | 1955.28 | 1.3895 |
| throttle_step | dynamic_minus_10_percent | 16.3333 | 1766.28 | 2.0589 |
| load_step | dynamic_baseline | 14.7000 | 1555.11 | 0.0546 |
| load_step | dynamic_plus_10_percent | 13.3636 | 1527.08 | 1.3566 |
| load_step | dynamic_minus_10_percent | 16.3333 | 1340.91 | 1.6063 |

Final means use the last simulated second including endpoints. Short recordings can remain transient.
AFR RMSE uses [5 s, end]; for recordings shorter than 5 s it uses the final sample only.
Fuel used is trapezoidal integration of the reported mass flow, not measured vehicle consumption.

The baseline's air estimate matches the plant by construction. The lambda loss coefficient is assumed,
so differences in RPM are conditional on that choice and require sensitivity analysis and calibration.
Ignition is not modelled in this version.

Reproduce from this directory:

```text
python run_fuel_dynamics.py --config config.json --output-dir reproduced
```

Numerical traces should match in the recorded runtime. UUIDs and creation times differ.
