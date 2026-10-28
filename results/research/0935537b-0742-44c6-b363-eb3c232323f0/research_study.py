"""Predefined deterministic map comparisons and one-at-a-time sensitivity study."""

import argparse
import copy
import csv
import hashlib
import json
import math
import platform
import shutil
import struct
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from ecu_bench import FuelMap, sha256, write_json
from engine_dynamics import Inputs, Parameters
from fuel_dynamics import MODEL_VERSION, FuelParameters, default_config, simulate_scenario, uniform_equilibrium
from run_fuel_dynamics import metrics as fuel_metrics

ROOT = Path(__file__).resolve().parent
STUDY_VERSION = "0.1.0"
SOURCE_FILES = ("research_study.py", "research_figures.py", "ecu_bench.py",
                "engine_dynamics.py", "fuel_dynamics.py", "run_fuel_dynamics.py")


def atomic_json(path, data):
    temporary = path.with_suffix(path.suffix + ".tmp")
    write_json(temporary, data)
    temporary.replace(path)


def make_plan(mode="sensitivity"):
    if mode not in ("sensitivity", "nominal"):
        raise ValueError("Unknown study mode")
    maps = []
    for key, name in (("baseline", "dynamic_baseline.json"), ("plus10", "dynamic_plus_10_percent.json"),
                      ("minus10", "dynamic_minus_10_percent.json")):
        maps.append({"id": key, "fuel_map": json.loads((ROOT / "maps" / name).read_text(encoding="utf-8"))})
    cases = [{"id": "nominal", "overrides": {}}]
    if mode == "sensitivity":
        cases += [
            {"id": "mixture_loss_none", "overrides": {"lambda_loss_coefficient": 0.0}},
            {"id": "mixture_loss_high", "overrides": {"lambda_loss_coefficient": 4.0}},
            {"id": "fuel_response_fast", "overrides": {"response_time_s": 0.1}},
            {"id": "fuel_response_slow", "overrides": {"response_time_s": 0.4}},
            {"id": "ecu_air_underestimate", "overrides": {"ecu_volumetric_efficiency": 0.72}},
            {"id": "ecu_air_overestimate", "overrides": {"ecu_volumetric_efficiency": 0.88}},
        ]
    base = default_config()
    return {"schema": "ecu_research_study_v1", "study_version": STUDY_VERSION, "mode": mode,
            "base_config": base, "cases": cases, "maps": maps,
            "condition_count": len(cases)*len(maps)*len(base["scenarios"]),
            "executions_per_condition": 1, "repeat_verification_count": 2,
            "response": {"fraction": 0.02, "minimum_band_rpm": 1.0, "confirmation_s": 1.0},
            "uncertainty_interpretation": "deterministic tested ranges, not confidence intervals"}


def validate_plan(plan):
    if plan.get("schema") != "ecu_research_study_v1" or plan.get("executions_per_condition") != 1:
        raise ValueError("Unsupported study schema or repetition policy")
    for key in ("cases", "maps"):
        if not plan[key] or len({item["id"] for item in plan[key]}) != len(plan[key]):
            raise ValueError(f"{key} must have unique identifiers")
    if "nominal" not in {c["id"] for c in plan["cases"]} or "baseline" not in {m["id"] for m in plan["maps"]}:
        raise ValueError("Nominal case and baseline map are required")
    base = plan["base_config"]
    if not base["scenarios"]:
        raise ValueError("At least one operating scenario is required")
    if len({s["name"] for s in base["scenarios"]}) != len(base["scenarios"]):
        raise ValueError("Operating scenario names must be unique")
    Parameters(**base["parameters"])
    for case in plan["cases"]:
        FuelParameters(**{**base["fuel_parameters"], **case["overrides"]})
    for item in plan["maps"]:
        FuelMap.from_dict(item["fuel_map"])
    if plan["condition_count"] != len(plan["cases"])*len(plan["maps"])*len(base["scenarios"]):
        raise ValueError("Predeclared condition count does not match the design")
    if type(plan["repeat_verification_count"]) is not int or plan["repeat_verification_count"] < 1:
        raise ValueError("At least one repeat verification is required")
    for key in ("fraction", "minimum_band_rpm", "confirmation_s"):
        value = plan["response"][key]
        if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value) or value <= 0:
            raise ValueError("Response criteria must be finite and positive")


