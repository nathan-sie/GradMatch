# H3 independent graders

The evaluator grades a saved H2 result without rerunning the candidate. Answer keys, criteria and human labels never enter candidate inputs. H4 provides scheduling and aggregation; H5 records the actual frozen comparison.

Current revision: H5 uses grader v3. The original H3 checkpoint and its actual decisions remain historical records in `docs/verification/H3.md`. v3 keeps the semantic criteria but replaces model-written evidence quotes with selections from exact candidate-only spans; v1/v2 development failures are retained separately.

## One-result CLI

From the repository root:

```powershell
.\.venv\Scripts\python.exe -m scripts.homework.grade_task --run docs/verification/h2/02-fixed-d08.json
```

Without a live flag, an open answer is saved as `judge_disabled` with `passed: null` after code checks. Tool-only tasks and deterministic failures require no judge. To explicitly make one metered grading request, add `--live-judge`; the existing local OpenAI configuration must be enabled.

Results are saved under ignored `work/h3/grade-<uuid>.json`. `--output` selects a new file; prior results are never overwritten. The default split is development. `--split formal` selects frozen formal references for an existing result; it does not schedule or run that task.

Python exit codes: 0 passed, 1 failed, 2 invalid command/configuration/file, 3 invalid grading input or unavailable/failed semantic grading. A shell may display nonzero Python exits as a generic command failure.

## Decision rules

| Type | Code checks | Semantic requirements |
| --- | --- | --- |
| Exact | Whole normalized value/date/text, requested unit type, observed reference-basis citation and valid state/source metadata. | Correct, grounded, complete and in policy must all pass. A matching number inside a false statement fails. |
| Tool | First actual tool span has the exact expected name and schema-valid arguments. A later call or a tool name in prose cannot substitute. | No judge for the slide's tool-selection task; execution/state/source guards still apply. |
| Rubric | Execution, citations, URLs, resulting profile and forbidden recommendations. | All four standard criteria and every task item pass. |
| Unanswerable | Same source/state guards. | Also require a specific evidence gap and no invention, including after a disclaimer. |

There is no weighted score or model-selected overall pass. All applicable checks must pass.

Numeric matching respects complete quantities, signs, comma groups and decimal values: 145 does not match 45. Dates accept ISO year-month-day or unambiguous English month-name dates; shortened ambiguous dates are not normalized. Unit presence is a code guard; semantic judging independently checks the quantity's meaning, scope and contradictions.

Citations must name real observed IDs and match catalog URL, quote, retrieval date, intake and locator. Exact answers need a citation to their reference basis. The independent grader uses authored references and frozen facts without calling production tuition, constraint or ranking functions as its oracle. H1 reference/data locks must still pass `scripts.homework.validate_tasks`.

Final state must contain only the reference's explicit changes, preserve other fields and advance its version only for a real change. Confirmation prose cannot hide an unintended budget/GPA update.

## Judge contract and errors

The judge receives question/setup, criteria, reference facts, relevant frozen evidence, final answer, observed source IDs, reported checks and before/after profile. Strategy, candidate model/run IDs, usage, latency and calibration labels are omitted. The answer and source text are untrusted data.

The model returns a strict object with every criterion as a required key. Each value has a strict boolean, concise reason and an `evidence_id` selected from an enum of exact candidate answer/profile spans. The evaluator copies the chosen source substring into the final grade; the model does not write quotes. A missing requirement may use a null ID only with a failing verdict. Criterion keys, span IDs, offsets and booleans are checked. The final record preserves the raw verdict, span ID and exact quote. Brief assessment evidence is recorded, never private model reasoning. Legacy quote validation remains available for diagnostic replay of old records and offline fixtures.

Grading uses a separate provider/trace/usage record: `store=False`, no tools or prior response state, at most one request per grade, a 45-second timeout, 2,400 output tokens and no automatic retries. Failed/incomplete/invalid responses retain measured usage and raw output when available; SDK exception messages and API keys are not logged.

`judge_error`, `judge_disabled` and `invalid_input` keep `passed: null`. Later aggregation must show these states, count none as passes and retain scheduled denominators. Candidate execution failures are failed outcomes without a judge call. Candidate and grader usage stay separate.

## Calibration and lock

`calibration_cases.jsonl` holds six authored English answers with the same facts/meaning as the examples presented to the user in Chinese. Five have binary human labels; D was skipped and is excluded from human agreement. They are authored fixtures, not actual Agent executions.

```powershell
.\.venv\Scripts\python.exe -m scripts.homework.calibrate_h3 --live-judge
```

This explicitly makes at most eight requests: six semantic probes, including a shadow judgment of the code-rejected wrong-unit answer, and grades for two saved H2 runs. Each attempt is saved immediately to a new directory. `--output-dir` selects a new named attempt; `--resume` continues unchanged saved attempts without replacing failures. A changed grader requires a new labelled attempt.

Actual H3 inspection used eight requests. Both semantic judging and the full pipeline agreed on 5/5 evaluated human labels; D matched the authored incomplete-answer expectation but is not a sixth human agreement. This tiny selected sample is below the lecture's approximately 50-answer guidance and does not prove general reliability. Judge and candidate use the same model family; correlated errors remain possible.

`grader_freeze.json` locks the core grading/prompt/configuration revision and catalog after calibration. Changed core revisions are rejected. H4/H5 will additionally pin the full runner and experiment inputs. See [actual verification](../docs/verification/H3.md).
