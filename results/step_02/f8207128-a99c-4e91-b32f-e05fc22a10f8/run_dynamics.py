"""Run, archive and reproduce the second-stage engine dynamics experiments."""

import argparse
import csv
import json
import platform
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path

from ecu_bench import sha256, write_json
from engine_dynamics import MODEL_VERSION, Inputs, Parameters, default_config, equilibrium, simulate_scenario

ROOT = Path(__file__).resolve().parent


def metrics(samples, scenario, parameters):
    last_event = scenario["events"][-1]
    try:
        target = equilibrium(Inputs(last_event["throttle"], last_event["load_nm"]), parameters)
    except ValueError:
        # A valid short recording can head towards a stall outside our domain.
        # Preserve the recording even when no supported equilibrium exists.
        target = None
    final = [s for s in samples if s["time_s"] >= max(0, samples[-1]["time_s"] - 1)]
    return {
        "sample_count": len(samples),
        "initial_rpm": samples[0]["rpm"],
        "final_window_mean_rpm": sum(s["rpm"] for s in final) / len(final),
        "initial_map_kpa": samples[0]["map_kpa"],
        "final_window_mean_map_kpa": sum(s["map_kpa"] for s in final) / len(final),
        "minimum_rpm": min(s["rpm"] for s in samples),
        "maximum_rpm": max(s["rpm"] for s in samples),
        "analytical_equilibrium_rpm": target.rpm if target else None,
        "analytical_equilibrium_map_kpa": target.pressure_pa/1000 if target else None,
        "last_sample_equilibrium_error_rpm": samples[-1]["rpm"] - target.rpm if target else None,
    }


def export_suite(output_root, config, datasets, origin="batch"):
    if len(config["scenarios"]) != len(datasets) or not datasets or any(not s for s in datasets):
        raise ValueError("Each scenario must have a nonempty dataset")
    parameters = Parameters(**config["parameters"])
    summaries = [metrics(samples, scenario, parameters) for scenario, samples in zip(config["scenarios"], datasets)]
    experiment_id = str(uuid.uuid4())
    directory = Path(output_root) / experiment_id
    directory.mkdir(parents=True, exist_ok=False)
    write_json(directory / "config.json", config)
    source_hashes = {}
    for filename in ("engine_dynamics.py", "run_dynamics.py", "ecu_bench.py"):
        shutil.copyfile(ROOT / filename, directory / filename)
        source_hashes[filename] = sha256(directory / filename)
    manifest = {
        "experiment_id": experiment_id, "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "model_version": MODEL_VERSION, "python_version": platform.python_version(),
        "data_origin": "synthetic_simulation", "interface_origin": origin,
        "time_basis": "simulation_seconds_not_measured_wall_clock", "random_seed": None,
        "source_sha256": source_hashes, "config_sha256": sha256(directory / "config.json"), "runs": [],
    }
    lines = ["# Air path and speed experiment", "",
             "Synthetic data from an uncalibrated model. Verification only; no real-engine performance claim.", "",
             "Fuel mixture and indicated efficiency are assumed constant. Fuel and ignition maps are not coupled to torque yet.", "",
             f"Model: {MODEL_VERSION}. Internal integration step: {config['integration_step_s']} s. "
             f"Reporting: {config['sampling_rate_hz']:g} Hz.", "",
             "| Scenario | Initial RPM | Final window mean RPM | Analytical final equilibrium RPM |",
             "| --- | ---: | ---: | ---: |"]
    for index, (scenario, samples, summary) in enumerate(zip(config["scenarios"], datasets, summaries), 1):
        run_id = str(uuid.uuid4())
        data_path = directory / f"scenario_{index:02d}.csv"
        with data_path.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=["run_id", *samples[0]])
            writer.writeheader()
            writer.writerows({"run_id": run_id, **sample} for sample in samples)
        manifest["runs"].append({"run_id": run_id, "scenario": scenario["name"],
                                 "data_file": data_path.name, "data_sha256": sha256(data_path)})
        target_text = (f"{summary['analytical_equilibrium_rpm']:.2f}"
                       if summary['analytical_equilibrium_rpm'] is not None else "Outside model domain")
        lines.append(f"| {scenario['name']} | {summary['initial_rpm']:.2f} | "
                     f"{summary['final_window_mean_rpm']:.2f} | {target_text} |")
    lines.extend(["", "The analytical equilibrium is a reference from the same model, not independent engine evidence.",
                  "The final measurement window is the last simulated second, including endpoints.",
                  "For a short recording it may include a transient; the analytical equilibrium need not be reached.", "",
                  "Reproduce from this directory:", "", "```text",
                  "python run_dynamics.py --config config.json --output-dir reproduced", "```", "",
                  "Numerical traces should match under the recorded Python runtime. IDs and creation times will differ.", ""])
    write_json(directory / "summary.json", summaries)
    write_json(directory / "manifest.json", manifest)
    (directory / "report.md").write_text("\n".join(lines), encoding="utf-8")
    return directory


def run_suite(config, output_root):
    if config.get("schema") != "air_path_speed_suite_v1":
        raise ValueError("Unsupported scenario suite schema")
    if not config["scenarios"]:
        raise ValueError("At least one scenario is required")
    parameters = Parameters(**config["parameters"])
    datasets = [simulate_scenario(s, parameters, config["integration_step_s"], config["sampling_rate_hz"])
                for s in config["scenarios"]]
    return export_suite(output_root, config, datasets)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--output-dir", type=Path, default=Path("results") / "step_02")
    args = parser.parse_args()
    try:
        config = json.loads(args.config.read_text(encoding="utf-8")) if args.config else default_config()
        directory = run_suite(config, args.output_dir)
    except (OSError, ValueError, KeyError, TypeError) as error:
        parser.error(str(error))
    print((directory / "report.md").read_text(encoding="utf-8"))
    print(f"Saved experiment: {directory.resolve()}")


if __name__ == "__main__":
    main()
