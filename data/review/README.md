# M6.1 research inputs

These files are audit/research inputs. The runtime catalog remains `data/catalog/m35_seed.json`; nothing in this directory creates a formal program, source binding or recommendation.

- `m61_candidate_index.json`: reduced identity leads from the already imported 83-row CS Grad tracker snapshot. Original public labels are preserved, including upstream encoding artifacts. It retains the pinned commit, upstream SHA-256, date, intake, halt flags and review flags. Source tiers, application fees, test-score/deadline claims and admissions datapoints are excluded.
- `m61_review_plan.json`: explicit links from ten leads to the existing reviewed catalog, followed by ten independently researched expansion leads. Existing `candidate_source_id` provenance is not overwritten; in particular, the two CMU records keep their official-comparison provenance. Proposed IDs are research identifiers until degree/campus/track scope is resolved.

The first ten official program pages were read on 2026-11-19 through the web tool. Each research entry records its URL, short excerpt and scope caveat. These notes have no raw HTTP response hash and are **not** runtime `SourceRecord` evidence. Before importing new numerical facts, capture the applicable official page, record the response/snapshot hashes, bind exact values, and run catalog/constraint validation. CMU ECE, Duke ECE and UCSD still require campus/degree/pathway resolution. UW Tacoma's varying degree-pathway credits must not become one unsupported per-credit total.

## Candidate metadata attribution

Source: **CS Grad contributors**, [project](https://csgrad.com/), [pinned tracker JSON](https://raw.githubusercontent.com/csms-apply/csgrad/a60f321365c0f00594e4d593de6f0383428bd59d/src/lib/tracker/school-list.json), commit `a60f321365c0f00594e4d593de6f0383428bd59d`. Upstream generated date: 2026-10-25; intake: Fall 2027. Original JSON SHA-256: `793b4685a323229b99ec39783ca0bb388c2870551e9ee05b6b66b357a31d4ffb`.

The project homepage displays **CC BY-NC-SA 4.0**, checked again on 2026-11-19. The reduced candidate index and its candidate-derived report metadata retain attribution and the [CC BY-NC-SA 4.0 notice](https://creativecommons.org/licenses/by-nc-sa/4.0/). Changes: reduction to identity leads/review flags, independent screening and explicit catalog links; no source risk labels are mapped to personalized tiers. This data notice does not change the license of application code or university pages. No restricted CS Grad DataPoints content is accessed or redistributed.

## Offline reproduction

```powershell
.\.venv\Scripts\python.exe -m scripts.audit_catalog
.\.venv\Scripts\python.exe -m scripts.verify_m61
```

Both use bundled public inputs and make no model/network request. A local full-file/database cross-check is available when the original import material exists:

```powershell
.\.venv\Scripts\python.exe -m scripts.audit_catalog --original-tracker work/csgrad-school-list.json --candidate-database work/csgrad_candidates.db
```

The full source JSON and candidate SQLite are optional local material, not requirements for a clean checkout. Their checks are explicitly marked `not_supplied` when absent; the bundled reduced snapshot remains traceable to its pinned source. Reports go to fresh ignored `work/m61/<id>/` directories and never replace prior attempts or either database.
