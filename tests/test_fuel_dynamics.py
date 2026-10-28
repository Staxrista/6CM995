import copy
import json
import math
import tempfile
import unittest
from dataclasses import replace

from ecu_bench import FuelMap, sha256
from engine_dynamics import Inputs, Parameters, observe as air_observe
from fuel_dynamics import (FuelParameters, State, advance, comparison_config, default_config,
    derivatives, observe, simulate_scenario, uniform_equilibrium, uniform_map, validate_map_domain)
from run_fuel_dynamics import export_suite, run_suite


class FuelDynamicsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.parameters = Parameters()
        cls.fuel_parameters = FuelParameters()
        cls.maps = [uniform_map("baseline", 1.0), uniform_map("plus10", 1.1), uniform_map("minus10", 0.9)]
        cls.config = comparison_config(cls.maps)
        cls.datasets = [simulate_scenario(s, cls.parameters, cls.fuel_parameters) for s in cls.config["scenarios"]]

    def test_comparisons_start_with_identical_states_and_inputs(self):
        for offset in (0, 3, 6):
            group = self.config["scenarios"][offset:offset+3]
            self.assertTrue(all(s["initial"] == group[0]["initial"] for s in group))
            self.assertTrue(all(s["events"] == group[0]["events"] for s in group))
            self.assertTrue(all(abs(self.datasets[offset+i][0]["afr"]-14.7) < 1e-12 for i in range(3)))

    def test_map_changes_fuel_command_without_changing_plant_airflow(self):
        scenario = self.config["scenarios"][0]
        state = State.from_readings(**scenario["initial"])
        inputs = Inputs(scenario["events"][0]["throttle"], 8)
        baseline = observe(state, inputs, self.parameters, self.fuel_parameters, self.maps[0])
        richer = observe(state, inputs, self.parameters, self.fuel_parameters, self.maps[1])
        self.assertEqual(baseline["cylinder_air_g_s"], richer["cylinder_air_g_s"])
        self.assertAlmostEqual(richer["fuel_command_g_s"], baseline["fuel_command_g_s"]*1.1)
        self.assertEqual(baseline["afr"], richer["afr"])
        self.assertEqual(baseline["model_indicated_torque_nm"], richer["model_indicated_torque_nm"])
        self.assertGreater(derivatives(state, inputs, self.parameters, self.fuel_parameters, self.maps[1])[2], 0)

    def test_baseline_idle_is_stationary(self):
        samples = self.datasets[0]
        self.assertEqual(len(samples), 1001)
        self.assertLess(max(s["rpm"] for s in samples)-min(s["rpm"] for s in samples), 1e-8)
        self.assertTrue(all(abs(s["afr"]-14.7) < 1e-10 for s in samples))

    def test_uniform_maps_converge_to_analytical_afr_and_speed(self):
        for scenario, samples in zip(self.config["scenarios"], self.datasets):
            fuel_map = FuelMap.from_dict(scenario["fuel_map"])
            event = scenario["events"][-1]
            target = uniform_equilibrium(Inputs(event["throttle"], event["load_nm"]), self.parameters,
                                         self.fuel_parameters, fuel_map)
            multiplier = fuel_map.values[0][0]
            self.assertAlmostEqual(samples[-1]["afr"], 14.7/multiplier, delta=1e-4)
            self.assertAlmostEqual(samples[-1]["rpm"], target.rpm, delta=0.02)

    def test_closed_form_equilibria_satisfy_all_three_equations(self):
        for fuel_map in self.maps:
            inputs = Inputs(0.25, 8)
            state = uniform_equilibrium(inputs, self.parameters, self.fuel_parameters, fuel_map)
            dp, dw, df = derivatives(state, inputs, self.parameters, self.fuel_parameters, fuel_map)
            self.assertAlmostEqual(dp, 0, places=7)
            self.assertAlmostEqual(dw, 0, places=9)
            self.assertAlmostEqual(df, 0, places=12)

    def test_torque_respects_fuel_and_air_energy_bounds(self):
        original = State.from_readings(**self.config["scenarios"][3]["initial"])
        inputs = Inputs(0.25, 8)
        air_flow = air_observe(original, inputs, self.parameters)["cylinder_air_g_s"]/1000
        for relative_afr in (0.7, 1.0, 1.3):
            state = replace(original, fuel_mass_flow_kg_s=air_flow/(14.7*relative_afr))
            value = observe(state, inputs, self.parameters, self.fuel_parameters, self.maps[0])
            fuel_bound = self.parameters.indicated_efficiency*self.parameters.heating_value_j_kg*state.fuel_mass_flow_kg_s/state.omega_rad_s
            air_bound = self.parameters.indicated_efficiency*self.parameters.heating_value_j_kg*(air_flow/14.7)/state.omega_rad_s
            self.assertGreater(value["model_indicated_torque_nm"], 0)
            self.assertLessEqual(value["model_indicated_torque_nm"], min(fuel_bound, air_bound)+1e-12)

    def test_ecu_air_estimate_is_independent_of_plant_parameter(self):
        state = State.from_readings(**self.config["scenarios"][0]["initial"])
        inputs = Inputs(0.1, 8)
        a = observe(state, inputs, self.parameters, self.fuel_parameters, self.maps[0])
        b = observe(state, inputs, self.parameters, replace(self.fuel_parameters, ecu_volumetric_efficiency=0.72), self.maps[0])
        self.assertEqual(a["cylinder_air_g_s"], b["cylinder_air_g_s"])
        self.assertAlmostEqual(b["fuel_command_g_s"], 0.9*a["fuel_command_g_s"])

    def test_assumed_lambda_loss_changes_predicted_torque(self):
        inputs = Inputs(0.25, 8)
        state = uniform_equilibrium(inputs, self.parameters, self.fuel_parameters, self.maps[1])
        with_loss = observe(state, inputs, self.parameters, self.fuel_parameters, self.maps[1])
        without_loss = observe(state, inputs, self.parameters, replace(self.fuel_parameters, lambda_loss_coefficient=0), self.maps[1])
        self.assertGreater(without_loss["model_indicated_torque_nm"], with_loss["model_indicated_torque_nm"])

    def test_reporting_rate_does_not_change_the_trajectory(self):
        scenario = self.config["scenarios"][4]
        coarse = simulate_scenario(scenario, self.parameters, self.fuel_parameters, sample_hz=10)
        for index, sample in enumerate(coarse):
            self.assertEqual(sample, self.datasets[4][index*5])

    def test_step_halving_is_within_declared_tolerances(self):
        scenario = self.config["scenarios"][4]
        fine = simulate_scenario(scenario, self.parameters, self.fuel_parameters, dt=0.0005)
        self.assertLess(max(abs(a["rpm"]-b["rpm"]) for a,b in zip(fine,self.datasets[4])), 0.01)
        self.assertLess(max(abs(a["afr"]-b["afr"]) for a,b in zip(fine,self.datasets[4])), 1e-4)

    def test_invalid_fuel_and_insufficient_map_coverage_are_rejected(self):
        with self.assertRaises(ValueError):
            FuelParameters(response_time_s=0)
        with self.assertRaises(ValueError):
            FuelParameters(lambda_loss_coefficient=-1)
        state = State.from_readings(**self.config["scenarios"][0]["initial"])
        for value in (0, -1, math.nan):
            with self.assertRaises(ValueError):
                observe(replace(state, fuel_mass_flow_kg_s=value), Inputs(0.1, 8), self.parameters, self.fuel_parameters, self.maps[0])
        limited = FuelMap("limited", (800,6000), (30,100), ((1,1),(1,1)))
        with self.assertRaises(ValueError):
            validate_map_domain(limited, self.parameters)

    def test_export_keeps_frozen_maps_sources_and_numerical_data(self):
        config = copy.deepcopy(self.config)
        config["scenarios"] = config["scenarios"][0:3]
        with tempfile.TemporaryDirectory() as temporary:
            directory = export_suite(temporary, config, self.datasets[0:3])
            manifest = json.loads((directory/"manifest.json").read_text())
            self.assertEqual(len(manifest["runs"]), 3)
            for name, digest in manifest["source_sha256"].items():
                self.assertEqual(sha256(directory/name), digest)
            for run in manifest["runs"]:
                self.assertEqual(sha256(directory/run["fuel_map_file"]), run["fuel_map_sha256"])
            saved = json.loads((directory/"config.json").read_text())
            self.assertEqual(simulate_scenario(saved["scenarios"][1], self.parameters, self.fuel_parameters), self.datasets[1])
        with self.assertRaises(ValueError):
            run_suite({"schema": "air_path_speed_suite_v1"}, "unused")


if __name__ == "__main__":
    unittest.main()
