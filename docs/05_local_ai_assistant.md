# Local assistant and optional map proposals

The AI Assistant is an optional interface feature. The numerical engine,
experimental metrics and acceptance checks remain deterministic Python code.
The LLM generates explanations and hypotheses; it is not an engine controller
or independent validation of model physics.

## Operation

Open **AI Assistant**. The app connects to its project-local Ollama service or
starts its portable runtime when needed. Choose a model, a context and a mode,
write a question and select **Send**. No API key is required.

Replies default to **English**, including when a question is in Greek or
Greeklish. Select **Language → Greek** for an optional Greek response.
**Compute → Auto (GPU / CPU)** lets Ollama select available hardware;
**CPU only** disables GPU offloading for the next request. The selected model,
language and compute mode are remembered locally across launches.

The model menu includes installed choices and models available for download.
**Download selected** downloads only the chosen model. On a fresh installation,
**Install + download** first installs the shared portable runtime. Selecting
a model does not reset the engine, change a map or send a question; the selection
is used on the next Send. The managed runtime is configured for one loaded
model at a time. Changing models clears an unaccepted proposal preview.

- **Current dashboard + editor** captures the current state, recent samples,
  model/fuel parameters, active map, editor map and available run metrics.
- **Loaded experiment study + editor** provides the loaded study's status,
  sample/condition counts, parameter cases, nominal results and deterministic
  sensitivity ranges. It excludes unrelated live-run telemetry.
- **Explain / discuss** allows an explanatory answer only.
- **Suggest map changes** additionally allows a complete fuel-map proposal,
  with a rationale, while retaining the editor's axes.

The context is a snapshot taken when Send is pressed. New samples can arrive
while a response is generated; the answer concerns its recorded snapshot.
The assistant does not browse the internet or execute tools. It cannot inspect
arbitrary files. Recent conversational history is bounded; older text is not
guaranteed to remain in context.

## Model profiles

| Profile | Model | Approximate model download | Request context | Recent messages |
| --- | --- | ---: | ---: | ---: |
| Tiny | Qwen3 0.6B Q4_K_M | 0.523 GB | 4096 tokens | None |
| Light | Qwen3.5 2B Q4_K_M | 1.9 GB | 6144 tokens | 2 |
| Balanced | Qwen3.5 4B Q4_K_M | 3.3 GB | 8192 tokens | 4 |
| Full | Qwen3.5 9B Q4_K_M | 6.6 GB | 8192 tokens | 4 |

Download size is not total RAM/VRAM usage. Context buffers and the runtime
require additional memory. Tiny and Light reduce context and output limits;
they receive compact app snapshots. Tiny omits study sensitivity ranges and
parameter cases, but retains condition/sample counts and nominal results.
The full captured snapshot and actual request are both available in chat exports.
Tiny treats each question separately; larger profiles retain bounded history.
Smaller models have weaker reasoning and may be less useful for map proposals.
These profiles offer a memory/quality choice, not a guarantee of laptop performance.

## Review and application

A proposal is independently checked for response shape, finite numeric values,
map dimensions and the existing multiplier range [0.5,1.5]. Displayed values
are quantised to the editor's three decimal places. The preview compares every
cell with its captured editor value and calculates the fuel-command percentage
change at fixed estimated air and AFR target.

**Load proposal in Fuel maps** is an explicit user action. It loads a candidate
into the editor for review. If the editor has changed since the request, loading
is rejected and a fresh proposal is needed. The running map and queued map are
preserved. The existing **Use on next run → Dashboard → Reset** workflow applies
the reviewed candidate to a later run.

Schema and range validation establish software compatibility, not engineering
correctness. A valid proposal may be unnecessary, poorly justified or worse
under the chosen metric. Evaluate any hypothesis using matched simulator runs.
Generated explanations may still contain numerical, terminology or reasoning
errors; compare them with the recorded snapshot and model specification.

## Runtime and installation

