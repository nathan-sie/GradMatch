# 50-task evaluation homework

Branch: `homework/eval-harness-50`  
Base: `main` at `6ae734828c160b6f1fee5d3088b1b52b5f0b3ba9`  
Assignment deadline shown in the supplied slides: November 17, 2026, 11:59 p.m.

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
| H1: minimal Agent | Add bounded model-selected tool actions and observations, using the existing catalog, constraints, evidence and final validator. Retain the fixed baseline. | Offline tool/state/stop checks and an actual model-selected tool trace. A fixed pipeline with a different name does not qualify. |
| H2: task set and harness | Author 50 varied tasks, isolated references, deterministic checks where possible, criterion-based grading where needed, metering, run persistence and aggregation. | Validate task IDs/counts/types, required edge/unanswerable cases, reference isolation, grader calculations and incomplete-run handling. |
| H3: real evaluation | Verify a small development pilot, freeze versions, then execute the complete comparison and repeated Agent runs. | Retain every outcome, error, timeout and actual usage record. Recompute the table and flip list from saved runs; explain a real failure. |

H0 is the current checkpoint. H1–H3 are not implemented by creating this branch.

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

No homework model requests or formal evaluation have been executed at branch setup. No benchmark scores are claimed. The existing M3.5 acceptance records remain historical project evidence.
