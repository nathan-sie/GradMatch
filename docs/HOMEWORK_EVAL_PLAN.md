# 50-task evaluation homework

Branch: `homework/eval-harness-50`  
Base: `main` at `6ae734828c160b6f1fee5d3088b1b52b5f0b3ba9`  
Assignment deadline shown in the supplied slides: November 17, 2026, 11:59 p.m.

Source reviewed: `Week 6 Evaluation _ Observability.pdf` (57 pages), especially pages 54-57. Page numbers in this plan are one-based PDF pages. Pages 55-56 define the submitted homework; pages 19, 22-23, 30-32, 35-36 and 46-51 explain evaluation and observability practices. The attached lecture is a requirements reference, not authorization to execute every exercise or perform paid evaluation.

The main branch preserves the current GradMatch project, including the deployed M3.5 recommendation pilot and browser-input fixes. Homework development is isolated on this branch. The existing public app continues to track main. No homework merge or deployment-branch change is part of this setup.

## Assignment scope

The numbered slide requirements specify 50 tasks, despite an inconsistent reference to 20 in the sidebar. Prepare 50 JSONL records with known answers or rubrics, including at least three edge cases and two unanswerable cases.

One script must execute both a genuine tool-using Agent and the non-agentic baseline on all tasks. Report accuracy, average turns, average and p95 latency, and average tokens side by side. Trace one actual evaluation failure. Run the Agent three times per task to report pass@3 (at least one success), pass^3 (all three succeed), and task IDs whose outcomes flip. The initial interpretation is three Agent runs total per task, matching the slide's three-trial metric definitions: 150 Agent task executions plus 50 baseline executions. A task execution can contain multiple model calls; grading calls are additional.

Required submission artifacts:

- `tasks.jsonl`, one distinct task per line.
- A reproducible evaluation script and usage instructions.
- A results table with the requested metrics and repeated-run statistics.
- A paragraph identifying one failure step and its cause, backed by its trace.

## Incremental checkpoints

| Checkpoint | Work | Verification |
| --- | --- | --- |
| H0: branch setup | Create and publish the isolated branch; preserve main's commit. | Working tree clean; local and remote main unchanged; homework branch available remotely. |
| H1: task set and experiment contract | Prepare 50 tasks, references/rubrics, coverage and fixed experiment settings. | Exactly 50 unique task IDs; at least 3 edge cases and 2 unanswerable cases; every task has a checkable reference or explicit rubric and source basis. |
| H2: Agent, baseline and traces | Implement the minimal tool-using Agent and a common execution record for both strategies. | Model-selected actions respond to observations; state is isolated; call/time limits stop execution; every model/tool call is traceable. |
| H3: graders | Implement exact, first-tool-call, rubric and unanswerable grading; calibrate judge decisions. | Known-good and known-bad answers are graded correctly; judge outputs are criterion-based; references never reach candidates. |
| H4: one-script harness and metrics | Execute task/strategy/repeat combinations, persist outcomes, resume and compute metrics. | A no-cost dry run lists 200 planned candidate executions; saved runs produce correct denominators, percentiles, pass@3, pass^3 and flip IDs. |
| H5: real pilot and formal runs | Validate a small development pilot, freeze versions, then run the complete comparison. | 50 baseline and 150 Agent executions have distinct IDs and saved actual usage/outcomes; pilot and formal results remain separate. |
| H6: failure analysis and submission | Explain an actual failed step and package the tasks, script, table and report. | The failure paragraph links to the trace; all reported values can be recomputed; the submission reproduces from documented commands. |

H0 is complete. H1-H6 are planned and are not implemented by this document. Each checkpoint should finish with its actual validation record before moving on. The paths and commands below are implementation targets, not commands that already exist.

## H1 - Task set and experiment contract

Deliverables: `homework/tasks.jsonl`, an evaluator-only reference/source record, a coverage table and frozen experiment settings. Preserve the slide's `id`, `type`, `question` and type-specific `expected`, `expected_call` or `rubric` fields. Additional GradMatch profile, conversation and scenario metadata must have explicit schema and visibility rules.

Use all four task types shown on page 56: `exact`, `tool`, `rubric` and `unanswerable`. Treat edge cases as tags, which can overlap any task type. Include realistic cost/eligibility questions, budget updates and memory, source use, missing evidence, and past failures. Suitable boundaries include an exact tuition upper bound, mismatched GPA scales, a test-validity cutoff and a deadline-day ambiguity. Unanswerable examples must actually be unsupported by the frozen evidence; the expected behavior is to identify the gap without inventing a number or admission probability.

Set one assessment date, model/version, catalog hash, tier rubric and per-strategy resource ceiling. Candidate model inputs receive the question, declared profile/history and accessible evidence only. They do not receive expected answers, expected calls, scoring rubrics or hidden reference facts. Draft and review the final set before examining its formal model results. Use a separate small development set for debugging and judge calibration.

