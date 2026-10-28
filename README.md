# Virtual ECU Tuning and Telemetry Platform

A dissertation project focused on developing and experimentally evaluating a
virtual ECU, fuel-map editing and telemetry environment.

The project currently includes four documented stages and a desktop application:

- Stage 01: fuel-map test bench at a fixed operating point.
- Stage 02: dynamic engine speed and manifold pressure driven by throttle and external load.
- Stage 03: fuel map → fuel flow → AFR → torque and engine-speed response.
- Stage 04: controlled comparisons, sensitivity analysis and figure export.
- Desktop: live dashboard, manual controls, fuel-map editor, run history and experiments.

All data is synthetic. Engine parameters have not been calibrated against
measurements from a real engine.

## Opening the application

On Windows, install the dependencies described below, then double-click
**Launch Studio.cmd**. This opens a separate desktop window.
A packaged `.exe` installer is not yet available.

Use **Theme** in the top-right corner to choose **New Gen** (the original dark
appearance), **Retro** (charcoal and amber colours, monospace text and classic
controls) or **Simple** (a clean, light appearance). Changes apply immediately
across all tabs and live plots, including during a simulation. The selected
theme is saved locally for the next launch.

1. In **Dashboard**, select **Throttle step** and press **Start simulation**.
   The throttle changes at five simulated seconds, followed by changes in pressure and RPM.
2. In **Manual bench**, use the throttle and load sliders.
   On the Dashboard, **↑ / ↓** also adjust throttle by **1%**, and **→ / ←**
   adjust load by **1 Nm**. Holding an arrow key repeats the adjustment.
   Mouse dragging remains available. When the scenario menu or another tab has
   focus, arrow keys retain their normal function. **Pause** stops simulated
   time, and **Reset** starts a new trial.
3. Press **Save run** to save CSV data, configuration and source-code snapshots.
4. In **Fuel maps**, select a preset or edit the table, then press
   **Use on next run**. Next, select **Dashboard → Reset → Start simulation**.
   The map affects AFR and the engine-speed response. The active map stays
   fixed throughout a trial; subsequent changes are queued for the next Reset.
   **Run fixed-point check** runs the Stage 01 verification experiment separately.
5. In **Run history**, open the report for a saved trial.
6. In **Experiments**, select the 63-condition study or the smaller 9-condition
   pilot, then press **Run study**. The study runs in a separate process while
   the GUI remains available. Select the three figures from the menu, use
   **Open report** to inspect metrics, and **Open results / PNG / PDF** to access
   the files. **Load saved study** reopens an earlier study. **Cancel** preserves
   completed data and marks the study as cancelled.
7. In **AI Assistant**, select a data context and enter a question.
   **Explain / discuss** explains the data, while **Suggest map changes** can
   produce a proposal with a comparison of map values. Use
   **Load proposal in Fuel maps** to review the proposal in the editor, then
   follow **Use on next run → Reset** to apply it to a new trial.
   **Stop** cancels a response, and **Save chat** exports the conversation
   together with data snapshots and model information.

The assistant uses local **Qwen models through Ollama**, without an API key.
The **Model** menu offers **Tiny 0.6B (~523 MB), Light 2B (~1.9 GB), Balanced 4B
(~3.3 GB) and Full 9B (~6.6 GB)**. **Download selected** downloads only the
selected model. On a new PC, **Install + download** also installs the shared
runtime (~1.59 GB download, with additional space required for extraction).

Replies default to **English**, including responses to questions in Greek.
Greek is optional through **Language**. **Compute → CPU only** enables inference
without a GPU, while **Auto** selects the available hardware. These preferences
are saved for the next launch. Tiny uses a smaller context and does not retain
previous questions; response speed depends on the PC.

After downloading the required files, conversations run locally. Suggested
changes are hypotheses to evaluate in the simulator and require assessment.
See the [assistant documentation](docs/05_local_ai_assistant.md).

Extreme manual inputs may take the simulation outside the model's supported
range. In that case, the run stops with a message and requires Reset.

