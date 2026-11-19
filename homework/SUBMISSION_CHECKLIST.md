# Final assignment compliance review

Reviewed November 18, 2026 against the final instructions supplied by the user. Due Friday, November 20, 2026, 11:59 PM Pacific Time. The latest deadline supersedes the earlier slide deadline; experiment dates and frozen evidence are unchanged.

| Requirement | Verified evidence | Status |
| --- | --- | --- |
| 50 tasks in lecture JSONL format, with answers/rubrics | 50 unique records; 18 exact, 8 tool, 20 rubric, 4 unanswerable; all type-specific fields validate | Pass |
| At least 3 edge cases and 2 unanswerable tasks | 11 overlapping edge-case tags; 4 unanswerable tasks | Pass |
| One script runs Agent and non-agentic baseline on all 50 | Root `eval.py` delegates to the shared runner; frozen schedule has 50 baseline plus 150 Agent executions | Pass |
| Accuracy, average turns, average/p95 latency, average tokens side by side | `submission_results.csv` and report; values recompute from actual candidate records | Pass |
| Trace one failure and explain the wrong step/cause in one paragraph | `failure_analysis.md`: t26 Agent repeat 2 first selected `get_program` instead of `check_program`; native trace and deterministic grade preserved | Pass |
| Agent runs 3 times on every task | Each of 50 task IDs has repeats 1, 2 and 3, with complete pass/fail outcomes | Pass |
| pass@3, pass^3 and changing-outcome task list | 49/50 = 98%; 38/50 = 76%; eleven flip IDs with complete vectors | Pass |
| Both members' names and UW NetIDs; one team submission | Fill root `TEAM.md`; blanks retained at the user's request | **Pending team entry** |

Flip IDs: t18, t26, t28, t29, t33, t41, t42, t43, t44, t45, t49.

The main comparison uses the Agent's predesignated first repeat for accuracy/efficiency. The two stability columns use all three repeats on the same 50 tasks. Baseline stability is N/A because the assignment requires only one baseline run per task.

Submit the ZIP after completing `TEAM.md`. It includes root `tasks.jsonl`, `eval.py`, the consolidated results table and the failure paragraph, plus the report and supporting source/evidence. Editing the team-information file does not require model requests; rebuild the ZIP using the supplied builder to refresh its integrity manifest, or attach the completed team file separately alongside the original ZIP. This review does not upload to Canvas or replace any frozen evaluation outcome.
