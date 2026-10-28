# Progress against the proposed dissertation specification

Source: the supplied Individual Project and Dissertation proposed specification.
Its status is proposed academic discussion, subject to supervisor approval.
The official assessment brief still needs to be checked separately.

## Objectives

| Objective | Current evidence | Remaining work |
| --- | --- | --- |
| O1 Literature | Engineering references in model specifications | Critical scholarly literature review and justified model selection |
| O2 Explicit model | Three documented stages, equations, state variables and unit tests | External validation or clearly bounded internal-validity argument |
| O3 Fuel and ignition maps | Interpolated fuel maps, three presets and three scenarios | Ignition map and justified ignition-to-output model |
| O4 Capture and visualise | CSV archives, hashes, source/config snapshots, data dictionary, saved-study loading, PNG/PDF overlays and figure provenance | Final usability and delivery review |
| O5 Controlled experiments | Predefined 63-condition fuel/sensitivity pilot, paired differences and two repeat checks | Supervisor review of the method, ignition experiments and final interpretation |
| O6 Critical evaluation | Explicit assumptions, deterministic sensitivity ranges and conditional map-ranking evidence | Broader robustness, justified parameter bounds and final dissertation discussion |

The specification permits SQLite or structured files. Existing JSON/CSV archives
are therefore a valid storage route; a SQL database is not assumed mandatory.

## Experimental programme

| Study | Evidence so far | Next evidence |
| --- | --- | --- |
| E1 Model checks | Idle, throttle step and load step; consistency tests, response measures and domain checks in the pilot | Stronger independent validation or bounded internal-validity discussion |
| E2 Tuning maps | Three fuel maps under matched operating histories, paired differences and overlays | Ignition comparison and research interpretation |
| E3 Robustness | Exact replay, Step 04 deterministic one-at-a-time sensitivity and min/max ranges | Parameter justification, interactions if needed and critical evaluation |
| E4 Telemetry | Reporting-grid invariance verification | Separate measurements of wall-clock jitter, loss and logging overhead |

## Mandatory scope still open

Ignition modelling; the critical literature chapter; an approved evaluation
protocol; experimental interpretation; a dissertation draft; and final packaging
with installation, test evidence, representative datasets and demonstration.
Full CAN/OBD compliance, hardware and remote remapping are optional future work.
An optional local LLM assistant now explains snapshots and produces reviewable
fuel-map hypotheses. This does not complete an evaluation of AI tuning quality
or replace the core experiments and outstanding academic work.
Virtual diagnostics can be added after the experimental core is secured.

This is a living progress record. Working prototype features do not imply that
an academic objective or delivery gate has been approved or fully achieved.