The GUI uses Qt/PySide6. Dependencies are installed locally in `.deps/desktop`
and are excluded from Git. To set up a new environment with Python 3.10 or later:

```powershell
python -m pip install --target .deps/desktop -r requirements-desktop.txt
python studio_app.py
```

On Windows, `py -3` can be used instead of `python` if Python is not on PATH.
Use the same interpreter when installing dependencies and running the app.
Choose Python 3.11 or later if you also need the research figures described below.

The Windows launcher first uses `STUDIO_PYTHON` if set, then a project-local
`.venv`, an optional interpreter path in `.local/python-path.txt`, or Python
available through `py -3` or PATH. Local configuration is excluded from Git.

## Getting started

1. Read the [model and experiment specification](docs/01_model_and_experiment.md).
2. Inspect the [baseline map](maps/baseline.json) and its [modified version](maps/fuel_plus_10_percent.json).
3. Run the first experiment and read the generated `report.md`.
4. Read about the [manifold-pressure and engine-speed model](docs/02_engine_dynamics.md).
5. Read about [fuel-map coupling](docs/03_fuel_coupling.md).
6. Read the [sensitivity protocol](docs/04_sensitivity_protocol.md) and
   [pilot-study interpretation](docs/04_pilot_findings.md). The
   [mapping to the dissertation document's objectives](docs/project_progress.md)
   identifies the remaining work.

## Running the project

The simulation core uses only the Python 3.10+ standard library.
No external packages are required to run the numerical experiments below.

From the project directory, with Python available:

```powershell
python ecu_bench.py
python run_dynamics.py
python run_fuel_dynamics.py
python -m unittest discover -s tests -v
```

The first experiment creates a new directory under `results/step_01/` containing:

- `baseline.csv` and `candidate.csv`: telemetry with a run identifier.
- `summary.json` and `report.md`: metrics and interpretation.
- `manifest.json`: data provenance, identifiers and SHA-256 hashes.
- Copies of the maps, protocol and source code for reproduction.

The report includes the command needed to reproduce the experiment from the
archived copies.

`run_fuel_dynamics.py` saves the nine combinations of three scenarios and three
fuel maps under `results/step_03/`. The desktop application saves dynamic trials
under `results/desktop/`, with corresponding data and snapshots.

## What the first experiment demonstrates

With air flow held constant, a 10% increase in fuel changes AFR from 14.7 to
13.363636. This is the expected result of the test-bench equations.
It does not establish a power increase or an improvement in a real engine.

## Controlled study and research figures

Figure generation requires Python **3.11+** and separate dependencies:

```powershell
python -m pip install --target .deps/research -r requirements-research-lock.txt
python research_study.py
```

The full study comprises 7 parameter cases × 3 scenarios × 3 maps = 63 conditions,
plus two additional reference repetitions. All cases use the same initial
states and inputs for each scenario. `--mode nominal` runs only the nine
nominal combinations. `--no-plots` runs the numerical study without external
dependencies.

Each `results/research/<UUID>/` directory contains the study plan saved before
execution, data/configuration/map files for each condition, source code, hashes,
`metrics.csv`, `paired_effects.csv`, `sensitivity_ranges.json`,
`data_dictionary.json`, a report and three figures in PNG/PDF format.
The report includes commands for reproduction from the archived copies.
Use `--render-only <directory>` to regenerate figures from saved data after
verifying their hashes.

The reported ranges are the minimum and maximum values across the tested cases,
rather than statistical confidence intervals. Repeating identical data checks
software reproducibility; it does not provide independent physical validation.

To check the desktop application after installing its dependencies:

```powershell
python studio_app.py --smoke-test
python studio_app.py --research-smoke-test
```

## Next steps

Document and implement ignition effects, supported by a critical literature
review. The mixture-loss relationship remains an explicit modelling assumption.
Physical validation and a separate real-time experiment covering jitter,
dropped samples and logging overhead remain outstanding.
