# One actual formal Agent failure

In formal run t26--react--r2 (trace 67b2d63c-c209-412d-b5fb-0a95278d0753), the user explicitly requested program checks for uci-mcs-irvine at profile version 1. The required first action was check_program with that program_id and profile_version=1, but the first model decision selected get_program with only the program_id. That lookup succeeded; the second decision called check_program correctly and identified IELTS speaking 5.5 below the required module minimum of 6, despite an overall score of 7. The final answer passed the application validator. The run nevertheless failed because the prespecified tool grader compares the first actual call, so a correct later call cannot repair the earlier ordering mistake. The first causally wrong step was therefore the model's discretionary lookup before the requested check, rather than a tool execution failure, an overall/module score mix-up, or a judge error. A future revision should honor valid explicit direct-check requests before optional inspection, with a separate regression case for this ordering rule; that change was not applied to the frozen experiment.

## Evidence trail

| Step | Actual record | Consequence |
| --- | --- | --- |
| Request | Run checks for `uci-mcs-irvine`, current profile version 1; inspect declared IELTS modules. | Expected first call: `check_program({"program_id":"uci-mcs-irvine","profile_version":1})`. |
| First model decision | Span `651e38fa-bb04-4971-8d4f-4da622b29bdc` selected `get_program({"program_id":"uci-mcs-irvine"})`. | First causally wrong action under the fixed tool-task rule. |
| First tool | Span `b6c7191c-e45c-441c-8633-b182d8dd538e` returned the program record successfully. | No tool failure forced the detour. |
| Second tool | Span `8f3dfd15-63f3-4bc3-8d3a-4a0793e6d738` ran `check_program` with the expected arguments. | English check correctly failed: speaking 5.5 < 6. |
| Final answer | Reports the module-level failure and keeps the program out of formal recommendations. | Application validation accepted the answer; applicant fields stayed unchanged. |
| Grading | The only failing code criterion was `first_tool_call`; no LLM judge was called. | Procedural action-order failure, not a demonstrated error in the final English conclusion. |

The three prescribed Agent outcomes for t26 were [pass, fail, pass], so this task belongs to the eleven-task flip list.

[Full candidate trace](../docs/verification/h5/formal/entries/t26--react--r2/candidate.json)

[Saved grade](../docs/verification/h5/formal/entries/t26--react--r2/grade.json)

[Machine-checked failure facts](../docs/verification/h6/failure_case.json)

## Proposed follow-up, outside the frozen benchmark

Prioritize a valid explicitly named direct-check operation with known arguments before discretionary inspection; use later tool results to decide whether more retrieval is needed. Do not learn task IDs, expected answers, or reference-only metadata. A fresh regression input uses profile version 3 to exercise the same general rule without changing the original task or scores:

- [Candidate-only input](../homework/regressions/direct_check_first_input.json).
- [Evaluator-only expected call](../homework/regressions/direct_check_first_reference.json).

The proposal is not implemented or model-tested in H6. The regression case is outside the 50 formal tasks and is excluded from every reported denominator. No formal answer, grade, trace or score was altered.
