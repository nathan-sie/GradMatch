# GradMatch: Evaluation Harness Report

**50-task course homework | November 17, 2026 | Frozen snapshot evaluation**

## System and evaluation design

GradMatch answers graduate-program eligibility, cost and planning questions using reviewed official snapshots. The non-agentic baseline executes fixed search, scoped record retrieval and deterministic checks, then one answer call per user turn. The Agent chooses its next native tool call or final answer from observations. Both use the same ten-program catalog, model, constraint rules, tier rubric and per-task ceilings.

The frozen set contains 50 tasks: 18 exact, 8 first-tool-call, 20 rubric and 4 unanswerable; 11 have overlapping edge-case tags and 3 include follow-ups. Exactly one baseline execution and three Agent executions per task produced 200 candidate/grade pairs. Agent repeat 1 was designated for the primary comparison before execution. Assessment date: 2026-11-16. Model: `gpt-5.4-mini-2026-03-17`.

Candidates never receive expected answers, expected calls, grading rubrics, task types or evaluator references. Tools are read-only catalog search, program lookup, evidence lookup and current-profile checks. Open answers must pass correct, grounded, complete and in-policy criteria, plus task-specific items. Tool tasks compare the first actual call's exact name and arguments. The judge is blind to candidate strategy and efficiency metrics and selects evidence only from exact candidate answer/profile spans.

## Results

| System | Accuracy | Passed / tasks | Avg turns | Avg latency (s) | p95 latency (s) | Avg tokens |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Fixed baseline | 78% | 39/50 | 1.06 | 2.335 | 4.782 | 7,146.02 |
| Agent repeat 1 | 94% | 47/50 | 2.32 | 3.696 | 5.672 | 8,985.56 |

Turns count all candidate model calls, including setup and profile interpretation. Candidate latency includes tools/waits and failed executions, excludes grading, and uses nearest-rank p95. Tokens sum input plus output without adding cached input twice. Every scheduled task remains in its denominator.

| Repeated-run measure | Observed |
| --- | ---: |
| pass@3: at least one of three passes | 49/50 = 98% |
| pass^3: all three pass | 38/50 = 76% |
| Mixed pass/fail tasks | 11/50 |
| Agent pooled accuracy, separately labelled | 131/150 = 87.33% |

Flip IDs: t18, t26, t28, t29, t33, t41, t42, t43, t44, t45, t49. Task t27 failed all three repeats. The observed vectors, rather than cubed overall accuracy, define pass^3.

| Task type | Baseline | Agent repeat 1 |
| --- | ---: | ---: |
| Exact | 18/18 | 18/18 |
| First-tool-call | 1/8 | 8/8 |
| Rubric | 16/20 | 17/20 |
| Unanswerable | 4/4 | 4/4 |

Seven of the eight additional first-repeat passes come from tool-selection cases: the baseline's fixed search-first action cannot satisfy a requested direct first lookup/check. Exact and unanswerable primary results are equal; the rubric difference is one task. The Agent spends more calls, time and tokens. These results show better action adherence on this authored set, not a general 16-point gain in admission advising.

## One traced failure

In formal run t26--react--r2 (trace 67b2d63c-c209-412d-b5fb-0a95278d0753), the user explicitly requested program checks for uci-mcs-irvine at profile version 1. The required first action was check_program with that program_id and profile_version=1, but the first model decision selected get_program with only the program_id. That lookup succeeded; the second decision called check_program correctly and identified IELTS speaking 5.5 below the required module minimum of 6, despite an overall score of 7. The final answer passed the application validator. The run nevertheless failed because the prespecified tool grader compares the first actual call, so a correct later call cannot repair the earlier ordering mistake. The first causally wrong step was therefore the model's discretionary lookup before the requested check, rather than a tool execution failure, an overall/module score mix-up, or a judge error. A future revision should honor valid explicit direct-check requests before optional inspection, with a separate regression case for this ordering rule; that change was not applied to the frozen experiment.

The t26 repeat vector is [pass, fail, pass]. [Candidate trace](../docs/verification/h5/formal/entries/t26--react--r2/candidate.json), [saved grade](../docs/verification/h5/formal/entries/t26--react--r2/grade.json), and [step-level evidence](../homework/FAILURE_ANALYSIS.md) allow independent inspection. This is a procedural first-action failure even though the final module-score conclusion is consistent with the recorded rule.

## Reproducibility and usage

Source revision `61d7b844bf201ed55e12196678779c8c63807ba9` and the [formal lock](../homework/formal_freeze.json) were pinned before execution. Experiment `bf76953d-36e5-46e9-a73b-34df32e0e697` used 50 baseline and 150 Agent executions, interleaved by task. The first 20 entries were checked, then the same plan resumed for the remaining 180. Candidate/grader/runner source stayed unchanged; no failed result was rerun or replaced.

All 200 outcomes are known: 170 passed and 30 failed, including 8 validation-rejected candidate outputs. There were zero unresolved cases, judge errors or missing usage measurements. Verification checked 200 distinct candidate traces, 569 distinct provider response IDs and all 934 criterion evidence items against exact candidate substrings. All 244 pre-freeze regression tests passed.

| Formal usage stream | Requests | Input tokens | Output tokens | Estimated USD |
| --- | ---: | ---: | ---: | ---: |
| Candidate | 409 | 1,699,158 | 47,723 | 0.86272200 |
| Judge | 160 | 1,227,393 | 36,984 | 1.06597755 |
| Total | 569 | Separate streams | Separate streams | 1.92869955 |

The final 32-execution development pilot had 30 passes, 2 failures and no judge errors. Earlier failed pilot/calibration attempts remain separate and preserved. All H5 development and recalibration add USD 0.65360760, giving an H5 total estimate of USD 2.58230715. Cost uses actual provider usage and the dated project price lock, not an invoice.

The ZIP includes tasks, evaluator references, runnable source, the lockfile, official snapshots, all formal records, development history, results/vectors and this report. The root `eval.py` runs both strategies and defaults to no-cost planning. Results can be recomputed offline without an API key; a new live comparison requires explicit enablement and a new labelled experiment. See [submission instructions](../homework/SUBMISSION_README.md).

## Limits and next work

This is a small authored 50-task snapshot corpus over ten programs. Judge and candidate share a model family; only five binary human calibration labels were obtained, with one skipped case. Judge decisions varied on a saved development answer, so repeat stability includes grading variation as well as candidate variation. The selected t26 failure avoids that ambiguity because its first-tool criterion is deterministic.

No proposed failure fix was applied to the frozen run. A candidate-only regression input and separate expected-call reference are provided for future development. Live web/PDF retrieval, broader program coverage, the final project's larger task set and its safety evaluation remain separate. Main and the public application retain their accepted checkpoint.
