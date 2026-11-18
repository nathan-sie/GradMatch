# Homework evaluation: frozen data, candidates, graders and runner

H1 data freeze: 2026-11-16. Latest checkpoint: H6, 2026-11-17 (America/Los_Angeles). Branch: `homework/eval-harness-50`.

H1 provides frozen data; H2 the snapshot candidates; H3 independent [grading](H3_GRADING.md); and H4 the [runner/metrics](H4_HARNESS.md). H5 has completed the actual [50-task formal comparison](H5_REAL_RUN.md): baseline 78%, designated Agent repeat 1 at 94%, pass@3 98% and pass^3 76%. See the H5 guide for the small-corpus/judge limitations and complete actual records. Main and the deployed app retain their accepted checkpoint.

H6 provides the [English report](FINAL_REPORT.md), [actual failure analysis](FAILURE_ANALYSIS.md), [submission instructions](SUBMISSION_README.md) and [verification record](../docs/verification/H6.md). The standalone ZIP includes the report PDF, root `tasks.jsonl` and `eval.py`, results and all actual evidence. No Canvas upload is implied.

## Validate without model calls

From the repository root:

```powershell
.\.venv\Scripts\python.exe -m scripts.homework.validate_tasks
.\.venv\Scripts\python.exe -m pytest -q tests/test_homework_h1.py
```

The validator reads the versioned seed and snapshots, not a mutable SQLite database. It verifies artifact hashes, evidence bindings, exact-answer arithmetic, task coverage and candidate input projection. It does not open websites or invoke a model, even if the project's local API key is configured. Its report is `work/h1_verification.json`.

## Files and visibility

| File / interface | Purpose | Visible to candidates? |
| --- | --- | --- |
| `tasks.jsonl` | 50 formal task records, including the slide's grading fields. | The raw records are evaluator-only. |
| `references.jsonl` | Authored reference answers, source IDs, fact claims, check/state expectations and independent exact-answer bases. | No. |
| `dev_tasks.jsonl`, `dev_references.jsonl` | Eight development/calibration cases, never counted in formal results. | Only their projected user inputs during pilot runs. |
| `experiment.json` | Frozen date, model, data/rubric hashes, candidate budgets, metric conventions and artifact checksums. | H2 uses only relevant execution settings. |
| `tool_contracts.json` | Four frozen snapshot tool schemas and semantics, implemented in H2. | Yes. |
| `TASK_REVIEW.md` | Readable index of all formal questions and reference answers for review. | No. |
| `gradmatch.homework.dataset.load_candidate_inputs` | Builds `CandidateInput` objects by an explicit whitelist. | Yes. This is the required H2 input boundary. |

The raw tasks retain `expected`, `expected_call` or `rubric` to follow the submission format. Never serialize an `EvalTask` directly into a candidate prompt. Pass only its `CandidateInput`: question, fictional initial profile, prior user setup messages, explicitly requested program scope and assessment date; task ID is for run correlation. Tags, families, type and scoring references do not cross this boundary. H2 tools must not expose arbitrary local-file access to the evaluator files. This is runtime input isolation, not a claim that answers in a public repository are secret.

## Actual coverage

| Formal task type | Count |
| --- | ---: |
| Exact | 18 |
| Tool | 8 |
| Rubric | 20 |
| Unanswerable | 4 |
| Total | 50 |

Eleven tasks have the overlapping `edge_case` tag; they are part of the 50, not additional tasks. Three formal tasks exercise prior user setup plus a follow-up. The set covers all ten programs, 30 authored task-family labels, and 27 of the 30 verified source records. All 30 source snapshots are hash-validated when loading the shared catalog.

Topics include complete tuition and billing scope, summer tuition, campus/track identity, credits, audience-specific deadlines, cohort fields, GPA comparability, recommended versus required thresholds, English subscores/conditions/date exceptions, GRE presence/format, degree/prerequisites, conditional risk evidence, profile updates and missing evidence. Exact numeric answers and expected rule states were authored separately from the production checker; H1 does not call the production cost or eligibility functions to generate an answer key.

The development set has disjoint IDs, normalized questions and family labels. It intentionally shares the same accessible catalog facts; this does not establish statistical independence or an unseen domain. A frozen small course dataset should not be presented as broad real-world admission validation.

## Reference interpretation

- `official_binding` claims must match the declared program field and the cited source's field binding. `snapshot_state` claims describe a local coverage gap or classification; they do not assert a universal university policy.
- Source text assertions verify selected phrases in the authored snapshot summary/excerpt. They help substantiate facts not represented by a dedicated program field, such as the absence of a hard GRE score cutoff or a combined tuition/fee amount.
- `expected_checks` are authored per-dimension outcomes, not assertions that a partial catalog record is fully eligible.
- `required_program_ids` identifies programs that must occur in the requested answer/search/comparison. It does not automatically require a formal recommendation. `forbidden_formal_program_ids` explicitly prevents unsupported formal recommendations.
- Profile-change references specify only the requested root-field updates. With `preserve_other_profile_fields=true`, all other declared background must remain semantically unchanged; the application manages profile versions itself.
- Setup messages are actual earlier user turns to execute in a fresh session before the final question. They are not precomputed assistant answers. All setup calls count toward the same per-task budget and efficiency metrics. No task/repeat shares mutable session state.
- The deadline-day question is explicitly hypothetical; it does not change the experiment's fixed assessment date. The correct answer distinguishes a date from the missing current clock time.

Reference answers were curated and reconciled with the frozen snapshot fields and summaries. Automated validation proves structural consistency and selected arithmetic/provenance facts, not complete semantic truth or expert-human agreement. Peer/user spot checks and the H3 judge calibration remain distinct review activities. No LLM judge has been calibrated or run in H1.

## Frozen execution choices

The assessment date is 2026-11-16; data mode is snapshot. Candidate model: `gpt-5.4-mini-2026-03-17`; tier rubric: `conservative-v1.1`. Each strategy has the same homework-specific ceiling: eight model calls, twelve tool calls and 120 seconds per task (including setup/follow-up), a 45-second model-call timeout, at most 1,800 output tokens per call and no automatic model retries. These choices do not change the public application's configuration. Actual candidate/judge code and prompt revisions will be pinned after H2-H4 and before H5.

One baseline repeat and three total Agent repeats schedule 200 candidate task executions. Candidate turns count all candidate model calls; latency includes candidate tools/waits but excludes grading; tokens sum input and output without double-counting cached input. The p95 convention is nearest-rank. The designated first Agent repeat supplies the side-by-side accuracy/efficiency row; all three repeats supply pass@3, pass^3 and flip IDs. Missing token usage stays unknown; failures/timeouts stay in task denominators. See the exact formulas in `experiment.json` and the six-part plan.

H1-H6 are complete. Formal scores are distinct from offline fixtures and development/calibration samples. This homework snapshot comparison does not complete the full M4 live-tool or final-project safety/broader-task milestones.
