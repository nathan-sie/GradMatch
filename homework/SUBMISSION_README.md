# GradMatch evaluation homework submission

Start with **report.pdf** (three-page English report) or **report.md**. The package contains the required task file, evaluation entry point, results table with repeated-run measures, and one actual Agent failure analysis with its full trace.

**Due Friday, November 20, 2026, at 11:59 PM Pacific Time. One submission per two-person team.** Complete both full names and UW NetIDs in root `TEAM.md` before submission; these fields are intentionally blank for team review. See `SUBMISSION_CHECKLIST.md` for the final requirement-by-requirement audit.

## Required deliverables

| Item | Location |
| --- | --- |
| 50 tasks with known answers/rubrics | `tasks.jsonl`; identical canonical copy at `homework/tasks.jsonl` |
| One evaluation script for both systems | `eval.py`, delegating to `scripts/homework/evaluate.py` |
| Consolidated side-by-side metrics including pass@3 and pass^3 | `submission_results.csv`; full original values in `results.csv`, `results.md`, `results.json` |
| pass@3, pass^3, flip IDs/vectors | Report, `flip_tasks.json`, `repeat_vectors.json` |
| One actual failed step and cause | `failure_analysis.md` and report |
| Full failure trace and grade | `docs/verification/h5/formal/entries/t26--react--r2/` |
| All 200 formal candidate/grade pairs | `docs/verification/h5/formal/entries/` |
| Frozen references, model/data/code locks | `homework/references.jsonl`, `homework/formal_freeze.json` |
| Byte-integrity inventory | `submission_manifest.json` |
| Both members' names and UW NetIDs | Complete `TEAM.md` before submitting |

No API key, local SQLite database, virtual environment or lecture PDF is included. Applicant profiles are fictional. Root convenience copies do not change the canonical frozen files used by the runner.

## Environment

Use Python 3.12. The recorded run used Python 3.12.14, OpenAI SDK 2.54.0 and Pydantic 2.14.3. Install the locked dependencies with:

```powershell
uv sync --frozen
```

The commands below assume that environment is active; alternatively prefix Python with `uv run --frozen`.

## Recompute without paid requests

From the extracted package root:

```powershell
python -m scripts.homework.validate_tasks
python -m scripts.homework.summarize --experiment-dir docs/verification/h5/formal --output-dir work/recomputed-results
python eval.py --dry-run --experiment-dir work/review-plan
```

Use new output directories for another invocation. Validation and summary make no model requests. The last command writes a 200-entry plan (50 baseline plus 150 Agent) and no benchmark scores. Existing actual outcomes are never replaced.

The expected comparison is baseline 39/50 (78%) and designated Agent repeat 1 at 47/50 (94%); pass@3 is 49/50 (98%), pass^3 is 38/50 (76%) and eleven tasks flip. The optional pooled Agent row is 131/150 (87.33%). Read the task-type breakdown and limitations before generalizing.

## A new live experiment

Only if intentionally collecting a new paid comparison, configure a local `.env` from `.env.example`, enable `MODEL_ENABLED=true`, and use a new labelled directory with the explicit flag:

```powershell
python eval.py --tasks homework/tasks.jsonl --agent-repeats 3 --live-model --experiment-dir work/new-live-experiment
```

This includes required judge requests. Model/data/criteria limits must remain frozen within one experiment. The published results require no rerun. Never place keys in tasks, reports or the submission.

## Selected failure and proposed regression

In t26 Agent repeat 2, the first native action was `get_program` instead of the requested `check_program`. Both tools later succeeded, and the final IELTS module conclusion was correct, but the deterministic first-tool grader failed the run. Trace and grade are linked from the report.

`homework/regressions/direct_check_first_input.json` is a candidate-only future regression at profile version 3; its evaluator-only reference is separate. Neither file is added to the original 50 tasks or reported denominators. No proposed policy fix was applied to the frozen experiment.

## Scope

This package completes the evaluation-harness homework. It does not represent the final project's 200-unique-task/safety evaluation, a new web deployment or a Canvas upload. Main and the existing public application are unchanged.
