# M6.1 research inputs

M6.2 adds `data/community/csgrad_tracker_v1.json`, a separate, reduced snapshot of reported language, GRE, application rounds, fees and portals for all 83 identities. The original identity index remains unchanged. `python -m scripts.build_community --input work/csgrad-school-list.json` verifies the pinned full-file hash before rebuilding this snapshot. Clean hosts use the bundled result without the ignored raw file. Community fields are stored in the rebuildable directory SQLite and shown as preliminary; they are not imported as verified university facts. See `docs/verification/M62.md`.

These files supply audit/research inputs and, from M6.1d, the public exploration directory. `data/catalog/active.json` selects `m61j_seed.json`: 20 identities / 145 sources. The M6.1j manifest reviews MCDS and NYU Tandon CS with seven new sources, preserving all 138 earlier source objects, tuition policies and the exact 20-to-83 mapping. Nine scripted capture attempts include two obsolete MCDS URLs returning 404. English and GPA-scope gaps remain explicit; cached or typical scores do not establish a minimum. See `docs/M61J_SOURCES.md`.

The preceding M6.1i manifest records seven reviewed programs and 13 new sources while preserving all 125 previous source objects. Four conservative tuition ceilings have source-bound rates, scope, units and unknown minima. Admission research exclusions and all 28 scripted capture receipts remain explicit, including the incorrect FAQ 404 and initial calculator 302 responses. See `docs/M61I_SOURCES.md`.

The preceding M6.1h manifest retains seven reviewed programs and 13 new sources, preserving all 112 earlier source objects. Its 15 receipts include an excluded 403 response and a former application URL that served the homepage. `history:<group>` bindings preserve earlier snapshots without letting them drive current checks; each requires a verified replacement (including score-floor promotion to a complete English policy). See `docs/M61H_SOURCES.md`.

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
