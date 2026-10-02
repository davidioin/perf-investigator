# SDS Performance Investigator

A local browser app for real, reproducible SDS benchmark comparisons. No frontend build, sample reports, or CI integration. Benchmarking stays local; an optional read-only Codex investigation sends relevant evidence and source context to the model using your existing Codex login.

## Start

From the development workspace:

```sh
python3 perf-investigator/demo.py
```

Requires Python 3.12+, macOS or Linux, Git, rustup, the candidate revision's installed Rust toolchain, a C compiler, and at least 4 GiB free disk. Cargo dependencies must be cached or accessible using your normal registry setup. Shared-library benchmark targets also compile their existing development dependencies, which can require Python packages, model build assets, and protoc even though this workload does not exercise ML. Nothing fabricates results when prerequisites fail.

`--no-browser` prints the URL without opening it. `--port 8765` chooses a fixed port. The server only binds to `127.0.0.1`; all frontend assets are local. Only one launcher per tool directory may run at once.

**Demo date filter:** August–September 2026 is enabled by default. Version choices and commit summaries are restricted to commit dates from August 1 through September 30. For connected revisions, the actual range is filtered. If shallow/disconnected history prevents ancestry verification, the UI explicitly labels a date-window fallback: locally available commits reachable from either selected revision, not a verified between-versions range. Turn off the demo filter to restore strict ancestry behavior. No repository history is fetched or modified.

Use the baseline and comparison dropdowns to choose local tags, branches, or commits. Filter the loaded versions or load older commits; the defaults are HEAD’s first parent and HEAD. For forward selections the commit list uses `baseline..comparison` (baseline excluded, comparison included). Reverse selections list `comparison..baseline` and label those commits as removed. Diverged selections require a visible common ancestor; disconnected or shallow-incomplete history blocks both the list and LLM generation instead of treating all reachable history as intervening changes. Identical selections contain no commits. It includes all commits in that range, including merged branches.

One-line LLM summaries generate automatically after selection, using your Codex login. Each is based on the commit message and up to 16,000 characters of diff context, with truncation disclosed to the model. Summaries are cached by canonical repository and immutable commit SHA under `runs/_commit_summaries/`. Large ranges are processed in batches of ten with a 15-minute job deadline; partial summaries survive failures and can be retried. These explanations do not claim measured performance impact. Summary work shares the single-job limit with benchmarks and agent investigations.

Select a **trusted** local `sds-shared-library` or `dd-sensitive-data-scanner` checkout. Git revisions must already exist locally. Check the resolved commits, then start. Cargo build scripts execute normal repository code; this tool is not a sandbox for untrusted repositories. Git snapshots and build outputs go into `runs/`, never into the selected checkout. Uncommitted changes are not included.

## What gets measured

Nine fixed synthetic workloads: small and large events, dense matches, text keywords, attribute-path keywords, included/excluded scope, redaction, and 64-rule scanning. The harness asserts exact rule indexes, paths, match spans, and output before any timing. Scanner construction is outside timing; input cloning is in Criterion's batched setup. Times cover scanning a prepared event and returning its output, not end-to-end telemetry processing.

The same harness is installed in both disposable snapshots. Each build uses its original Cargo.lock with `--locked`, default features disabled, and matching release settings. This does **not** measure the shipped rule catalog, language FFI overhead, ML inference, network validation, allocations, package size, or production traffic. Shared-library comparisons use its exported scanner API and pinned core dependency.

Each workload has 30 Criterion samples after 0.5 seconds warm-up and at least 1 second measurement, repeated in three alternating baseline/candidate pairs. A regression requires more than 5% slowdown **and** separated confidence intervals in every pair. Improvement uses the symmetric criterion. All pairs within ±5% yield “no detected change”; remaining outcomes are inconclusive. These are conservative diagnostic heuristics, not a calibrated statistical guarantee or release gate. Avoid other heavy work during measurement.

Identical SHA comparisons are explicitly labeled controls: differences are noise/environment effects, not evidence of a code regression. Never compare absolute timings from runs on different machines, toolchains, flags, or harnesses.

Optional Linux `perf` capture profiles the two largest reproducible regressions separately from timed runs. Unavailable permissions/tools leave the timings usable and record the limitation. Optimized builds may have limited symbol detail. macOS timing works without perf.

## Artifacts and investigation

Each run folder retains state, raw Criterion estimates, build output, run logs, source diff, original lockfiles, source snapshots, and separate build targets. Successful runs additionally contain:

- `results.json`: schema version 1, environment, immutable revisions, harness hash, all pairs, and verdicts.
- `report.md`: readable measurements and reproduction inputs.
- `investigate.md`: instructions for a coding agent to inspect the evidence and recommend a fix. No agent/model is called until you explicitly start an investigation.

The UI supports sortable results, repeat details, downloads, live logs, cancellation, and run history. Closing the tab does not cancel a run. Ctrl+C stops the server and active child process group. Interrupted states survive restarts. Runs time out after 60 minutes. Retained build directories can consume several GiB each; remove a completed run directory manually when no longer needed.

## Run an agent investigation

Open a completed comparison and click **Run agent investigation**. Requires an installed `codex` CLI supporting `exec --ignore-user-config --output-schema` and an existing working login. Authentication and model-access failures are shown in the panel; the app does not log in for you. This uses Codex account capacity and sends relevant benchmark/source context to the model. The CLI chooses its default model; when the runtime does not report the model identifier, the UI says so.

The invocation ignores user configuration, disables hooks, MCP servers and web search, uses a read-only sandbox with approvals set to never, and instructs the agent to read only saved evidence/source. It does not apply fixes or execute benchmark experiments. The sandbox prevents source writes; read-only mode is not a filesystem privacy boundary. Use this only for trusted local SDS repositories.

The agent explains changed behavior, proposes evidence-backed hypotheses with counterevidence, and recommends experiments. Its analysis never changes benchmark verdicts. No regression and inconclusive results are valid outcomes; missing profiles are explicitly described. Evidence buttons show validated file excerpts from the saved run. Reports are downloadable and previous attempts remain selectable.

Attempts live under `runs/<run-id>/analysis/<attempt-id>/` with `prompt.md`, `schema.json`, `invocation.json`, raw CLI events, stderr, state, final response, and the validated Markdown report. Only public command/activity events appear in the UI; reasoning events are not displayed. Do not share raw event logs without review.

One benchmark or analysis may run at a time. Analysis has a 15-minute deadline, supports cancellation, and is marked interrupted after an application restart. Failed or interrupted attempts preserve their artifacts; **Run another investigation** creates a new attempt. The original copy-prompt handoff remains available.

## Tests

```sh
python3 -m unittest discover -s perf-investigator/tests -v
node --check perf-investigator/static/app.js
```

HTTP integration tests require permission to bind localhost. The test suite uses isolated temporary data; no seeded report is available in the demo UI.
