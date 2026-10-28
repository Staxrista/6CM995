import json
import tempfile
import unittest
from pathlib import Path

from ecu_bench import sha256
from research_figures import render_figures
from research_study import (make_plan, mark_interrupted, paired_effects, read_samples,
    response_metrics, run_study, trace_hash, validate_plan)


class ResearchStudyTests(unittest.TestCase):
    def tiny_plan(self):
        plan = make_plan("nominal")
        plan["base_config"]["scenarios"] = plan["base_config"]["scenarios"][:1]
        plan["base_config"]["scenarios"][0]["duration_s"] = 0.1
        plan["condition_count"] = 3
        return plan

    def test_predefined_matrix_changes_one_parameter_at_a_time(self):
        plan = make_plan()
        validate_plan(plan)
        self.assertEqual(plan["condition_count"], 63)
        self.assertEqual(plan["repeat_verification_count"], 2)
        self.assertEqual(plan["cases"][0]["overrides"], {})
        self.assertTrue(all(len(c["overrides"]) == 1 for c in plan["cases"][1:]))
        self.assertEqual(make_plan("nominal")["condition_count"], 9)

    def test_rejects_miscounted_or_duplicate_design(self):
        plan = self.tiny_plan()
        plan["condition_count"] += 1
        with self.assertRaises(ValueError):
            validate_plan(plan)
        plan = make_plan()
        plan["base_config"]["scenarios"][1]["name"] = plan["base_config"]["scenarios"][0]["name"]
        with self.assertRaises(ValueError):
            validate_plan(plan)

    def response(self, speeds):
        samples = [{"time_s": t, "rpm": rpm, "afr": 14.7, "afr_target": 14.7}
                   for t, rpm in enumerate(speeds)]
        return response_metrics(samples, 0, 200, {"fraction": 0.02, "minimum_band_rpm": 1, "confirmation_s": 1})

    def test_settling_requires_all_remaining_samples_and_confirmation(self):
        result = self.response([100, 199, 205, 200, 200])
        self.assertEqual(result["rpm_settling_time_s"], 3)
        self.assertEqual(result["rpm_overshoot_percent"], 5)
        self.assertIsNone(self.response([100, 199, 205, 200])["rpm_settling_time_s"])

    def test_zero_change_has_no_overshoot_percentage(self):
        result = self.response([200, 200, 200])
        self.assertEqual(result["rpm_settling_time_s"], 0)
        self.assertIsNone(result["rpm_overshoot_percent"])

    def test_hash_ignores_numeric_spelling_but_detects_numerical_change(self):
        self.assertEqual(trace_hash([{"x": 1}]), trace_hash([{"x": 1.0}]))
        self.assertNotEqual(trace_hash([{"x": 1}]), trace_hash([{"x": 1.00000000001}]))

    def test_pairing_uses_same_case_and_handles_missing_settling(self):
        def record(case, fuel_map, value):
            return {"case": case, "operating_scenario": "idle", "map": fuel_map,
                "condition_id": case+fuel_map, "metrics": {"final_window_mean_rpm": value,
                "final_window_mean_afr": value, "post_5s_afr_rmse": value, "rpm_settling_time_s": None}}
        rows = paired_effects([record("nominal", "baseline", 10), record("bias", "baseline", 20),
                               record("bias", "plus10", 22)])
        self.assertEqual(rows[-1]["delta_final_window_mean_rpm"], 2)
        self.assertEqual(rows[-1]["reference_condition_id"], "biasbaseline")
        self.assertIsNone(rows[-1]["delta_rpm_settling_time_s"])

    def test_archive_preserves_plan_sources_and_numerical_evidence(self):
        with tempfile.TemporaryDirectory() as temp:
            plan = self.tiny_plan()
            events = []
            directory = run_study(plan, temp, plots=False, progress=events.append)
            manifest = json.loads((directory/"manifest.json").read_text())
            self.assertEqual(manifest["status"], "complete")
            self.assertEqual(len(manifest["runs"]), 3)
            self.assertTrue(all(c["matches"] for c in manifest["repeat_checks"]))
            self.assertEqual(len(manifest["repeat_checks"]), 2)
            self.assertEqual(manifest["plan_sha256"], sha256(directory/"study_plan.json"))
            for name, digest in manifest["source_sha256"].items():
                self.assertEqual(sha256(directory/name), digest)
            for record in manifest["runs"]:
                self.assertEqual(trace_hash(read_samples(directory/record["data_file"])), record["numerical_trace_sha256"])
                self.assertEqual(record["data_sha256"], sha256(directory/record["data_file"]))
            self.assertTrue((directory/"data_dictionary.json").is_file())
            self.assertNotIn("![", (directory/"report.md").read_text(encoding="utf-8"))
            self.assertEqual([e["event"] for e in events], ["started", "progress", "progress", "progress", "complete"])

    def test_failed_conditions_are_retained_and_not_reported_as_success(self):
        plan = self.tiny_plan()
        for item in plan["maps"]:
            item["fuel_map"]["rpm_axis"] = [2000, 3000, 7000]
        with tempfile.TemporaryDirectory() as temp:
            directory = run_study(plan, temp, plots=False)
            manifest = json.loads((directory/"manifest.json").read_text())
            self.assertEqual(manifest["status"], "complete_with_failures")
            self.assertEqual(len(manifest["failures"]), 3)
            self.assertEqual(manifest["runs"], [])
            self.assertIn("Failed conditions", (directory/"report.md").read_text(encoding="utf-8"))

    def test_plotting_rejects_modified_archived_data_before_loading_dependencies(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = run_study(self.tiny_plan(), temp, plots=False)
            manifest = json.loads((directory/"manifest.json").read_text())
            data_file = directory/manifest["runs"][0]["data_file"]
            with data_file.open("a", encoding="utf-8") as stream:
                stream.write("\n")
            with self.assertRaisesRegex(ValueError, "hash mismatch"):
                render_figures(directory)

    def test_interruption_marks_partial_study_without_changing_completed_study(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = run_study(self.tiny_plan(), temp, plots=False)
            path = directory/"manifest.json"
            before = path.read_bytes()
            mark_interrupted(directory)
            self.assertEqual(before, path.read_bytes())
            manifest = json.loads(before)
            manifest["status"] = "running"
            path.write_text(json.dumps(manifest), encoding="utf-8")
            mark_interrupted(directory)
            self.assertEqual(json.loads(path.read_text())["status"], "cancelled")


if __name__ == "__main__":
    unittest.main()
