"""Standalone Matplotlib figures generated from archived telemetry and metrics."""

import json
import os
import sys
from pathlib import Path

from ecu_bench import sha256, write_json

ROOT = Path(__file__).resolve().parent
COLORS = {"baseline": "#2366a5", "plus10": "#d3781c", "minus10": "#21865b"}
LABELS = {"baseline": "Baseline", "plus10": "+10% fuel", "minus10": "-10% fuel"}


def plotting_environment(dependencies=None):
    dependencies = Path(dependencies) if dependencies else ROOT/".deps/research"
    if dependencies.is_dir() and str(dependencies) not in sys.path:
        sys.path.insert(0, str(dependencies))
    os.environ.setdefault("MPLCONFIGDIR", str(ROOT/"tmp/matplotlib"))
    import matplotlib
    matplotlib.use("Agg", force=True)
    import numpy
    return {"matplotlib": matplotlib.__version__, "numpy": numpy.__version__, "backend": "Agg"}


def render_figures(directory, dependencies=None):
    environment = plotting_environment(dependencies)
    import matplotlib.pyplot as plt
    from research_study import read_samples, sensitivity_ranges
    directory = Path(directory)
    manifest = json.loads((directory/"manifest.json").read_text(encoding="utf-8"))
    plan = json.loads((directory/"study_plan.json").read_text(encoding="utf-8"))
    afr_target = plan["base_config"]["fuel_parameters"]["afr_target"]
    records = manifest["runs"]
    if not records:
        raise ValueError("No completed conditions to plot")
    figures = directory/"figures"
    figures.mkdir(exist_ok=True)
    scenario_names = list(dict.fromkeys(r["operating_scenario"] for r in records))
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 9, "axes.spines.top": False,
                         "axes.spines.right": False, "axes.grid": True, "grid.alpha": 0.18})
    provenance = {"data_origin": "synthetic", "dependencies": environment, "figures": []}
    def save(fig, name, conditions, caption):
        for extension in ("png", "pdf"):
            fig.savefig(figures/f"{name}.{extension}", dpi=170, bbox_inches="tight", facecolor="white")
        plt.close(fig)
        provenance["figures"].append({"name": name, "condition_ids": conditions, "caption": caption,
            "png_sha256": sha256(figures/f"{name}.png"), "pdf_sha256": sha256(figures/f"{name}.pdf")})
    fig, axes = plt.subplots(len(scenario_names), 2, figsize=(11, 2.65*len(scenario_names)), squeeze=False,
                             layout="constrained")
    nominal = [r for r in records if r["case"] == "nominal"]
    for index, scenario in enumerate(scenario_names):
        for record in nominal:
            if record["operating_scenario"] != scenario:
                continue
            samples = read_samples(directory/record["data_file"])
            for column, key in enumerate(("afr", "rpm")):
                axes[index,column].plot([s["time_s"] for s in samples], [s[key] for s in samples],
                    color=COLORS.get(record["map"]), label=LABELS.get(record["map"],record["map"]), linewidth=1.5)
        for column, unit in enumerate(("AFR (g air / g fuel)", "Engine speed (RPM)")):
            axes[index,column].set(xlabel="Simulation time (s)", ylabel=unit, title=scenario.replace("_"," "))
            axes[index,column].legend(fontsize=8)
        axes[index,0].axhline(afr_target, linestyle="--", linewidth=0.8, color="#777777")
    fig.suptitle("Nominal fuel-map comparisons — synthetic model data", fontsize=13)
    save(fig, "nominal_traces", [r["condition_id"] for r in nominal], f"Matched nominal conditions; dashed AFR line is the stored target of {afr_target:g}.")
    ranges = sensitivity_ranges(records)
    fig, axes = plt.subplots(1, len(scenario_names), figsize=(11, 4), squeeze=False, layout="constrained")
    for index, scenario in enumerate(scenario_names):
        axis = axes[0,index]
        rows = [r for r in ranges if r["operating_scenario"] == scenario]
        for position, row in enumerate(rows):
            low, high = row["final_window_mean_rpm_min"], row["final_window_mean_rpm_max"]
            axis.plot([position,position], [low,high], color=COLORS.get(row["map"]), linewidth=4, solid_capstyle="round")
            reference = next((r for r in nominal if r["operating_scenario"] == scenario and r["map"] == row["map"]),None)
            if reference:
                axis.scatter(position, reference["metrics"]["final_window_mean_rpm"], color="black", s=25, zorder=3)
        axis.set_xticks(range(len(rows)), [LABELS.get(r["map"],r["map"]) for r in rows], rotation=20)
        axis.set(title=scenario.replace("_"," "), ylabel="Final-window mean speed (RPM)")
    fig.suptitle("Tested sensitivity ranges; black dots show nominal values\nDeterministic min/max across completed cases — not confidence intervals", fontsize=11)
    save(fig, "sensitivity_ranges", [r["condition_id"] for r in records], "Tested parameter ranges only; no probability or confidence interpretation.")
    estimates = [r for r in records if r["case"] in ("nominal", "ecu_air_underestimate", "ecu_air_overestimate")]
    fig, axes = plt.subplots(1, len(scenario_names), figsize=(11, 4), squeeze=False, layout="constrained")
    for index, scenario in enumerate(scenario_names):
        axis = axes[0,index]
        for fuel_map in dict.fromkeys(r["map"] for r in records):
            group = sorted((r for r in estimates if r["operating_scenario"] == scenario and r["map"] == fuel_map),
                           key=lambda r:r["fuel_parameters"]["ecu_volumetric_efficiency"])
            axis.plot([r["fuel_parameters"]["ecu_volumetric_efficiency"] for r in group],
                      [r["metrics"]["post_5s_afr_rmse"] for r in group], marker="o", color=COLORS.get(fuel_map), label=LABELS.get(fuel_map,fuel_map))
        axis.set(title=scenario.replace("_"," "), xlabel="ECU volumetric-efficiency estimate", ylabel="AFR RMSE after 5 s")
        axis.legend(fontsize=8)
    fig.suptitle("AFR target error versus ECU estimate — synthetic data", fontsize=12)
    save(fig, "ecu_estimate_sweep", [r["condition_id"] for r in estimates], "Plant efficiency remains fixed; ECU estimate changes. A nominal-only pilot has one estimate.")
    write_json(directory/"figure_provenance.json", provenance)
    return provenance
