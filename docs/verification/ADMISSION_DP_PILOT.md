# Local admissions datapoint coverage pilot

The pilot maps 13 program identities from a local applicant-reported export to GradMatch's recommendation pool. The [mapping](../../data/review/admission_dp_pilot.json) records each source program ID, degree, and track. The audit checks all bindings against the same identity lookup used by the 83-program recommendation service. Nine groups have reviewed program records, and four have community catalog identities for historical context.

The expansion adds CMU MSAII, Illinois ECE MEng, UC Irvine MCS, Georgia Tech MSCS, Brown ScM CS, CMU MSCS, Northwestern MSCS, and Illinois thesis MSCS. Identical tracker IDs distinguish Illinois MCS, ECE MEng, and thesis MSCS. The UC Irvine export has separate professional MCS and MSCS entries. See [Illinois degree options](https://siebelschool.illinois.edu/admissions/graduate/degree-program-options) and [UC Irvine program distinctions](https://mcs.ics.uci.edu/mcs-vs-mscs/).

The Brown match uses cohorts through Fall 2026. The export lacks a delivery-mode field, and Brown launches a separate AI/ML track with online and residential delivery from Fall 2027. The raw Columbia MSCS, Rice MCS, and Northeastern CS General identifiers do not establish the delivery mode or campus needed for the proposed matches. Those rows stay outside this batch. See [Brown's degree page](https://cs.brown.edu/degrees/masters/), [Columbia's CVN FAQ](https://www.cs.columbia.edu/education/undergraduate/prospectivefaq/), and [Rice's delivery-mode comparison](https://cs.rice.edu/academics/graduate-programs/master-computer-science).

## Run the audit

```powershell
python -m scripts.audit_admission_dp --input '<path to local admissions export>' --intake-year 2027 --intake-term fall --gpa-scale 4 --gpa-scope overall
python -m pytest -q tests/test_admission_dp_audit.py
```

Each run writes an aggregate `coverage.json` to a new ignored `work/admissions_dp/` directory. The report includes the input hash, program-level coverage, duplicate, conflict and route-exclusion counts, and outcomes before and after GPA filtering. Applicant identifiers are used in memory to deduplicate. Personal fields and raw submission text are omitted from the output. The audit needs no model, network, or write to the catalog or application database.

For Fall 2027, the eligible cycles in this export are Fall 2024 through Fall 2026. Reports with the same applicant, program, year and term form one group. A repeated applicant contributes at most once per program, from their latest cycle in the window. Conflicting outcomes within that cycle remain unresolved. The audit counts explicit admits and rejects separately and records silent rejection as an unconfirmed decision.

The GPA coverage checks use a valid original GPA and an exact numeric scale. The local pilot provisionally treats a missing scope as overall GPA. The report counts explicit scope matches, assumed overall matches, and their combined coverage. Existing scope values still take precedence. Unrecognized values and assumptions cannot match a last-60-semester or last-90-quarter comparison. The current export has no structured GPA calculation-scope field, so its overall comparison counts all use the assumption.

## Preview on recommendation cards

Add `--write-preview` to the audit command to activate an aggregate-only preview for the chosen intake, GPA scale, and scope. The audit writes `work/admissions_dp/recommendation_preview.json`. The preview contains program IDs, decision counts, and comparison metadata.

Run `python -m streamlit run app.py` locally. Select **Load tiering example (USD 140,000)** and **Generate / rerun**, then look for **Historical applicant comparisons** in the recommendation cards and the details for mapped pending programs. The default example matches Fall 2027 and a 4-point overall GPA. The display filters by GPA scale and scope. Counts are self-reported context for that basis. Additional pending-program details appear when they have a matching preview.

**Compare candidates by historical sample coverage** orders current candidates by the number of explicit decisions in the applicant's GPA band. Each original scale is divided into 16 equal-width bands. On a 4-point scale, each band spans 0.25 points. Lower endpoints are included, and the maximum score belongs to the final band. The table shows candidates with at least five decisions and preserves assessment order among equal sample sizes. The program cards still show overall counts and indicate when the matching band has fewer than five reports. Re-run the preview command to add band data to an existing local preview.

## Use historical reports in preliminary ranking

Start the app with a local preview and choose the **All 83 programs** pool. **Use historical reports in preliminary ranking** defaults to off. Enable it and submit **Generate / rerun** with a matching profile and model ranking enabled. This gives all three strategies the same optional input to their shared ranking call.

The code selects aggregates for eligible preliminary candidates in the applicant's GPA band, scale, scope and intake. Each option has at least five decisions. The model can use the added context when selecting or ordering preliminary suggestions. To cite a row it returns its program-specific evidence ID. The validator matches the ID to the exact options offered in the current draft, then attaches the original aggregate for display and audit. The applicable eligibility checks and formal tier rules still use their official evidence. The app records whether history was enabled, the aggregate snapshot fingerprint, and how many options were offered and cited.

The local preview contains aggregate fields only. With model ranking enabled, aggregate options for matching candidates may be sent to the provider. Validated citations are included in that assessment's session export. The M6.4 evaluation suite uses the shared engine with this optional input off.

```powershell
python -m pytest -q tests/test_admission_history_ranking.py
```

The offline paired checks use a controlled provider and identical fictional profiles. They verify that each strategy can cite provided DP evidence, that hard failures remove a program and its aggregate on the next rank, and that a cross-program or stale reference cannot authorize a citation.

### Bounded model pilot

```powershell
python -m scripts.pilot_history_ranking
```

The default command checks local inputs without calling a model. Add `--live-model` to run one paid pair of Plan-and-replan snapshot assessments, with a limit of three model requests per arm. The two fresh sessions use the same synthetic Fall 2027 CS applicant with a 3.80/4.00 overall GPA.

On November 22, 2026, both arms retrieved the full pool of 83 programs. The first ranking input matched across arms apart from the nine optional DP aggregates sent to the enabled arm. The run used six requests to `gpt-5.4-mini-2026-03-17`, with an estimated total model cost of USD 0.0541.

The first drafts reproduced the following outcomes in a zero-request replay of the application validators.

| First draft validation | DP off | DP on |
| --- | ---: | ---: |
| Preliminary suggestions retained by the validator | 7 | 8 |
| Verified historical citations | 0 | 2 |
| Supported formal tiers | CMU MSAII, Lottery | CMU MSAII, Lottery |

The citations refer to the matching overall 3.75–4.00 GPA band for Brown's Sc.M. in Computer Science (6 admits and 2 rejects) and CMU's MSCS (2 admits and 4 rejects). The first validation of both drafts rejected UC Irvine MCS as a formal Target because its reviewed tier evidence was missing. Both agents replanned and reached the per-arm request limit before they could rank again. The end-to-end comparison remains inconclusive, and this pair supplies no estimate of recommendation quality.

Broad ranking now omits programs without a reviewed tier option from the model's formal allowlist. An eligibility-passing program such as UC Irvine MCS stays available for a preliminary suggestion. The three strategy regression checks exercise this distinction, and all 45 development benchmark fixtures pass. The saved real pair predates this change.

The original sessions, rank input fingerprints, aggregate rows, and `comparison.json` are in `work/admissions_dp/real-ab-a8f4b92187f0/`. The separate `offline_replay.json` captures the replay of the first model drafts. This directory is ignored by Git.

### Post-fix retest

On November 22, 2026, the same fictional applicant and catalog passed a second paired run on `gpt-5.4-mini-2026-03-17`. Both sessions completed the search, constraint check, rank, and validation steps of the initial plan and screened all 83 programs. Each used two model requests. The estimated total model cost was USD 0.0402.

| Completed assessment | DP off | DP on |
| --- | ---: | ---: |
| Programs screened | 83 | 83 |
| History aggregates offered to the ranker | 0 | 9 |
| Preliminary suggestions | 6 | 8 |
| Verified historical citations | 0 | 2 |
| Supported formal tier | CMU MSAII, Lottery | CMU MSAII, Lottery |

The base ranking inputs matched. There were no validation errors, and both results retained `insufficient_evidence` as the assessment status because some candidates still lacked evidence for formal tiers. UC Irvine MCS appeared as a preliminary suggestion in the control arm. The enabled arm cited Brown's computer science Sc.M. and CMU's MSCS in the same GPA band and with the same recorded counts as the first pilot. This single pair verifies that the application can complete the workflow and attach eligible DP references. Ranking quality requires a separate evaluation.

The successful run's full session traces and `comparison.json` are in the ignored local directory `work/admissions_dp/real-ab-6c21b1f5e46a/`.

## Six-profile paired evaluation

The [pilot suite](../../eval/dp_pilot.json) pins the assessment date, official catalog, community catalog and local aggregate preview. Both arms run fresh Plan-and-replan sessions in snapshot mode with the same fictional profile. The run order alternates. The six profiles cover CS employment, CS research, a GPA band boundary with a reduced budget, ECE, sparse history and a mismatched GPA calculation scope. The single-profile pilot is repeated as a calibration case.

```powershell
python -m scripts.evaluate_history_ranking
python -m scripts.evaluate_history_ranking --fixtures
```

The first command verifies the pinned inputs and prints the schedule. Fixture mode blocks network calls and exercises the production assessment and validation path with controlled drafts. A paid run uses `--live-model`, which schedules 12 sessions with a cap of three model requests per session. All run artifacts stay in an ignored local directory.

The automatic comparison checks plan completion, matching base ranking inputs, expected DP coverage, verified exclusions, and same-program citation binding. Formal tier agreement and the number of citations are reported alongside those checks. `blind_review.json` presents up to five preliminary recommendations per arm with anonymous labels, reasons, and check statuses. Reviewers score goal fit, handling of constraints, and actionability from 0 to 2 and leave a concrete example. The separate comparison file holds the arm key and records all pairs, including failures. Only completed pairs with matching inputs and passing checks enter the blind review.

The first fixture run found that the model's formal options still included an employment-only program for the research profile. The broad ranker now requires a goal feature matching the applicant's goal as well as a reviewed tier option. The research profile can still consider that program as a preliminary suggestion. The first run is preserved in `work/admissions_dp/batch-6a15c90057cf/`.

The fixture rerun passed all six pairs with zero paid requests. The enabled arms offered 9, 9, 7, 2, 0 and 0 DP aggregates, respectively. The USD 50,000 case excluded USC MSCS and NYU Tandon MSCS from the recommendations and ranker's history options. The fixture report and reviewer packet are in `work/admissions_dp/batch-30d196ab6a58/`.

### Model-backed pilot results

On November 22, 2026, all six pairs passed on `gpt-5.4-mini-2026-03-17`. All 12 sessions completed the 83-program assessment, using two requests each. Total estimated model cost was USD 0.2316. Both arms agreed on formal tiers and verified exclusions for every profile.

| Profile | DP options when enabled | Valid DP citations | DP off shortlist score / 6 | DP on shortlist score / 6 |
| --- | ---: | ---: | ---: | ---: |
| CS employment | 9 | 3 | 3 | 6 |
| CS research | 9 | 2 | 4 | 4 |
| USD 50,000 budget | 7 | 2 | 3 | 3 |
| ECE employment | 2 | 2 | 3 | 5 |
| Sparse GPA band | 0 | 0 | 6 | 6 |
| Mismatched GPA scope | 0 | 0 | 6 | 6 |

The enabled arm cited history in every profile with eligible DP, with nine verified citations total. The sparse-band and mismatched-scope controls produced no history options or citations. At USD 50,000, both arms excluded USC MSCS and NYU Tandon MSCS. Every program in either top-five shortlist still lacked verified tuition.

One Codex review scored the anonymized top-five shortlists on goal fit, constraint handling, and actionability before opening the arm key. The enabled arm scored higher in two pairs and tied in four. Its mean was 5.00 out of 6, compared with 4.17 for the control. In both higher-scoring pairs, four of five enabled suggestions and one of five control suggestions had verified tuition checks. The research profile's leading suggestions included professional routes in both arms, and their reasons did not establish research fit. These scores describe one review of six fictional profiles and one execution per arm. A broader quality estimate requires additional cases, repeated runs, and independent review.

The comparison, unscored blind packet, and review notes are in `work/admissions_dp/batch-857c2dc688ea/` as `comparison.json`, `blind_review.json`, and `blind_review_scored.json`.

## Check readiness for Target

```powershell
python -m scripts.audit_target_readiness --input '<path to local admissions export>'
```

The report uses the fictional CS tiering profile with overall GPAs of 3.50 and 3.80 on a 4-point scale. It screens the same recent, deduplicated reports by GPA band, a controlled set of CS major labels, and a positive reported research or internship count shared with the reference profile. It reports matching admitted and rejected cases. This is a screen for manual comparison of actual academic background and experience.

For each reviewed program and profile, the report runs the application's official hard checks and `Target` tier validator against the active catalog. It records the remaining eligibility, budget, goal and reviewed-case gaps. Community-only entries receive background counts and an explicit missing-official-record finding. The screening counts are local research inputs. Only existing source-bound catalog evidence is passed to the tier validator.