Acceptance: a proposed `python -m scripts.homework.validate_tasks` validates the 50 records, IDs, task-specific fields, coverage minima and source bindings. Manually review whether the tasks are distinct and answerable as labelled. No model request is needed for schema/coverage validation.

## H2 - Minimal Agent, baseline and observability

Deliverables: a CLI-accessible Agent, a baseline adapter, shared tool contracts, and JSON traces. Reuse the current official snapshots, deterministic constraints, tuition calculations and output validator. The Agent must select its next tool or final response from the current observations rather than execute a predetermined tool sequence. Keep the baseline non-agentic.

Implement only the snapshot tool subset needed by the task set, such as catalog search, program/evidence inspection and condition checks. Both strategies have the same evidence access; a baseline operation is logged as the actual deterministic operation it is, not as a fabricated model-selected call. Clarification and multi-turn tasks must preserve unchanged applicant fields and isolate different tasks/repeats.

Following pages 19 and 47, record outcome, trajectory and individual decisions. Every candidate task execution gets a trace ID. Each model/tool span records its parent, name, start/end/duration, arguments, returned observation or structured failure, model version and actual token usage where applicable. Persist structured actions and observations, not hidden model reasoning. Never log API keys.

Acceptance: offline checks cover invalid arguments, missing evidence, repeated actions, call/time exhaustion, profile updates and session isolation. Then inspect a bounded real-model development trace showing that an observation changes the next action. The existing project baseline and regression checks must still work. This is a partial M4 checkpoint, not proof of complete live web/PDF retrieval.

## H3 - Graders and judge calibration

Deliverables: task-type graders, a structured judge contract, grading records and a calibration note.

| Type | Primary check from page 56 | Additional safeguards |
| --- | --- | --- |
| `exact` | The answer contains the expected answer. | For numeric/structured GradMatch facts, check the amount, unit, scope and cited basis; a matching number in an otherwise contradictory answer is insufficient. |
| `tool` | The first tool call's name and arguments match the reference. | Inspect the actual trace; a later correct call does not satisfy the first-call requirement. Do not invent a missing baseline call. |
| `rubric` | An LLM judge grades each criterion separately. | Return yes/no plus evidence for each criterion, using an isolated reference/evidence package. |
| `unanswerable` | The judge verifies appropriate inability to answer and no invented facts. | A vague refusal to a supported question is not a success. |

Every open answer must pass all four standard criteria: correct, grounded, complete and in policy, plus its task-specific items. Where a task changes state, inspect the resulting profile/state as well as the final message. The shared application validator is useful evidence but is not the sole independent grader.

Use code checks where possible and reference-based judging for open answers (pages 22-23). Blind the judge to the candidate strategy, use a fixed criterion-based prompt, and manually label a development sample to measure agreement. The lecture recommends roughly 50 human-labelled answers for calibration and preferably a different judge model family; these are guidance beyond the explicit submission checklist. Record the actual reviewed sample size and model-family limitations. Do not claim human agreement that was not measured. Keep judge requests, tokens and latency separate from candidate metrics.

Acceptance: fixed good/bad examples exercise every grader, including wrong units, unsupported citations, partial answers, a wrong first call, and fabricated facts on an unanswerable question. Check schema failures and judge errors explicitly. Freeze the grader after development calibration and before formal runs.

## H4 - Evaluation runner and metric aggregation

Deliverables: one evaluation entry point, persisted per-run results/traces, a summary command, CSV/Markdown tables and flip-task output.

A proposed command family is `python -m scripts.homework.evaluate --tasks homework/tasks.jsonl --agent-repeats 3`. It must support a no-model dry run, a small development pilot, explicit real-model execution, and resuming the same experiment without overwriting completed runs. Every run is identified by experiment, task, strategy and repeat. Failures and timeouts are saved as outcomes rather than silently dropped.

| Metric | Frozen counting rule |
| --- | --- |
| Accuracy | Passed tasks / all 50 scheduled tasks for the baseline and the predesignated first Agent repeat. Optional pooled Agent accuracy across 150 executions is separately labelled. Failures/timeouts remain in the denominator. |
| Average turns | Candidate model calls per task, as explicitly defined on page 30; include interpretation and decision/final-answer calls. User messages and tool calls are counted separately. |
| Average and p95 latency | Candidate task start to final result or terminal failure, including its tools/waits; exclude post-run grading. Predeclare the percentile method and report incomplete runs. |
| Average tokens | Sum candidate input and output tokens across every call in the task. Cached input is a subset of input, not an extra amount. Unknown provider usage remains flagged rather than silently becoming zero. |
| pass@3 | Number of tasks with at least one pass among the three Agent repeats / 50. |
| pass^3 | Number of tasks with three passes among the three Agent repeats / 50. |
| Flip list | Task IDs with mixed pass/fail outcomes across those repeats, including each outcome vector. |

