"""Deterministic fuel-map verification bench, not a complete engine simulator."""

import argparse
import bisect
import csv
import hashlib
import json
import math
import shutil
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path


MODEL_VERSION = "0.1.0-fixed-operating-point"
PROJECT_ROOT = Path(__file__).resolve().parent


def positive_number(value, label):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be a number")
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"{label} must be finite and positive")


@dataclass(frozen=True)
class FuelMap:
    name: str
    rpm_axis: tuple
    map_kpa_axis: tuple
    values: tuple  # Rows: increasing MAP. Columns: increasing RPM.

    def __post_init__(self):
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("Map name must be a nonempty string")
        for label, axis in (("RPM", self.rpm_axis), ("MAP kPa", self.map_kpa_axis)):
            if len(axis) < 2:
                raise ValueError(f"{label} axis needs at least two points")
            for value in axis:
                positive_number(value, label)
            if any(a >= b for a, b in zip(axis, axis[1:])):
                raise ValueError(f"{label} axis must be strictly increasing")
        if len(self.values) != len(self.map_kpa_axis):
            raise ValueError("Map row count must match MAP axis")
        for row in self.values:
            if len(row) != len(self.rpm_axis):
                raise ValueError("Map column count must match RPM axis")
            for value in row:
                positive_number(value, "Fuel multiplier")
                if not 0.5 <= value <= 1.5:
                    raise ValueError("Fuel multiplier outside the bench range [0.5, 1.5]")

    @classmethod
    def from_dict(cls, data):
        if data.get("schema") != "fuel_multiplier_map_v1":
            raise ValueError("Unsupported fuel map schema")
        return cls(
            name=data["name"],
            rpm_axis=tuple(data["rpm_axis"]),
            map_kpa_axis=tuple(data["map_kpa_axis"]),
            values=tuple(tuple(row) for row in data["values"]),
        )

    def to_dict(self):
        return {"schema": "fuel_multiplier_map_v1", **asdict(self)}

    def lookup(self, rpm, map_kpa):
        """Bilinear interpolation on nonuniform axes; reject extrapolation."""
        def bracket(axis, value, label):
            positive_number(value, label)
            if value < axis[0] or value > axis[-1]:
                raise ValueError(f"{label} outside map domain")
            index = min(bisect.bisect_right(axis, value) - 1, len(axis) - 2)
            weight = (value - axis[index]) / (axis[index + 1] - axis[index])
            return index, weight

        column, x = bracket(self.rpm_axis, rpm, "RPM")
        row, y = bracket(self.map_kpa_axis, map_kpa, "MAP kPa")
        lower = self.values[row][column] * (1 - x) + self.values[row][column + 1] * x
        upper = self.values[row + 1][column] * (1 - x) + self.values[row + 1][column + 1] * x
        return lower * (1 - y) + upper * y


@dataclass(frozen=True)
class Protocol:
    rpm: float = 3000.0
    map_kpa: float = 60.0
    air_mass_flow_g_s: float = 20.0
    afr_target: float = 14.7
    fuel_time_constant_s: float = 0.2
    duration_s: float = 10.0
    map_change_time_s: float = 5.0
    sampling_rate_hz: float = 50.0
    steady_window_s: float = 1.0

    def __post_init__(self):
        for label, value in asdict(self).items():
            positive_number(value, label)
        if self.map_change_time_s >= self.duration_s:
            raise ValueError("Map change must occur before the experiment ends")
        if self.steady_window_s > self.duration_s - self.map_change_time_s:
            raise ValueError("Final measurement window must follow the map change")
        for label, seconds in (("Duration", self.duration_s), ("Map change", self.map_change_time_s)):
            count = seconds * self.sampling_rate_hz
            if not math.isclose(count, round(count), rel_tol=0, abs_tol=1e-9):
                raise ValueError(f"{label} must align with the sampling grid")


def simulate(fuel_map, protocol):
    """Start from the reference state and apply the selected map at t_change."""
    multiplier = fuel_map.lookup(protocol.rpm, protocol.map_kpa)
    reference_fuel = protocol.air_mass_flow_g_s / protocol.afr_target
    delivered_fuel = reference_fuel
    dt = 1.0 / protocol.sampling_rate_hz
    decay = math.exp(-dt / protocol.fuel_time_constant_s)
    interval_count = round(protocol.duration_s * protocol.sampling_rate_hz)
    change_index = round(protocol.map_change_time_s * protocol.sampling_rate_hz)
    samples = []
    for index in range(interval_count + 1):
        active_multiplier = 1.0 if index < change_index else multiplier
        command = reference_fuel * active_multiplier
        samples.append({
            "time_s": index / protocol.sampling_rate_hz,
            "rpm": protocol.rpm,
            "map_kpa": protocol.map_kpa,
            "air_mass_flow_g_s": protocol.air_mass_flow_g_s,
            "fuel_multiplier": active_multiplier,
            "fuel_command_g_s": command,
            "fuel_delivered_g_s": delivered_fuel,
            "afr": protocol.air_mass_flow_g_s / delivered_fuel,
            "afr_target": protocol.afr_target,
        })
        # Exact first-order solution over [t_k, t_k + dt), held command.
        delivered_fuel = command + (delivered_fuel - command) * decay
    return samples


