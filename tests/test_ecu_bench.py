import csv
import json
import math
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from ecu_bench import FuelMap, Protocol, run_experiment, sha256, simulate, summarise


class FuelMapTests(unittest.TestCase):
    def setUp(self):
        # Unequal axis spacing catches index-based interpolation mistakes.
        self.table = FuelMap("test", (1000, 2000, 5000), (20, 80),
                             ((0.8, 1.0, 1.3), (1.0, 1.2, 1.5)))

    def test_exact_nodes_and_upper_boundary(self):
        self.assertAlmostEqual(self.table.lookup(1000, 20), 0.8)
        self.assertAlmostEqual(self.table.lookup(2000, 80), 1.2)
        self.assertAlmostEqual(self.table.lookup(5000, 80), 1.5)

    def test_bilinear_interpolation_on_nonuniform_axes(self):
        self.assertAlmostEqual(self.table.lookup(3500, 50), 1.25)
        self.assertAlmostEqual(self.table.lookup(1500, 35), 0.95)

    def test_rejects_extrapolation_and_nonfinite_inputs(self):
        for rpm, pressure in ((999, 30), (5001, 30), (1500, 19), (1500, 81), (math.nan, 30)):
            with self.subTest(rpm=rpm, pressure=pressure), self.assertRaises(ValueError):
                self.table.lookup(rpm, pressure)

    def test_rejects_invalid_map_geometry_and_values(self):
        cases = [
            ((1000, 1000), (20, 80), ((1, 1), (1, 1))),
            ((2000, 1000), (20, 80), ((1, 1), (1, 1))),
            ((1000, 2000), (20, 80), ((1, 1),)),
            ((1000, 2000), (20, 80), ((1,), (1, 1))),
            ((1000, 2000), (20, 80), ((1, math.nan), (1, 1))),
            ((1000, 2000), (20, 80), ((1, 0), (1, 1))),
        ]
        for rpm, pressure, values in cases:
            with self.subTest(values=values), self.assertRaises(ValueError):
                FuelMap("invalid", rpm, pressure, values)

    def test_schema_round_trip_and_unknown_schema(self):
        self.assertEqual(FuelMap.from_dict(self.table.to_dict()), self.table)
        with self.assertRaises(ValueError):
            FuelMap.from_dict({"schema": "unknown"})


class BenchTests(unittest.TestCase):
    def setUp(self):
        self.protocol = Protocol()
        self.baseline = FuelMap("baseline", (800, 6000), (30, 100), ((1, 1), (1, 1)))
        self.richer = replace(self.baseline, name="plus10", values=((1.1, 1.1), (1.1, 1.1)))

    def test_reference_map_holds_target_and_sample_grid(self):
        samples = simulate(self.baseline, self.protocol)
        self.assertEqual(len(samples), 501)
        self.assertEqual(samples[0]["time_s"], 0)
        self.assertEqual(samples[-1]["time_s"], 10)
        self.assertTrue(all(abs(s["afr"] - 14.7) < 1e-12 for s in samples))

    def test_step_timing_and_analytical_transient(self):
        samples = simulate(self.richer, self.protocol)
        self.assertEqual(samples[249]["fuel_multiplier"], 1.0)
        self.assertEqual(samples[250]["fuel_multiplier"], 1.1)
        self.assertAlmostEqual(samples[250]["afr"], 14.7)
        initial_fuel = 20 / 14.7
        expected_fuel = initial_fuel * (1.1 - 0.1 * math.exp(-1 / 0.2))
        self.assertAlmostEqual(samples[300]["fuel_delivered_g_s"], expected_fuel)
        self.assertTrue(all(b["afr"] <= a["afr"] for a, b in zip(samples[250:], samples[251:])))

    def test_richer_and_leaner_maps_match_steady_state_identity(self):
        for multiplier in (0.9, 1.1):
            table = replace(self.baseline, values=((multiplier, multiplier), (multiplier, multiplier)))
            samples = simulate(table, self.protocol)
            self.assertAlmostEqual(samples[-1]["afr"], 14.7 / multiplier, places=9)
            self.assertTrue(all(s["fuel_delivered_g_s"] > 0 and math.isfinite(s["afr"]) for s in samples))

    def test_identical_configuration_reproduces_numerical_samples(self):
        self.assertEqual(simulate(self.richer, self.protocol), simulate(self.richer, self.protocol))

    def test_exact_update_agrees_at_shared_times_across_sample_rates(self):
        coarse = simulate(self.richer, replace(self.protocol, sampling_rate_hz=10))
        fine = simulate(self.richer, self.protocol)
        for index, sample in enumerate(coarse):
            self.assertAlmostEqual(sample["afr"], fine[index * 5]["afr"], places=11)

    def test_protocol_rejects_invalid_or_misaligned_experiments(self):
        for changes in ({"sampling_rate_hz": 0}, {"fuel_time_constant_s": math.nan},
                        {"map_change_time_s": 10}, {"map_change_time_s": 5.001},
                        {"duration_s": 10.001}, {"steady_window_s": 6}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                replace(self.protocol, **changes)

    def test_metrics_use_documented_windows(self):
        summary = summarise(simulate(self.richer, self.protocol), self.richer, self.protocol)
        self.assertEqual(summary["final_window_sample_count"], 51)
        self.assertAlmostEqual(summary["final_window_mean_afr"], 14.7 / 1.1, places=8)
        self.assertGreater(summary["post_change_afr_rmse"], 0)

    def test_exports_have_unique_ids_snapshots_and_consistent_hashes(self):
        with tempfile.TemporaryDirectory() as temporary:
            first = run_experiment(temporary, self.baseline, self.richer, self.protocol)
            second = run_experiment(temporary, self.baseline, self.richer, self.protocol)
            self.assertNotEqual(first, second)
            manifest = json.loads((first / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["data_origin"], "synthetic_simulation")
            self.assertEqual(manifest["model_sha256"], sha256(first / "model_snapshot.py"))
            ids = []
            for run in manifest["runs"]:
                ids.append(run["run_id"])
                self.assertEqual(run["map_sha256"], sha256(first / run["map_file"]))
                self.assertEqual(run["data_sha256"], sha256(first / run["data_file"]))
                with (first / run["data_file"]).open(encoding="utf-8", newline="") as stream:
                    rows = list(csv.DictReader(stream))
                self.assertEqual(len(rows), 501)
                self.assertTrue(all(row["run_id"] == run["run_id"] for row in rows))
            self.assertEqual(len(set(ids)), 2)
            with (first / "candidate.csv").open(encoding="utf-8", newline="") as stream:
                first_rows = list(csv.DictReader(stream))
            with (second / "candidate.csv").open(encoding="utf-8", newline="") as stream:
                second_rows = list(csv.DictReader(stream))
            self.assertEqual([{k: v for k, v in row.items() if k != "run_id"} for row in first_rows],
                             [{k: v for k, v in row.items() if k != "run_id"} for row in second_rows])


if __name__ == "__main__":
    unittest.main()
