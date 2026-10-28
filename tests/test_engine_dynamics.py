import json
import math
import tempfile
import unittest
from dataclasses import replace

from engine_dynamics import (Inputs, Parameters, State, advance, default_config, derivatives,
                             equilibrium, observe, simulate_scenario, throttle_for_equilibrium)
from run_dynamics import run_suite


class DynamicsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = default_config()
        cls.parameters = Parameters()
        cls.datasets = [simulate_scenario(s, cls.parameters) for s in cls.config["scenarios"]]

    def test_closed_form_equilibrium_satisfies_mass_and_torque_balances(self):
        for inputs in (Inputs(0.1, 8), Inputs(0.25, 8), Inputs(0.25, 20)):
            state = equilibrium(inputs, self.parameters)
            dp, dw = derivatives(state, inputs, self.parameters)
            self.assertAlmostEqual(dp, 0, places=8)
            self.assertAlmostEqual(dw, 0, places=10)

    def test_idle_is_stationary_without_clamping_or_feedback(self):
        samples = self.datasets[0]
        self.assertEqual(len(samples), 1001)
        self.assertLess(max(s["rpm"] for s in samples) - min(s["rpm"] for s in samples), 1e-8)
        self.assertAlmostEqual(samples[-1]["rpm"], 900, places=8)

    def test_throttle_step_raises_pressure_then_speed(self):
        samples = self.datasets[1]
        before, event, after = samples[249], samples[250], samples[255]
        self.assertAlmostEqual(before["rpm"], event["rpm"], places=8)
        self.assertGreater(event["pressure_rate_kpa_s"], 0)
        self.assertGreater(after["map_kpa"], event["map_kpa"])
        self.assertGreater(after["rpm"], event["rpm"])
        self.assertGreater(samples[-1]["rpm"], samples[0]["rpm"])

    def test_load_step_reduces_speed_and_increases_equilibrium_pressure(self):
        samples = self.datasets[2]
        event = samples[250]
        self.assertEqual(event["external_load_nm"], 20)
        self.assertAlmostEqual(event["net_torque_nm"], -12, places=8)
        self.assertLess(samples[-1]["rpm"], samples[0]["rpm"])
        self.assertGreater(samples[-1]["map_kpa"], samples[0]["map_kpa"])

    def test_final_states_match_independent_equilibrium(self):
        for scenario, samples in zip(self.config["scenarios"], self.datasets):
            last = scenario["events"][-1]
            target = equilibrium(Inputs(last["throttle"], last["load_nm"]), self.parameters)
            self.assertAlmostEqual(samples[-1]["rpm"], target.rpm, delta=0.01)
            self.assertAlmostEqual(samples[-1]["map_kpa"], target.pressure_pa/1000, delta=0.001)

    def test_units_and_four_stroke_air_flow(self):
        state = State.from_readings(3000, 60)
        values = observe(state, Inputs(0.25, 8), self.parameters)
        expected = 0.8 * 0.002 * (3000/120) * 60000 / (287.05*300) * 1000
        self.assertAlmostEqual(values["cylinder_air_g_s"], expected)
        self.assertAlmostEqual(values["manifold_air_mass_g"], 60000*0.003/(287.05*300)*1000)

    def test_pressure_derivative_obeys_mass_conservation(self):
        values = observe(State.from_readings(2000, 40), Inputs(0.2, 8), self.parameters)
        mass_rate = self.parameters.manifold_volume_m3 / self.parameters.rt * values["pressure_rate_kpa_s"] * 1000
        self.assertAlmostEqual(mass_rate, (values["throttle_air_g_s"] - values["cylinder_air_g_s"])/1000)

    def test_inertia_changes_acceleration_not_static_equilibrium(self):
        inputs = Inputs(0.25, 20)
        state = equilibrium(Inputs(0.25, 8), self.parameters)
        heavier = replace(self.parameters, inertia_kg_m2=0.5)
        self.assertAlmostEqual(derivatives(state, inputs, heavier)[1], derivatives(state, inputs, self.parameters)[1]/2)
        self.assertAlmostEqual(equilibrium(inputs, heavier).rpm, equilibrium(inputs, self.parameters).rpm)

    def test_sampling_rate_does_not_change_internal_trajectory(self):
        scenario = self.config["scenarios"][1]
        coarse = simulate_scenario(scenario, self.parameters, sample_hz=10)
        for index, sample in enumerate(coarse):
            self.assertEqual(sample, self.datasets[1][index*5])

    def test_step_halving_converges(self):
        scenario = self.config["scenarios"][1]
        fine = simulate_scenario(scenario, self.parameters, dt=0.0005)
        maximum_error = max(abs(a["rpm"]-b["rpm"]) for a, b in zip(fine, self.datasets[1]))
        self.assertLess(maximum_error, 0.001)

    def test_invalid_inputs_parameters_and_stall_are_rejected(self):
        for throttle, load in ((-0.1, 8), (1.1, 8), (0.2, -1), (math.nan, 8)):
            with self.assertRaises(ValueError):
                Inputs(throttle, load)
        with self.assertRaises(ValueError):
            replace(self.parameters, inertia_kg_m2=0)
        with self.assertRaises(ValueError):
            advance(State.from_readings(400.01, 10), Inputs(0, 500), self.parameters, 0.001)

    def test_replay_is_deterministic(self):
        self.assertEqual(simulate_scenario(self.config["scenarios"][1], self.parameters), self.datasets[1])

    def test_invalid_event_and_reporting_grids_are_rejected(self):
        scenario = json.loads(json.dumps(self.config["scenarios"][1]))
        scenario["events"][1]["time_s"] = 5.0001
        with self.assertRaises(ValueError):
            simulate_scenario(scenario, self.parameters)
        with self.assertRaises(ValueError):
            simulate_scenario(self.config["scenarios"][1], self.parameters, sample_hz=37)

    def test_suite_saves_self_contained_reproduction_package(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = run_suite(self.config, temporary)
            manifest = json.loads((directory / "manifest.json").read_text())
            self.assertEqual(len(manifest["runs"]), 3)
            self.assertTrue((directory / "engine_dynamics.py").is_file())
            self.assertTrue((directory / "ecu_bench.py").is_file())
            self.assertEqual(manifest["data_origin"], "synthetic_simulation")

    def test_short_recording_can_be_saved_without_supported_final_equilibrium(self):
        config = json.loads(json.dumps(self.config))
        config["scenarios"] = [config["scenarios"][0]]
        config["scenarios"][0]["duration_s"] = 0.02
        config["scenarios"][0]["events"][0]["load_nm"] = 100
        with tempfile.TemporaryDirectory() as temporary:
            directory = run_suite(config, temporary)
            summary = json.loads((directory / "summary.json").read_text())
            self.assertEqual(summary[0]["sample_count"], 2)
            self.assertIsNone(summary[0]["analytical_equilibrium_rpm"])


if __name__ == "__main__":
    unittest.main()