def summarise(samples, fuel_map, protocol):
    post_change = [s for s in samples if s["time_s"] >= protocol.map_change_time_s]
    final_window = [s for s in samples if s["time_s"] >= protocol.duration_s - protocol.steady_window_s]
    mean_afr = sum(s["afr"] for s in final_window) / len(final_window)
    return {
        "sample_count": len(samples),
        "final_window_sample_count": len(final_window),
        "post_change_afr_rmse": math.sqrt(
            sum((s["afr"] - protocol.afr_target) ** 2 for s in post_change) / len(post_change)
        ),
        "final_window_mean_afr": mean_afr,
        "final_window_signed_afr_error": mean_afr - protocol.afr_target,
        "analytical_steady_state_afr": protocol.afr_target / fuel_map.lookup(protocol.rpm, protocol.map_kpa),
    }


def write_json(path, data):
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_experiment(output_root, baseline, candidate, protocol):
    # Validate both conditions and compute before creating any output files.
    conditions = [("baseline", baseline), ("candidate", candidate)]
    runs = [(label, fuel_map, simulate(fuel_map, protocol)) for label, fuel_map in conditions]
    experiment_id = str(uuid.uuid4())
    directory = Path(output_root) / experiment_id
    directory.mkdir(parents=True, exist_ok=False)
    write_json(directory / "protocol.json", asdict(protocol))
    shutil.copyfile(Path(__file__).resolve(), directory / "model_snapshot.py")
    manifest = {
        "experiment_id": experiment_id,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "model_version": MODEL_VERSION,
        "model_sha256": sha256(directory / "model_snapshot.py"),
        "protocol_sha256": sha256(directory / "protocol.json"),
        "scenario": "fixed_operating_point_fuel_map_step",
        "data_origin": "synthetic_simulation",
        "time_basis": "simulation_seconds_not_wall_clock",
        "random_seed": None,
        "runs": [],
    }
    summaries = {}
    for label, fuel_map, samples in runs:
        run_id = str(uuid.uuid4())
        map_file = directory / f"{label}_map.json"
        csv_file = directory / f"{label}.csv"
        write_json(map_file, fuel_map.to_dict())
        with csv_file.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=["run_id", *samples[0].keys()])
            writer.writeheader()
            writer.writerows({"run_id": run_id, **sample} for sample in samples)
        summaries[label] = summarise(samples, fuel_map, protocol)
        manifest["runs"].append({
            "run_id": run_id,
            "condition": label,
            "map_name": fuel_map.name,
            "map_file": map_file.name,
            "map_sha256": sha256(map_file),
            "data_file": csv_file.name,
            "data_sha256": sha256(csv_file),
        })
    write_json(directory / "summary.json", summaries)
    write_json(directory / "manifest.json", manifest)
    report = [
        "# First fuel map verification experiment", "",
        "All data are synthetic. This is software verification, not validation against an engine.", "",
        f"Model version: {MODEL_VERSION}",
        f"Operating point: {protocol.rpm:g} RPM, {protocol.map_kpa:g} kPa absolute, "
        f"{protocol.air_mass_flow_g_s:g} g/s prescribed air flow.",
        f"Protocol: {protocol.duration_s:g} s, {protocol.sampling_rate_hz:g} Hz; "
        f"map activation at {protocol.map_change_time_s:g} s.", "",
        "| Condition | Post change AFR RMSE | Final window mean AFR | Analytical steady AFR |",
        "| --- | ---: | ---: | ---: |",
    ]
    for label, metrics in summaries.items():
        report.append(f"| {label} | {metrics['post_change_afr_rmse']:.6f} | "
                      f"{metrics['final_window_mean_afr']:.6f} | {metrics['analytical_steady_state_afr']:.6f} |")
    report.extend([
        "", "The analytical result follows from AFR_target / fuel_multiplier. Agreement verifies the",
        "implementation of the chosen equations; it is not independent physical evidence or a tuning improvement.",
        "The baseline is deliberately matched to the reference AFR by construction.", "",
        "The fuel time constant is an illustrative assumption, not a measured injector or engine parameter.",
        "Sampling here is the reporting grid of an exact first-order update. Logging latency is not measured.", "",
        "Reproduce the numerical traces from this directory using:", "", "```text",
        "python model_snapshot.py --protocol protocol.json --baseline baseline_map.json "
        "--candidate candidate_map.json --output-dir reproduced", "```", "",
        "New run identifiers and creation times are expected; numerical telemetry must be identical.", "",
    ])
    (directory / "report.md").write_text("\n".join(report), encoding="utf-8")
    return directory


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, default=PROJECT_ROOT / "maps" / "baseline.json")
    parser.add_argument("--candidate", type=Path, default=PROJECT_ROOT / "maps" / "fuel_plus_10_percent.json")
    parser.add_argument("--protocol", type=Path, help="Saved protocol JSON; defaults to the documented first experiment")
    parser.add_argument("--output-dir", type=Path, default=Path("results") / "step_01")
    args = parser.parse_args()
    try:
        baseline = FuelMap.from_dict(json.loads(args.baseline.read_text(encoding="utf-8")))
        candidate = FuelMap.from_dict(json.loads(args.candidate.read_text(encoding="utf-8")))
        protocol = Protocol(**json.loads(args.protocol.read_text(encoding="utf-8"))) if args.protocol else Protocol()
        directory = run_experiment(args.output_dir, baseline, candidate, protocol)
    except (OSError, ValueError, KeyError, TypeError) as error:
        parser.error(str(error))
    print((directory / "report.md").read_text(encoding="utf-8"))
    print(f"Saved experiment: {directory.resolve()}")


if __name__ == "__main__":
    main()