def trace_hash(samples):
    """Hash numerical doubles, independent of CSV int/float spelling and UUIDs."""
    keys = sorted(samples[0])
    digest = hashlib.sha256(json.dumps(keys).encode("utf-8"))
    for sample in samples:
        for key in keys:
            digest.update(struct.pack(">d", float(sample[key])))
    return digest.hexdigest()


def read_samples(path):
    with path.open(encoding="utf-8", newline="") as stream:
        return [{key: float(value) for key, value in row.items() if key != "run_id"}
                for row in csv.DictReader(stream)]


def response_metrics(samples, event_time, target_rpm, criteria):
    post = [s for s in samples if s["time_s"] >= event_time]
    result = {"rpm_settling_time_s": None, "rpm_overshoot_percent": None,
              "rpm_settling_band_rpm": None,
              "maximum_absolute_afr_error": max(abs(s["afr"]-s["afr_target"]) for s in post),
              "minimum_afr": min(s["afr"] for s in samples), "maximum_afr": max(s["afr"] for s in samples)}
    if target_rpm is None:
        return result
    change = target_rpm - post[0]["rpm"]
    band = max(criteria["minimum_band_rpm"], abs(change)*criteria["fraction"])
    result["rpm_settling_band_rpm"] = band
    if abs(change) > 1e-9:
        direction = 1 if change > 0 else -1
        result["rpm_overshoot_percent"] = 100*max(0, max((s["rpm"]-target_rpm)*direction for s in post))/abs(change)
    last_outside = max((i for i,s in enumerate(post) if abs(s["rpm"]-target_rpm) > band), default=-1)
    settled_index = last_outside+1
    if settled_index < len(post) and post[-1]["time_s"]-post[settled_index]["time_s"] >= criteria["confirmation_s"]-1e-9:
        result["rpm_settling_time_s"] = post[settled_index]["time_s"]-event_time
    return result


def checked_metrics(samples, scenario, parameters, fuel_parameters, base, criteria):
    expected = round(scenario["duration_s"]*base["sampling_rate_hz"])+1
    if len(samples) != expected:
        raise ValueError("Unexpected sample count")
    for index, sample in enumerate(samples):
        if any(not math.isfinite(value) for value in sample.values()):
            raise ValueError("Nonfinite telemetry")
        if abs(sample["time_s"]-index/base["sampling_rate_hz"]) > 1e-9:
            raise ValueError("Incorrect simulation timestamp grid")
        if sample["fuel_delivered_g_s"] <= 0:
            raise ValueError("Nonpositive delivered fuel")
        if not parameters.minimum_rpm <= sample["rpm"] <= parameters.maximum_rpm:
            raise ValueError("RPM domain violation")
        if not parameters.minimum_pressure_pa/1000 <= sample["map_kpa"] <= parameters.ambient_pressure_pa/1000:
            raise ValueError("Pressure domain violation")
    result = fuel_metrics(samples, scenario, parameters, fuel_parameters)
    result.update(response_metrics(samples, scenario["events"][-1]["time_s"],
                                   result["same_model_equilibrium_rpm"], criteria))
    return result


def paired_effects(records):
    references = {(r["case"],r["operating_scenario"]): r for r in records if r["map"] == "baseline"}
    effects = []
    for record in records:
        reference = references.get((record["case"],record["operating_scenario"]))
        if not reference:
            continue
        effect = {"condition_id": record["condition_id"], "case": record["case"],
                  "operating_scenario": record["operating_scenario"], "map": record["map"],
                  "reference_condition_id": reference["condition_id"]}
        for key in ("final_window_mean_rpm", "final_window_mean_afr", "post_5s_afr_rmse", "rpm_settling_time_s"):
            a,b = record["metrics"][key], reference["metrics"][key]
            effect["delta_"+key] = a-b if a is not None and b is not None else None
        effects.append(effect)
    return effects