Do not cube overall accuracy to obtain pass^3. Pages 31-32 demonstrate counting observed repeat combinations; with exactly three runs and k=3, the formulas above reduce to one all-three group per task. Never choose the best three attempts after seeing outcomes.

Acceptance: synthetic result records verify the mathematics, percentile convention, missing-run handling and resume behavior without paid requests. For example, outcome vectors `[pass, fail, pass]` and `[fail, fail, fail]` must produce pass@3 = 1/2, pass^3 = 0 and one flip ID. The dry-run manifest must enumerate exactly 50 baseline plus 150 Agent candidate executions. These fixtures are harness checks, not homework scores.

## H5 - Real development pilot and formal evaluation

Deliverables: pilot validation/usage, frozen experiment manifest, complete real run records, and generated summaries.

Run a small separate development set that exercises all task types, at least one edge case and a follow-up. Inspect actual model-selected tools, returned sources, profile state, grading, trace completeness and measured usage. Fix problems before freezing the formal experiment; retain development failures and their costs. Use measured pilot call counts and token usage to estimate the full run, including grader overhead.

The formal manifest schedules one baseline repeat and three total Agent repeats over the same 50 tasks. The first Agent repeat supplies the predesignated side-by-side accuracy/efficiency row; all three supply stability metrics. Interleave strategies/repeats to reduce time-of-day service effects. Keep the catalog, assessment date, model, prompts, tools and grader fixed within one formal experiment. A fix that changes those conditions starts a separately labelled experiment, rather than replacing selected failed results.

Acceptance: every scheduled execution is accounted for, including terminal failures. Reports recompute from the saved records, with actual candidate and grader usage separately visible. Pilot runs, unit tests and stubs do not enter formal task counts. No score is populated before execution.

## H6 - Failure analysis and submission package

Deliverables: `tasks.jsonl`, evaluation code/usage, results table with pass@3 and pass^3, flip-task list, and one paragraph on an actual failure, with its trace available for inspection.

Use a failed formal run to identify the task, expected behavior, first causally wrong step, the actual tool/action arguments or observation, and how that error led to the failed outcome. Distinguish model choice, tool failure, source/data gaps and grading mistakes. Do not submit only a statement that the final answer was wrong. If formal runs yield no failures, report that fact and clearly separate any diagnostic failure example from the formal scores.

Verify that an independent reader can reproduce the table and inspect the cited trace. Package the requested files with the required filenames and a concise English report. Preserve raw results and development failures; omit credentials, private applicant data and the full lecture PDF. Review a potential fix separately and add it as a regression task as described on pages 51 and 54; do not silently change a frozen experiment's answers or scores.

## Separate next-week preparation

Page 57 asks students to read OWASP Top 10 for LLM Applications (2025), bring the harness and an initial list of 50 safety prompts, and consider the worst actions their tools could perform. Track this separately from the page 55-56 homework. The 50 safety prompts are not the same as the 50 main evaluation tasks, and page 57 does not require running a complete safety benchmark for this submission. The later project's safety evaluation remains separate.

## Experimental boundaries

- Start with the current ten-program official snapshot catalog and the same assessment date, model, rubric and evidence access for both strategies. Record hashes and configuration versions in each run.
- Keep the versioned project catalog and public app usable. Homework-specific scenario overlays and runtime results must not mutate the shared public SQLite catalog.
- The minimal Agent can select catalog lookup, program/evidence inspection, constraint checks and clarification actions based on observations, within explicit call/time limits. Live web/PDF retrieval and the full M4 recovery workflow remain later project work.
- Use the command-line task interface first. A new website, M5 plan-and-replan, a 40–60-program catalog and the final 210-task/50-safety evaluation are outside this homework checkpoint.
- Cover normal questions, cost/eligibility boundaries, follow-up updates, tool choice, citations and evidence gaps. Do not make most tasks variants of the same template or unanswerable merely because the catalog is small.
- Apply the four standard answer criteria: correct, grounded, complete and in policy, together with task-specific requirements. Correctly identifying missing evidence can pass an explicitly unanswerable task.
- Define turns and latency/token aggregation before collecting results. Store model/tool counts separately; include failures in denominators and keep grader usage separate from candidate usage.
- Reference answers are evaluation-only. They must not enter Agent/baseline prompts, tool responses or scenario instructions. A validator shared by both systems does not alone establish an independent grade.
- Keep actual model evaluation distinct from regression tests and stubbed harness checks. Report both successful and failed development attempts and estimate formal-run cost from measured pilot usage.

## Status

H0 is complete, and the six-part plan has been checked against the full 57-page lecture. H1-H6 remain unstarted. No homework model requests or formal evaluation were executed while planning. No benchmark scores are claimed. The existing M3.5 acceptance records remain historical project evidence.
