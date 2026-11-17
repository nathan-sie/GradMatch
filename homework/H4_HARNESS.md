# H4 evaluation runner and offline summaries

The runner connects the H2 candidate systems to H3 grading, preserving every scheduled execution and both usage streams. H4 acceptance uses offline fixtures only. Real development/formal execution remains H5.

## Prepare a no-cost formal schedule

From the repository root, choose a new directory:

```powershell
.\.venv\Scripts\python.exe -m scripts.homework.evaluate --tasks homework/tasks.jsonl --agent-repeats 3 --dry-run --experiment-dir work/evaluations/my-formal-plan
```

Planning is the default even without `--dry-run`. It makes zero candidate/judge requests, even with an enabled local key. It writes one immutable manifest containing exactly 50 baseline and 150 Agent entries. It does not generate benchmark scores or create fake completed runs.

Each task has one baseline and three predesignated Agent repeats. The fixed/Agent/repeat order rotates across tasks to interleave variants; repeat 1 always supplies the primary Agent row, regardless of execution order. Formal task subsets and other repeat counts are rejected.

For a small development plan, use `--tasks homework/dev_tasks.jsonl --task-ids d03`. Development subsets and formal experiments remain separate.

## Explicit execution and resume

To run an existing unchanged plan, explicitly add the paid execution flag:

```powershell
.\.venv\Scripts\python.exe -m scripts.homework.evaluate --resume --experiment-dir work/evaluations/my-formal-plan --live-model --max-runs 1
```

This runs candidates AND any required H3 judge requests. An enabled local API configuration is required. `--max-runs` stops between scheduled entries without changing the original schedule or denominators. Omit it only when intending to execute all remaining entries. H4 verification did not execute this live command.

Repeat the same resume command to continue. Completed failures, timeouts and judge errors are preserved, never selected for automatic retry. A saved candidate awaiting grading is graded without rerunning the candidate. A different code/data/configuration/dependency fingerprint requires a new labelled experiment.

Each run ID combines task, strategy and repeat within its experiment. Candidate calls receive only CandidateInput, never raw tasks/references. Live experiments reject injected test doubles; fixtures cannot use a formal split.

## Evidence and crash handling

An experiment contains:

- `experiment.json`: experiment ID, selected task IDs, schedule, frozen date/limits and fingerprint, with its own integrity digest. `initial_state` describes creation; current status is computed from saved records.
- `entries/<run-id>/candidate.started.json` and `grade.started.json`: durable markers written before attempting each stage.
- `candidate.json` and `grade.json`: immutable payloads, hashes and experiment/run links. The grade must refer to the exact saved candidate/trace.
- `interruption.json`: explicit uncertainty when an attempted stage lacks a committed result.
- `reports/<unique-id>/`: recomputable output; new reports never replace old evidence.

Writes use flushed temporary files followed by same-directory rename. A single writer lock prevents simultaneous resume operations. Started markers and result hashes are verified before more requests; corrupt/foreign records and reused candidate trace IDs are rejected.

If the process stops after a potentially billable request but before its result commits, resume records `interrupted_unknown`; it does not assume the request failed or retry it. Unknown usage/cost stays unknown. An interrupted judge retains its candidate and is not automatically reissued. The start marker intentionally errs toward preserving uncertainty even if interruption occurred immediately before sending a request.

Normal stops release the lock. For a stale lock after a hard process exit, use `--recover-lock` together with explicit live resume only after inspecting the directory. Recovery verifies the recorded process is dead on this same host; alive, foreign-host or unverifiable owners are rejected. It removes only that checked lock, never a result. On Windows the check queries process state without sending a signal.

## Recompute reports without a key

```powershell
.\.venv\Scripts\python.exe -m scripts.homework.summarize --experiment-dir work/evaluations/my-formal-plan
```

This reads saved records without credentials or requests. Optionally select a new `--output-dir`. Outputs: `summary.json`, `results.csv`, `results.md`, `repeat_vectors.json` and `flip_tasks.json`.

| Metric | Counting rule |
| --- | --- |
| Primary accuracy | Passed / all scheduled tasks for baseline and designated Agent repeat 1. Failed and timed-out executions remain in the denominator. |
| Incomplete accuracy | Final accuracy stays null. A separate provisional passed/scheduled fraction never shrinks the denominator; missing/errored outcomes are not passes. |
| Average turns | All candidate model calls, including setup and profile interpretation, over the scheduled row. |
| Latency | H2 candidate timer, including setup/tools/waits and failures; excludes preflight, saved-result I/O and grading. |
| p95 | Nearest rank: sorted latencies[ceil(0.95*n)-1]. Missing any scheduled latency makes the final value null. |
| Tokens | Candidate input + output across all calls; cached input is a subset, never added again. Unknown usage is not zero-filled; a genuine zero-call result has zero tokens. |
| pass@3 | Fraction of scheduled tasks with at least one pass among the three designated repeats. |
| pass^3 | Fraction with all three passes; not the cube of overall accuracy. |
| Flips | Complete three-run vectors containing both pass and fail. Incomplete vectors remain explicitly unresolved. |

Final efficiency means are available only when every scheduled value in that row is known. JSON also exposes known sample counts and clearly labelled observed means for diagnostics. Grade errors keep their original null pass state and remain unresolved; they are not dropped. Stability values are final only when every three-run vector is known.

Candidate and judge requests, token totals, cost estimates and judge latency are separate. Unknown cost/usage and interrupted attempts have explicit counters. Cost is estimated from recorded pricing, not an invoice. The optional pooled Agent row is separate from the primary repeat-1 comparison.

## Offline checkpoint verification

```powershell
.\.venv\Scripts\python.exe -m scripts.homework.verify_h4
.\.venv\Scripts\python.exe -m pytest -q
```

The verifier blocks network access and paid providers, checks a real 200-entry dry schedule, connects the H2 engine to H3's tool grader with scripted model decisions, exercises resume, and checks hand-authored repeat vectors. Every fixture is labelled `offline_test_double`; fixture tables are not model results.

Actual H4 verification and preserved examples are in [H4 verification](../docs/verification/H4.md). H5 still needs a real pilot, measured cost estimate, final experiment freeze and the complete formal comparison.
