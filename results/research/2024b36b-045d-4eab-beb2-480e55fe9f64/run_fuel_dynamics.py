"""Controlled fuel-map comparisons and self-contained replay archives."""

import argparse
import csv
import json
import math
import platform
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path

from ecu_bench import FuelMap, sha256, write_json
from engine_dynamics import Inputs, Parameters
from fuel_dynamics import (MODEL_VERSION, FuelParameters, comparison_config,
                            simulate_scenario, uniform_equilibrium)

ROOT = Path(__file__).resolve().parent


def metrics(samples, scenario, parameters, fuel_parameters):
    final = [s for s in samples if s["time_s"] >= max(0, samples[-1]["time_s"]-1)]
    post = [s for s in samples if s["time_s"] >= min(5.0, samples[-1]["time_s"])]
    fuel_map = FuelMap.from_dict(scenario["fuel_map"])
    event = scenario["events"][-1]
    try:
        target = uniform_equilibrium(Inputs(event["throttle"], event["load_nm"]), parameters, fuel_parameters, fuel_map)
    except ValueError:
        target = None
    return {
        "sample_count": len(samples),
        "initial_rpm": samples[0]["rpm"],
        "final_window_mean_rpm": sum(s["rpm"] for s in final)/len(final),
        "final_window_mean_afr": sum(s["afr"] for s in final)/len(final),
        "post_5s_afr_rmse": math.sqrt(sum((s["afr"]-fuel_parameters.afr_target)**2 for s in post)/len(post)),
        "minimum_rpm": min(s["rpm"] for s in samples),
        "maximum_rpm": max(s["rpm"] for s in samples),
        "final_window_mean_model_torque_nm": sum(s["model_indicated_torque_nm"] for s in final)/len(final),
        "sampled_fuel_used_g": sum((a["fuel_delivered_g_s"]+b["fuel_delivered_g_s"])/2*(b["time_s"]-a["time_s"])
                                   for a, b in zip(samples, samples[1:])),
        "same_model_equilibrium_rpm": target.rpm if target else None,
    }


def export_suite(output_root, config, datasets, origin="batch"):
    if config.get("schema") != "fuel_coupled_suite_v1":
        raise ValueError("Unsupported fuel-coupled schema")
    if len(config["scenarios"]) != len(datasets) or not datasets or any(not s for s in datasets):
        raise ValueError("Each scenario must have a nonempty dataset")
    parameters = Parameters(**config["parameters"])
    fuel_parameters = FuelParameters(**config["fuel_parameters"])
    summaries = [metrics(samples, scenario, parameters, fuel_parameters)
                 for scenario, samples in zip(config["scenarios"], datasets)]
    experiment_id = str(uuid.uuid4())
    directory = Path(output_root) / experiment_id
    directory.mkdir(parents=True, exist_ok=False)
    write_json(directory / "config.json", config)
    source_hashes = {}
    for name in ("ecu_bench.py", "engine_dynamics.py", "fuel_dynamics.py", "run_fuel_dynamics.py"):
        shutil.copyfile(ROOT / name, directory / name)
        source_hashes[name] = sha256(directory / name)
    manifest = {
        "experiment_id": experiment_id, "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "model_version": MODEL_VERSION, "python_version": platform.python_version(),
        "data_origin": "synthetic_simulation", "interface_origin": origin,
        "time_basis": "simulation_seconds_not_measured_wall_clock", "random_seed": None,
        "source_sha256": source_hashes, "config_sha256": sha256(directory / "config.json"), "runs": [],
    }
    lines = ["# Fuel map and engine response comparison", "",
             "Synthetic data from an uncalibrated model with an assumed lambda-to-torque relationship.",
             "Results describe these equations and parameters; they do not establish real-engine tuning gains.", "",
             f"Model {MODEL_VERSION}. Integration {config['integration_step_s']:g} s; reporting {config['sampling_rate_hz']:g} Hz.", "",
             "| Scenario | Fuel map | Final mean AFR | Final mean RPM | AFR RMSE after 5 s |",
             "| --- | --- | ---: | ---: | ---: |"]
    for index, (scenario, samples, summary) in enumerate(zip(config["scenarios"], datasets, summaries), 1):
        run_id = str(uuid.uuid4())
        data_path = directory / f"scenario_{index:02d}.csv"
        map_path = directory / f"map_{index:02d}.json"
        write_json(map_path, scenario["fuel_map"])
        with data_path.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=["run_id", *samples[0]])
            writer.writeheader()
            writer.writerows({"run_id": run_id, **sample} for sample in samples)
        manifest["runs"].append({"run_id": run_id, "scenario": scenario["name"],
            "data_file": data_path.name, "data_sha256": sha256(data_path),
            "fuel_map_file": map_path.name, "fuel_map_sha256": sha256(map_path)})
        lines.append(f"| {scenario.get('operating_scenario', scenario['name'])} | {scenario['fuel_map']['name']} | "
                     f"{summary['final_window_mean_afr']:.4f} | {summary['final_window_mean_rpm']:.2f} | {summary['post_5s_afr_rmse']:.4f} |")
    lines.extend(["", "Final means use the last simulated second including endpoints. Short recordings can remain transient.",
                  "AFR RMSE uses [5 s, end]; for recordings shorter than 5 s it uses the final sample only.",
                  "Fuel used is trapezoidal integration of the reported mass flow, not measured vehicle consumption.", "",
                  "The baseline's air estimate matches the plant by construction. The lambda loss coefficient is assumed,",
                  "so differences in RPM are conditional on that choice and require sensitivity analysis and calibration.",
                  "Ignition is not modelled in this version.", "", "Reproduce from this directory:", "", "```text",
                  "python run_fuel_dynamics.py --config config.json --output-dir reproduced", "```", "",
                  "Numerical traces should match in the recorded runtime. UUIDs and creation times differ.", ""])
    write_json(directory / "summary.json", summaries)
    write_json(directory / "manifest.json", manifest)
    (directory / "report.md").write_text("\n".join(lines), encoding="utf-8")
    return directory


def run_suite(config, output_root):
    if config.get("schema") != "fuel_coupled_suite_v1":
        raise ValueError("Unsupported fuel-coupled schema")
    parameters = Parameters(**config["parameters"])
    fuel_parameters = FuelParameters(**config["fuel_parameters"])
    datasets = [simulate_scenario(s, parameters, fuel_parameters, config["integration_step_s"], config["sampling_rate_hz"])
                for s in config["scenarios"]]
    return export_suite(output_root, config, datasets)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--output-dir", type=Path, default=Path("results") / "step_03")
    args = parser.parse_args()
    try:
        if args.config:
            config = json.loads(args.config.read_text(encoding="utf-8"))
        else:
            fuel_maps = [FuelMap.from_dict(json.loads((ROOT / "maps" / name).read_text(encoding="utf-8")))
                         for name in ("dynamic_baseline.json", "dynamic_plus_10_percent.json", "dynamic_minus_10_percent.json")]
            config = comparison_config(fuel_maps)
        directory = run_suite(config, args.output_dir)
    except (OSError, ValueError, KeyError, TypeError) as error:
        parser.error(str(error))
    print((directory / "report.md").read_text(encoding="utf-8"))
    print(f"Saved experiment: {directory.resolve()}")


if __name__ == "__main__":
    main()
