# H5 actual-run record and reproduction

H5 completed one frozen 50-task formal comparison: 50 baseline executions and 150 Agent executions. The designated first Agent repeat passed 47/50 (94%); baseline passed 39/50 (78%). Agent pass@3 is 49/50 (98%), pass^3 is 38/50 (76%), with eleven mixed-outcome task vectors. Pooled Agent accuracy is separately 131/150 (87.33%).

See [H5 verification](../docs/verification/H5.md) for the complete metric table, task-type breakdown, development revisions, measured usage and limits. Full formal records are in `docs/verification/h5/formal/`; canonical tables/vectors are in `docs/verification/h5/results/`.

## Recompute without making API requests

From the repository root, choose new output paths:

```powershell
.\.venv\Scripts\python.exe -m scripts.homework.summarize --experiment-dir docs/verification/h5/formal --output-dir work/h5/recomputed-results
.\.venv\Scripts\python.exe -m scripts.homework.audit_h5 --pilot-dir docs/verification/h5/development/pilot-03 --formal-dir docs/verification/h5/formal --output work/h5/recomputed-audit.json
```

Summary uses only saved records and does not need an API key. The audit additionally verifies the locally frozen input bundle/configuration without enabling a model. Existing outputs are never overwritten; use a fresh destination for another recomputation. Generated timestamps may differ, but outcomes, denominators, metrics, source hashes and usage totals must match.

```powershell
.\.venv\Scripts\python.exe -m scripts.homework.validate_tasks
.\.venv\Scripts\python.exe -m pytest -q
```

The frozen source revision is `61d7b844bf201ed55e12196678779c8c63807ba9`; `formal_freeze.json` records the complete experiment fingerprint. Candidate/grader/runner source stayed unchanged during formal execution. Resuming the already completed experiment does not collect new draws or repair failures. A new live comparison requires an explicitly enabled model, a new labelled directory and its own complete scheduled outcomes.

The H1 validator's `formal_evaluation: not_run` describes that validator's own no-model operation; current H5 execution status comes from the saved formal records and summary.

## Record locations

| Artifact | Purpose |
| --- | --- |
| `formal_freeze.json` | Source revision, experiment/plan hash, model/data/configuration locks, prescribed repeats and pre-run cost estimate. |
| `docs/verification/h5/development/` | All actual pilot attempts, including early failures, judge errors and abandoned unexecuted development entries. |
| `docs/verification/h5/grader_v2_calibration/`, `grader_v3_calibration/` | Actual recalibration decisions; original five user labels reused, one skipped case excluded. |
| `docs/verification/h5/formal/entries/` | 200 immutable candidate/grade pairs and their started markers. |
| `docs/verification/h5/results/` | Final CSV/Markdown/JSON comparison, all repeat vectors and flip tasks. |
| `docs/verification/h5/results_by_type.json` | Separate exact/tool/rubric/unanswerable denominators. |
| `docs/verification/h5/final_audit.json`, `verification.json` | Trace/version/budget checks and complete actual-run accounting. |
| `docs/verification/h5/usage_accounting.json` | Formal cost and all H5 development/recalibration costs, separately from candidate efficiency metrics. |
| `docs/verification/h5/artifact_manifest.jsonl` | Byte hashes for JSON evidence; derived CSV/Markdown can be regenerated. |

The formal run used 409 candidate and 160 judge requests, estimated USD 1.92869955. All H5 work, including unsuccessful development attempts and recalibration, is estimated USD 2.58230715. Token usage is measured; cost uses the dated project price lock and is not an invoice.

The accuracy difference is concentrated in first-tool-call tasks: baseline 1/8 versus Agent repeat 1 at 8/8. Exact and unanswerable primary rates are equal; rubric accuracy differs by one task. The small corpus and same-family judge with five human labels limit generalization.

H6 is complete: see the [final report](FINAL_REPORT.md), [failure analysis](FAILURE_ANALYSIS.md), [submission instructions](SUBMISSION_README.md) and [verification](../docs/verification/H6.md). The final project's broader/safety benchmarks remain separate.