The default model is `qwen3.5:9b-q4_K_M` via Ollama `v0.40.10`. Its official
model listing reports about 6.6 GB. The portable Windows runtime download is
about 1.59 GB; extraction and cached downloads require additional disk space.
Both runtime and weights are stored under the ignored `.deps/ai/` directory.
The installer checks the pinned official runtime archive SHA-256 before
extraction; Ollama verifies downloaded model blobs.

On a fresh checkout, choose the desired profile before selecting **Install +
download** in the AI Assistant tab. Setup installs the portable runtime and only
the selected model, with progress shown inside the app. Installed models do not
need to be downloaded again. The runtime-only command is:

```powershell
python setup_local_ai.py
```

After installation, inference is local. The managed service binds only to
`127.0.0.1:11435`, uses the project's model directory and sets `OLLAMA_NO_CLOUD=1`.
It is started on demand. The app closes only a runtime process it owns; an
already-running service it connects to is not terminated. On Windows, the owned
server and its model-runner children are stopped when that app window closes.
If another Studio window was sharing it, that window can reconnect.

## Conversation evidence

**Save chat** exports completed turns as JSON, including the actual prompt,
bounded history, captured snapshot and hash, model metadata/digest, generation
options, raw response, timing and validated proposal. It also records whether
the user loaded that proposal in the editor. Chats are otherwise held in memory.
Each turn records its language, compute mode and context profile.
They are not silently sent to a cloud API or automatically published.

These records support inspection and later comparison. Generated text is not
guaranteed to be byte-identical across runtime, hardware or model changes.
The controlled experiments remain the source of quantitative results.

## Evaluation scope

Core automated checks cover explanation/proposal separation, geometry, bounds,
nonfinite values, quantisation, bounded history and local-runtime settings.
Interactive checks exercise real local inference, review before loading,
stale-editor rejection, export, cancellation and interface responsiveness.
This is integration evidence, not a benchmark of tuning quality or LLM accuracy.

The initial integration run passed 60 automated tests and exercised three real model
turns, including a 63-condition saved-study query. The default model was loaded
entirely in GPU memory with an 8192-token context. The
[verification record](../results/assistant/2026-10-24-integration-check/verification.json),
[actual conversation](../results/assistant/2026-10-24-integration-check/conversation.json)
and [runtime placement](../results/assistant/2026-10-24-integration-check/runtime_placement.json)
preserve the evidence and model digest. Generated text still needs review.

The later model-selection update passed 64 automated tests. A loopback protocol
test verified exact download targeting, missing-model Send gating, preferences
and per-model request settings. Real inference then exercised Tiny with
`num_gpu=0` and a 4096-token context, followed by Full with automatic placement.
The runtime reported zero VRAM use for Tiny, and both models answered Greek
questions in English. This was tested on the development PC, not an actual
low-end laptop. See the
[switching verification](../results/assistant/2026-10-24-model-switch-check/verification.json),
[actual conversation](../results/assistant/2026-10-24-model-switch-check/conversation.json)
and [Tiny placement](../results/assistant/2026-10-24-model-switch-check/tiny_placement.json).

## Primary references

- [Ollama Windows and portable runtime](https://docs.ollama.com/windows).
- [Chat API](https://docs.ollama.com/api/chat) and
  [structured outputs](https://docs.ollama.com/capabilities/structured-outputs).
- [Local-only mode and model storage](https://docs.ollama.com/faq).
- [Default Qwen3.5 9B quantisation](https://ollama.com/library/qwen3.5:9b-q4_K_M).
- [Tiny Qwen3 0.6B](https://ollama.com/library/qwen3:0.6b-q4_K_M),
  [Light Qwen3.5 2B](https://ollama.com/library/qwen3.5:2b-q4_K_M) and
  [Balanced Qwen3.5 4B](https://ollama.com/library/qwen3.5:4b-q4_K_M).
- [Qwen3.5 model family](https://ollama.com/library/qwen3.5).