def sensitivity_ranges(records):
    groups = {}
    for record in records:
        groups.setdefault((record["operating_scenario"], record["map"]), []).append(record)
    ranges = []
    for (scenario, fuel_map), group in groups.items():
        row = {"operating_scenario": scenario, "map": fuel_map, "tested_case_count": len(group)}
        for key in ("final_window_mean_rpm", "final_window_mean_afr", "post_5s_afr_rmse"):
            values = [r["metrics"][key] for r in group]
            row[key+"_min"], row[key+"_max"] = min(values), max(values)
        ranges.append(row)
    return ranges


def write_csv(path, rows):
    if not rows:
        return
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def write_report(directory, manifest):
    records = manifest["runs"]
    ranges = sensitivity_ranges(records)
    lines = ["# Controlled fuel map comparisons and sensitivity", "",
        f"Study status: {manifest['status']}. Model: {MODEL_VERSION}. Study protocol: {STUDY_VERSION}.",
        "All data are synthetic. Results concern the stated equations, not measured vehicle performance.", "",
        "## Method", "", f"Completed {len(records)} of {manifest['expected_conditions']} conditions; "
        f"{len(manifest['failures'])} failed conditions. One deterministic execution per condition.",
        "One-at-a-time parameter levels are illustrative probes, not measured tolerances. All cases preserve",
        "the stored initial states, scenarios, maps, integration step and reporting rate except the named parameter.",
        "Repeated identical traces verify software reproducibility and do not create independent physical samples.", "",
        "## Tested sensitivity ranges", "",
        "These are deterministic min/max ranges across completed cases, not confidence intervals.", "",
        "| Scenario | Map | Cases | Final mean RPM range | AFR RMSE range |", "| --- | --- | ---: | ---: | ---: |"]
    for row in ranges:
        lines.append(f"| {row['operating_scenario']} | {row['map']} | {row['tested_case_count']} | "
            f"{row['final_window_mean_rpm_min']:.2f}–{row['final_window_mean_rpm_max']:.2f} | "
            f"{row['post_5s_afr_rmse_min']:.4f}–{row['post_5s_afr_rmse_max']:.4f} |")
    lines += ["", "## AFR error ranking", "",
        "The smallest AFR RMSE in each case is listed for the tested maps only. Ties within 1e-9 are retained.",
        "This does not identify an optimal real-engine tune.", "", "| Case | Scenario | Lowest AFR RMSE map |", "| --- | --- | --- |"]
    groups = {}
    for record in records:
        groups.setdefault((record["case"], record["operating_scenario"]), []).append(record)
    for (case,scenario), group in groups.items():
        minimum = min(r["metrics"]["post_5s_afr_rmse"] for r in group)
        winners = ", ".join(r["map"] for r in group if abs(r["metrics"]["post_5s_afr_rmse"]-minimum) <= 1e-9)
        lines.append(f"| {case} | {scenario} | {winners} |")
    lines += ["", "## Reproducibility", "",
        f"Additional repeat checks: {len(manifest['repeat_checks'])}; "
        f"matching numerical trace hashes: {sum(r['matches'] for r in manifest['repeat_checks'])}.",
        "Per-run config, frozen map, CSV, numerical hash and metrics are linked by the manifest.", "",
        "## Figures", ""]
    if manifest.get("figures_generated"):
        lines += ["![Nominal trace comparisons](figures/nominal_traces.png)", "",
            "![Tested RPM sensitivity ranges](figures/sensitivity_ranges.png)", "",
            "![ECU estimate and AFR error](figures/ecu_estimate_sweep.png)", "",
            "Figures are also saved as PDFs. figure_provenance.json identifies plotted conditions and dependency versions.", ""]
    else:
        lines += ["No complete figure set has been generated for this study.", ""]
    lines += [
        "## Limitations and interpretation", "",
        "The nominal ECU estimate matches the plant by construction. The lambda penalty and its coefficient are assumed.",
        "Map rankings and RPM effects are conditional on these assumptions. Changing the ECU estimate can change",
        "which map compensates its bias. This is internal robustness evidence, not independent validation.",
        "One-at-a-time variation does not estimate interactions or probabilistic uncertainty.",
        "Settling and overshoot refer to the same-model equilibrium with the predefined band and confirmation period.",
        "Unavailable settling time means it was not observed by the end; it is not replaced by zero.",
        "Ignition, external calibration, critical literature review and the E4 wall-clock logging experiment remain open.", "",
        "## Reproduction", "", "Install the recorded plotting requirements once, then reproduce from this directory:", "",
        "```text", "python -m pip install --target .deps/research -r requirements-research-lock.txt",
        "python research_study.py --plan study_plan.json --output-dir reproduced", "```", "",
        "To regenerate figures from these stored datasets without rerunning simulations:", "", "```text",
        "python research_study.py --render-only .", "```", "",
        "Use --plot-deps PATH to reuse an existing matching plotting environment. Use --no-plots for numerical-only replay.",
        "UUIDs, wall times and file metadata may differ; compare numerical telemetry and metrics.", ""]
    if manifest["failures"]:
        lines += ["## Failed conditions", ""]
        lines += [f"- {failure['condition_id']}: {failure['error']}" for failure in manifest["failures"]]
    (directory/"report.md").write_text("\n".join(lines), encoding="utf-8")
    write_json(directory/"sensitivity_ranges.json", ranges)
    write_csv(directory/"paired_effects.csv", paired_effects(records))


