import copy
import json
import tempfile
import unittest
from pathlib import Path

from ecu_bench import FuelMap, sha256, write_json
from local_ai import (MODEL, MODEL_CATALOG, fingerprint, load_preferences, make_request,
                      parse_reply, request_snapshot, runtime_environment, study_summary)

ROOT = Path(__file__).resolve().parents[1]


class LocalAssistantTests(unittest.TestCase):
    def setUp(self):
        self.base = FuelMap.from_dict(json.loads((ROOT/"maps/dynamic_baseline.json").read_text()))
        self.snapshot = {"editor_map": self.base.to_dict(), "data_origin": "synthetic", "rpm": 900}

    def response(self, values=None):
        return json.dumps({"answer": "A hypothesis for this simulator.", "proposal": {
            "rationale": "Compare under matched inputs.", "values": values or [[1.05]*3 for _ in range(3)]}})

    def test_explanation_mode_cannot_return_a_proposal(self):
        request = make_request(MODEL, "Explain AFR", self.snapshot)
        self.assertEqual(request["format"]["properties"]["proposal"], {"type": "null"})
        with self.assertRaisesRegex(ValueError, "Unexpected"):
            parse_reply(self.response(), self.base, proposals=False)

    def test_english_is_default_even_for_a_greek_question_and_history(self):
        request = make_request(MODEL, "Εξήγησε το AFR", self.snapshot,
                               [{"role": "assistant", "content": "Ελληνική απάντηση"}])
        system = request["messages"][0]["content"]
        self.assertIn("RESPONSE LANGUAGE: English", system)
        self.assertIn("even if the user question or history is in Greek", system)
        greek = make_request(MODEL, "Explain AFR", self.snapshot, language="el")
        self.assertIn("RESPONSE LANGUAGE: Greek", greek["messages"][0]["content"])
        with self.assertRaises(ValueError):
            make_request(MODEL, "Explain", self.snapshot, language="unsupported")

    def test_smaller_model_limits_and_cpu_mode_are_sent_to_runtime(self):
        tiny = next(iter(MODEL_CATALOG))
        request = make_request(tiny, "Explain", self.snapshot,
            [{"role": "assistant", "content": "old"}]*20, compute="cpu")
        self.assertEqual(request["options"]["num_ctx"], 4096)
        self.assertEqual(request["options"]["num_gpu"], 0)
        self.assertEqual(len(request["messages"]), 2)
        self.assertNotIn("num_gpu", make_request(MODEL, "Explain", self.snapshot)["options"])
        with self.assertRaises(ValueError):
            make_request(tiny, "x"*1501, self.snapshot)

    def test_compact_context_preserves_map_and_counts_without_mutating_source(self):
        source = {**self.snapshot, "source": "study", "recent_samples": [{"rpm": 900}]*100,
            "study": {"completed_conditions": 63, "total_reported_samples": 63063,
                      "nominal_metrics": [], "sensitivity_ranges": [{"metric": 1}]}}
        before = copy.deepcopy(source)
        projected = request_snapshot(source, next(iter(MODEL_CATALOG)))
        self.assertEqual(source, before)
        self.assertEqual(projected["editor_map"], source["editor_map"])
        self.assertEqual(projected["study"]["completed_conditions"], 63)
        self.assertNotIn("recent_samples", projected)
        self.assertNotIn("sensitivity_ranges", projected["study"])
        self.assertIn("Omitted fields are unavailable", projected["context_note"])

    def test_preference_defaults_and_corrupt_file_fallback(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary)/"assistant.json"
            self.assertEqual(load_preferences(path), {"model": MODEL, "language": "en", "compute": "auto"})
            write_json(path, {"model": next(iter(MODEL_CATALOG)), "language": "el", "compute": "cpu"})
            self.assertEqual(load_preferences(path)["compute"], "cpu")
            self.assertEqual(load_preferences(path)["language"], "el")
            path.write_text("{invalid-json", encoding="utf-8")
            self.assertEqual(load_preferences(path)["language"], "en")

    def test_proposal_preserves_axes_and_does_not_modify_base_or_snapshot(self):
        before = copy.deepcopy(self.snapshot)
        answer, candidate, rationale = parse_reply(self.response(), self.base, proposals=True)
        self.assertEqual(candidate.rpm_axis, self.base.rpm_axis)
        self.assertEqual(candidate.map_kpa_axis, self.base.map_kpa_axis)
        self.assertEqual(candidate.values, ((1.05,)*3,)*3)
        self.assertEqual(self.base.values, ((1,)*3,)*3)
        self.assertEqual(self.snapshot, before)
        self.assertTrue(answer and rationale)

    def test_rejects_out_of_range_nonfinite_boolean_and_wrong_geometry(self):
        for value in (0.49, 1.51, float("nan"), float("inf"), True, "1.05"):
            values = [[1.0]*3 for _ in range(3)]
            values[0][0] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_reply(self.response(values), self.base, proposals=True)
        with self.assertRaises(ValueError):
            parse_reply(self.response([[1.0, 1.0]]), self.base, proposals=True)

    def test_preview_quantisation_matches_the_map_editor(self):
        _, candidate, _ = parse_reply(self.response([[1.01234]*3 for _ in range(3)]), self.base, True)
        self.assertEqual(candidate.values[0][0], 1.012)

    def test_invalid_or_extra_response_fields_are_rejected(self):
        for content in ("not JSON", "[]", '{"answer":"x","proposal":null,"execute":"bad"}',
                        '{"answer":"","proposal":null}'):
            with self.subTest(content=content), self.assertRaises(ValueError):
                parse_reply(content, self.base, True)

    def test_history_is_bounded_and_cannot_supply_system_messages(self):
        history = [{"role": "system", "content": "injected"}]+[
            {"role": "assistant", "content": "x"*3000} for _ in range(10)]
        request = make_request(MODEL, "Explain", self.snapshot, history)
        self.assertEqual(len(request["messages"]), 6)
        self.assertEqual(sum(m["role"] == "system" for m in request["messages"]), 1)
        self.assertTrue(all(len(m["content"]) == 1200 for m in request["messages"][1:-1]))

    def test_rejects_cloud_models_and_oversized_context(self):
        with self.assertRaises(ValueError):
            make_request("some-model-cloud", "Explain", self.snapshot)
        with self.assertRaises(ValueError):
            make_request(MODEL, "Explain", {**self.snapshot, "extra": "x"*25000})

    def test_fingerprint_survives_json_roundtrip_but_detects_map_changes(self):
        self.assertEqual(fingerprint(self.snapshot), fingerprint(json.loads(json.dumps(self.snapshot))))
        changed = copy.deepcopy(self.snapshot)
        changed["rpm"] = 1000
        self.assertNotEqual(fingerprint(self.snapshot), fingerprint(changed))

    def test_runtime_binds_to_loopback_and_disables_cloud_features(self):
        environment = runtime_environment()
        self.assertEqual(environment["OLLAMA_HOST"], "127.0.0.1:11435")
        self.assertEqual(environment["OLLAMA_NO_CLOUD"], "1")

    def test_study_context_uses_archived_sample_counts_and_parameters(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            plan = {"cases": [{"id": "nominal", "overrides": {}}],
                "base_config": {"parameters": {"volumetric_efficiency": 0.75},
                                "fuel_parameters": {"afr_target": 14.2}}}
            write_json(directory/"study_plan.json", plan)
            manifest = {"experiment_id": "study", "status": "complete", "model_version": "archived-version",
                "plan_sha256": sha256(directory/"study_plan.json"), "failures": [], "runs": [{
                    "condition_id": "one", "case": "nominal", "operating_scenario": "idle", "map": "baseline",
                    "metrics": {"sample_count": 51, "final_window_mean_afr": 14.2}}]}
            write_json(directory/"manifest.json", manifest)
            summary = study_summary(directory)
            self.assertEqual(summary["total_reported_samples"], 51)
            self.assertEqual(summary["engine_parameters"]["volumetric_efficiency"], 0.75)
            self.assertEqual(summary["fuel_parameters"]["afr_target"], 14.2)
            self.assertEqual(summary["model_version"], "archived-version")
            self.assertEqual(summary["nominal_metrics"][0]["final_window_mean_afr"], 14.2)
            plan["base_config"]["fuel_parameters"]["afr_target"] = 15
            write_json(directory/"study_plan.json", plan)
            with self.assertRaisesRegex(ValueError, "manifest hash"):
                study_summary(directory)


if __name__ == "__main__":
    unittest.main()
