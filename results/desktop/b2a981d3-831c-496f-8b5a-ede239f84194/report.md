# Fuel map and engine response comparison

Synthetic data from an uncalibrated model with an assumed lambda-to-torque relationship.
Results describe these equations and parameters; they do not establish real-engine tuning gains.

Model 0.3.0-fuel-map-coupling. Integration 0.001 s; reporting 50 Hz.

| Scenario | Fuel map | Final mean AFR | Final mean RPM | AFR RMSE after 5 s |
| --- | --- | ---: | ---: | ---: |
| steady_idle | dynamic_baseline | 14.6727 | 1624.97 | 0.3675 |

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
