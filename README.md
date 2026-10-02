# SDS Performance Investigator

Compare two SDS revisions on the same workloads, inspect measured performance changes, and ask a read-only Codex agent to explain the evidence and suggest follow-up experiments.

## Run

From the repository directory, run `python3 demo.py`.

Requires Python 3.12+, Git, and Rust.
For the AI features, for now it works only on Codex.
Future support for Bits AI hopefully to come.

## How it works

1. Select a local SDS checkout and baseline/comparison revisions.
2. You will see resolved commits and after a waiting period,  AI generated one-line summaries per commit.
3. The run button uses the same Criterion harness against disposable snapshots of both revisions. Process takes 5-10 min for now.
4. Explore timings, uncertainty, and repeat consistency. Click **Run agent investigation** for hypotheses, evidence links, and suggested experiments.

The local browser UI includes live logs, cancellation, downloadable reports, and saved run history. AI summaries and investigations send relevant source/evidence to the configured model using your Codex login. The investigation does not edit code or run experiments.

**Quick note abotu the demo scope:** only August–September 2026 commit filter by default.

## Synthetic tests

The fixed [Rust harness](harness.rs) calls the actual SDS scanner library, including its redaction engine. It checks expected matches and output before timing.

| Test | Synthetic event | What it checks |
| --- | --- | --- |
| Small, no match | `"x"` repeated 1,024 times | Scan 1 KiB without matches |
| Large, no match | `"x"` repeated 131,072 times | Scan 128 KiB without matches |
| Dense matches | `"secret "` repeated 128 times | Find 128 matches |
| Text keyword | `"password secret"` | Match `secret` near `password` |
| Field-name keyword | `{"password":"secret","other":"secret"}` | Match only in the `password` field |
| Included field | `{"secret":"secret","other":"secret"}` | Scan only the `secret` field |
| Excluded field | `{"secret":"secretA","other":"secretB"}` | Exclude `other` |
| Redaction | `"secret"` | Replace with `"[REDACTED]"` |
| Many rules | `"x"` repeated 16,384 times | Scan against 64 patterns: `marker000`–`marker063` |

Three alternating baseline/candidate pairs are measured. A reproducible regression requires over 5% slowdown with separated timing intervals in every pair; inconsistent results remain inconclusive.

These are local synthetic measurements, not production-impact estimates. They do not exercise the shipped rule catalog, ML, or remote validation. Agent explanations are very naive hypotheses and shouldn't be trusted for now.

## Development checks

```sh
python3 -m unittest discover -s tests -v
node --check static/app.js
```