def mark_interrupted(directory, status="cancelled"):
    path = directory/"manifest.json"
    if path.is_file():
        manifest = json.loads(path.read_text(encoding="utf-8"))
        if manifest["status"] in ("running", "rendering"):
            manifest["status"] = status
            atomic_json(path, manifest)
            write_report(directory, manifest)


def run_study(plan, output_root, plots=True, plot_deps=None, progress=None):
    validate_plan(plan)
    notify = progress or (lambda event: None)
    if plots:
        from research_figures import plotting_environment
        plotting_environment(plot_deps)
    study_id = str(uuid.uuid4())
    directory = Path(output_root)/study_id
    directory.mkdir(parents=True, exist_ok=False)
    atomic_json(directory/"study_plan.json", plan)
    sources = {}
    for name in SOURCE_FILES:
        shutil.copyfile(ROOT/name, directory/name)
        sources[name] = sha256(directory/name)
    for name in ("requirements-research.txt", "requirements-research-lock.txt"):
        if (ROOT/name).is_file():
            shutil.copyfile(ROOT/name, directory/name)
    if (ROOT/"docs/04_sensitivity_protocol.md").is_file():
        shutil.copyfile(ROOT/"docs/04_sensitivity_protocol.md", directory/"protocol.md")
    manifest = {"experiment_id": study_id, "study_version": STUDY_VERSION, "model_version": MODEL_VERSION,
        "created_at_utc": datetime.now(timezone.utc).isoformat(), "python_version": platform.python_version(),
        "data_origin": "synthetic_simulation", "random_seed": None, "status": "running",
        "expected_conditions": plan["condition_count"], "source_sha256": sources,
        "plan_sha256": sha256(directory/"study_plan.json"), "runs": [], "failures": [], "repeat_checks": []}
    atomic_json(directory/"manifest.json", manifest)
    notify({"event": "started", "directory": str(directory.resolve()), "total": plan["condition_count"]})
    base = plan["base_config"]
    parameters = Parameters(**base["parameters"])
    reference = None
    attempted = 0
    for case in plan["cases"]:
        fp_dict = {**base["fuel_parameters"], **case["overrides"]}
        fuel_parameters = FuelParameters(**fp_dict)
        for original in base["scenarios"]:
            for item in plan["maps"]:
                attempted += 1
                condition_id = f"condition_{attempted:03d}"
                run_dir = directory/"runs"/condition_id
                run_dir.mkdir(parents=True)
                scenario = copy.deepcopy(original)
                scenario["fuel_map"] = copy.deepcopy(item["fuel_map"])
                scenario["condition"] = item["id"]
                config = {**copy.deepcopy(base), "fuel_parameters": fp_dict, "scenarios": [scenario]}
                write_json(run_dir/"config.json", config)
                write_json(run_dir/"fuel_map.json", item["fuel_map"])
                started = time.perf_counter()
                try:
                    samples = simulate_scenario(scenario, parameters, fuel_parameters, base["integration_step_s"], base["sampling_rate_hz"])
                    measured = checked_metrics(samples, scenario, parameters, fuel_parameters, base, plan["response"])
                    run_id = str(uuid.uuid4())
                    write_csv(run_dir/"telemetry.csv", [{"run_id": run_id, **s} for s in samples])
                    write_json(run_dir/"metrics.json", measured)
                    record = {"condition_id": condition_id, "run_id": run_id, "case": case["id"],
                        "operating_scenario": original.get("operating_scenario", original["name"]),
                        "map": item["id"], "fuel_parameters": fp_dict, "metrics": measured,
                        "elapsed_wall_s": time.perf_counter()-started, "numerical_trace_sha256": trace_hash(samples),
                        "data_file": str((run_dir/"telemetry.csv").relative_to(directory)).replace("\\", "/"),
                        "data_sha256": sha256(run_dir/"telemetry.csv"),
                        "config_file": str((run_dir/"config.json").relative_to(directory)).replace("\\", "/"),
                        "config_sha256": sha256(run_dir/"config.json"), "fuel_map_sha256": sha256(run_dir/"fuel_map.json")}
                    manifest["runs"].append(record)
                    if case["id"] == "nominal" and item["id"] == "baseline":
                        if reference is None or record["operating_scenario"] == "throttle_step":
                            reference = (record, scenario, fuel_parameters)
                except (ValueError, ArithmeticError) as error:
                    manifest["failures"].append({"condition_id": condition_id, "case": case["id"],
                        "operating_scenario": original["name"], "map": item["id"], "error": str(error)})
                atomic_json(directory/"manifest.json", manifest)
                notify({"event": "progress", "done": attempted, "total": plan["condition_count"],
                        "case": case["id"], "scenario": original["name"], "failures": len(manifest["failures"])})
    if reference:
        record, scenario, fp = reference
        for index in range(plan["repeat_verification_count"]):
            repeated = simulate_scenario(scenario, parameters, fp, base["integration_step_s"], base["sampling_rate_hz"])
            digest = trace_hash(repeated)
            manifest["repeat_checks"].append({"repeat": index+1, "reference_condition_id": record["condition_id"],
                "numerical_trace_sha256": digest, "matches": digest == record["numerical_trace_sha256"]})
    write_csv(directory/"metrics.csv", [{"condition_id": r["condition_id"], "case": r["case"],
        "operating_scenario": r["operating_scenario"], "map": r["map"], **r["metrics"]} for r in manifest["runs"]])
    write_json(directory/"data_dictionary.json", data_dictionary())
    failed_replay = not reference or any(not c["matches"] for c in manifest["repeat_checks"])
    manifest["status"] = "complete_with_failures" if manifest["failures"] or failed_replay else "complete"
    if plots and manifest["runs"]:
        manifest["status"] = "rendering"
        atomic_json(directory/"manifest.json", manifest)
        notify({"event": "rendering"})
        try:
            from research_figures import render_figures
            render_figures(directory, plot_deps)
        except Exception as error:
            manifest["status"] = "failed"
            manifest["figure_error"] = str(error)
            atomic_json(directory/"manifest.json", manifest)
            write_report(directory, manifest)
            raise
        manifest["status"] = "complete_with_failures" if manifest["failures"] or failed_replay else "complete"
    manifest["figures_generated"] = plots and (directory/"figure_provenance.json").is_file()
    atomic_json(directory/"manifest.json", manifest)
    write_report(directory, manifest)
    notify({"event": "complete", "directory": str(directory.resolve()), "status": manifest["status"],
            "conditions": len(manifest["runs"]), "failures": len(manifest["failures"])})
    return directory


