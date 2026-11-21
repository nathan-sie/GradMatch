# Coverage-first program data plan

Approved direction on 2026-11-20: expose all 83 imported program leads first, then concentrate official-field review on priority programs. The M6.1f scope recommendation is 20–25 official records, with 10–15 records supporting useful applicant screening and cost comparison as the next quality target. These are different coverage measures. This replaces the earlier sequence of completing a few programs before exposing the next batch. The 210 main tasks, 50 safety prompts and shared evaluation requirements remain separate work.

Updated direction on 2026-11-21: prioritize broad maintained coverage over waiting for exact official verification. M6.2 exposes the available public tracker fields for all 83 records in one batch: language tests, GRE, listed rounds, application fees and public application portals. Source date, intake, attribution and preliminary status accompany the data. The applicant form can save a profile and show the full preliminary pool without a model call. The 20 officially reviewed records enrich their exact identities; more official review becomes a later quality improvement rather than a blocker for broad exploration. GPA and full-program tuition are absent from this tracker snapshot and remain unknown where no reviewed evidence exists.

## Delivered exploration layer

- All 83 pinned tracker identities are searchable by university, program, campus and keyword. Filters distinguish official snapshots, pending review and four source-reported halt flags.
- Twenty exact, reviewed identity links enrich their own entries with official facts. Other programs at the same university do not inherit those rules or prices. Missing GPA, English, tuition, intake, deadlines and admission evidence remain explicit.
- Compare up to four entries and download a comparison with attribution, snapshot date and evidence context. Comparison selections survive changes to search filters.
- A separate content-addressed SQLite directory is rebuilt on clean hosts and after cache loss. Runtime reads use read-only connections. Official recommendation records, provenance and historical source snapshots remain separate and unchanged.
- Browsing and the broad profile-based preview need no API key or model call. Directory membership supplies no admission tier or applicant eligibility decision. Doctoral-route leads and community halt reports remain visible with their original review flags. All 83 now carry structured preliminary details, including 80 listed-round sets, 82 reported fees and 83 application portals. Recommended and typical scores are labelled separately from reported minima; application fees are never tuition.

After M6.1j, the official data contains 20 program records / 145 sources, with eight two-sided tuition estimates, four additional conservative tuition ceilings and one minimum-only bound. Usable preparation policies are ten and complete English policies eight; five additional programs retain score-floor screening only. Seven remaining-eligibility checklists are reviewed; two programs pass hard checks for the fixed fictional profile, while only one has formal tier support. Dated intake/deadline coverage is 14/12; usable GRE coverage is 19, degree 16 and GPA eight. A ceiling is not an exact bill: a smaller budget remains pending. Coverage labels refer to the pinned Fall 2027 reference intake and official review date, not a fresh check of all websites. The directory displays the two existing reviewed cohorts as program-level context, with source links and an explicit non-personal-probability warning. Complete admission-tier support is not promised for every directory entry.

## Next review batches

The four queued tracks are now scoped official identities: Duke ECE MS, CMU Pittsburgh ECE MS, Georgia Tech on-campus MSCS and UCSD CS MS. The initial 20-program focus set is populated. Prioritize missing fields within these records before considering up to five additional identities; selection is based on project coverage needs, not community rankings. Do not count partial identities toward the 10–15 effective-screening target or describe that target as achieved.

Handle 10–15 programs per batch. Capture shared university policies once where the evidence applies to each exact degree, campus, applicant category and period. Apply the same validation to extracted fields; retain exceptions and unknowns. Prioritize complete tuition formulas, GPA/English/degree/GRE/prerequisite requirements, intake and deadlines. Gather goal and admissible admission evidence alongside these fields, with applicant tiers assessed separately.

Run focused checks during each batch, then one regression suite and one release at its end. Publish an updated coverage table distinguishing directory count, official records, usable fields and applicant-specific recommendation readiness. Do not block the full directory on missing official facts, or count directory leads toward verified recommendation coverage.

## Verification

```powershell
.\.venv\Scripts\python.exe -m pytest -q --tb=short
.\.venv\Scripts\python.exe -m scripts.verify_directory
```

On the public app, select **Browse all 83 programs**. Expect 83 / 20 / 63 within the directory. Search `a-minus-duke-ece` and inspect the minimum-only tuition label; compare it with an unreviewed entry. Select **Source-reported halt** and expect four entries. Unknown prices must remain unknown. Returning to the applicant workflow retains the current connection's profile; adding directory entries does not establish formal recommendation readiness.
