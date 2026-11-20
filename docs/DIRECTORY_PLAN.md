# Coverage-first program data plan

Approved direction on 2026-11-20: expose all 83 imported program leads first, then concentrate official-field review on 20–30 priority programs. This replaces the earlier sequence of completing a few programs before exposing the next batch. The 210 main tasks, 50 safety prompts and shared evaluation requirements remain separate work.

## Delivered exploration layer

- All 83 pinned tracker identities are searchable by university, program, campus and keyword. Filters distinguish official snapshots, pending review and four source-reported halt flags.
- Sixteen exact, reviewed identity links enrich their own entries with existing official facts. Other programs at the same university do not inherit those rules or prices. Missing GPA, English, tuition, intake, deadlines and admission evidence remain explicit.
- Compare up to four entries and download a comparison with attribution, snapshot date and evidence context. Comparison selections survive changes to search filters.
- A separate content-addressed SQLite directory is rebuilt on clean hosts and after cache loss. Runtime reads use read-only connections. Official recommendation records, provenance and historical source snapshots remain separate and unchanged.
- Browsing needs no API key or model call. Directory membership supplies no admission tier or applicant eligibility decision. Doctoral-route leads and community halt reports remain visible with their original review flags.

The official data remains 16 program records / 62 sources / seven computable tuition estimates. Coverage labels refer to the pinned Fall 2027 reference intake and official review date, not a fresh check of all websites. Complete admission-tier support is not promised for every directory entry.

## Next review batches

Start with the 16 linked identities plus the four queued tracks: Duke ECE MS, CMU Pittsburgh ECE MS, Georgia Tech on-campus MSCS and UCSD CS MS. This gives an initial 20-program focus set. Expand toward 30 after the first coverage improvement; selection is based on project coverage needs, not community rankings.

Handle 10–15 programs per batch. Capture shared university policies once where the evidence applies to each exact degree, campus, applicant category and period. Apply the same validation to extracted fields; retain exceptions and unknowns. Prioritize complete tuition formulas, GPA/English/degree/GRE/prerequisite requirements, intake and deadlines. Gather goal and admissible admission evidence alongside these fields, with applicant tiers assessed separately.

Run focused checks during each batch, then one regression suite and one release at its end. Publish an updated coverage table distinguishing directory count, official records, usable fields and applicant-specific recommendation readiness. Do not block the full directory on missing official facts, or count directory leads toward verified recommendation coverage.

## Verification

```powershell
.\.venv\Scripts\python.exe -m pytest -q --tb=short
.\.venv\Scripts\python.exe -m scripts.verify_directory
```

On the public app, select **Browse all 83 programs**. Expect 83 / 16 / 67 within the directory. Search `nyu brooklyn`, compare NYU Tandon with an unreviewed entry, then select **Source-reported halt** and expect four entries. Unknown prices must remain unknown. Returning to the applicant workflow retains the current connection's profile; adding directory entries does not expand the formal recommendation pool.