def data_dictionary():
    units = {"time_s": "simulation s", "throttle_fraction": "0..1", "external_load_nm": "Nm",
        "rpm": "rev/min", "map_kpa": "kPa absolute", "throttle_air_g_s": "g/s", "cylinder_air_g_s": "g/s",
        "model_indicated_torque_nm": "model Nm", "model_friction_torque_nm": "model Nm", "net_torque_nm": "model Nm",
        "manifold_air_mass_g": "g", "pressure_rate_kpa_s": "kPa/s", "speed_rate_rpm_s": "RPM/s",
        "ecu_estimated_air_g_s": "g/s", "fuel_multiplier": "dimensionless", "fuel_command_g_s": "g/s",
        "fuel_delivered_g_s": "g/s", "fuel_rate_g_s2": "g/s^2", "afr": "g air/g fuel", "afr_target": "g air/g fuel",
        "lambda": "AFR/reference AFR", "assumed_mixture_efficiency": "dimensionless assumed multiplier"}
    return {"origin": "synthetic", "time_basis": "simulation time, not wall-clock timestamps",
        "run_id": "unique run UUID; condition/config association is in manifest.json", "telemetry_units": units,
        "metric_definitions": {"post_5s_afr_rmse": "AFR RMSE over [5 s,end]; final sample if shorter than 5 s",
            "final_window_mean_rpm": "Mean RPM over last simulated second including endpoints",
            "final_window_mean_afr": "Mean AFR over last simulated second including endpoints",
            "rpm_settling_time_s": "Time after final input change satisfying stored band with at least 1 s confirmation; null if not observed",
            "sampled_fuel_used_g": "Trapezoidal integration of reported model fuel mass flow",
            "sensitivity_ranges": "Min/max over tested deterministic cases; not confidence intervals"}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("nominal", "sensitivity"), default="sensitivity")
    parser.add_argument("--plan", type=Path)
    parser.add_argument("--output-dir", type=Path, default=ROOT/"results/research")
    parser.add_argument("--no-plots", action="store_true")
    parser.add_argument("--plot-deps", type=Path)
    parser.add_argument("--render-only", type=Path)
    parser.add_argument("--json-progress", action="store_true")
    args = parser.parse_args()
    def notify(event):
        if args.json_progress:
            print(json.dumps(event, ensure_ascii=False), flush=True)
    try:
        if args.render_only:
            from research_figures import render_figures
            directory = args.render_only.resolve()
            render_figures(directory, args.plot_deps)
            manifest = json.loads((directory/"manifest.json").read_text(encoding="utf-8"))
            manifest["figures_generated"] = True
            atomic_json(directory/"manifest.json", manifest)
            write_report(directory, manifest)
            print(f"Figures regenerated: {args.render_only.resolve()}")
            return
        plan = json.loads(args.plan.read_text(encoding="utf-8")) if args.plan else make_plan(args.mode)
        directory = run_study(plan, args.output_dir, not args.no_plots, args.plot_deps, notify)
        if not args.json_progress:
            print((directory/"report.md").read_text(encoding="utf-8"))
            print(f"Saved study: {directory.resolve()}")
    except (ValueError, OSError, ImportError) as error:
        notify({"event": "error", "message": str(error)})
        parser.exit(1, f"Study failed: {error}\n")


if __name__ == "__main__":
    main()
