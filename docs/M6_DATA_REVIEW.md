# M6 data work and verification gates

M5 user page acceptance is complete: the user-provided trace demonstrated initial execution, two budget-triggered revisions, citation rejection and a completed recovery plan. No full profile or extra user-test usage is published.

## M6.1a — coverage audit and expansion screening

This first checkpoint provides executable audit code, field coverage, a repair queue, provenance checks and ten expansion leads with official-page research notes. It does not import new official facts. The formal catalog remains 10 programs / 30 sources, below the planned 40–60 range. The final-project task set and benchmark are later M6/M7 work.

The audit uses the shared evidence bindings, tuition calculator, eligibility checks and tier validator. It distinguishes:

- a source ID being present versus exact values being supported for the chosen intake;
- a published rate versus a complete, reproducible full-program tuition estimate;
- a recommended GPA versus a hard minimum or explicit no-minimum policy;
- applicant scale/scope mismatches versus missing official rules;
- aggregate cohort evidence versus complete eligibility and goal-fit evidence;
- candidate identity leads versus imported, source-bound program records.

The reference applicant is the existing fictional tiering example, with Fall 2027 intake and a USD 140,000 tuition-only published-rate budget. Readiness counts apply to that explicit scenario. They do not predict admission or establish eligibility for all applicants. No Safer rationale is invented for the audit.

Run `python -m scripts.verify_m61` for regression tests, an audit with network/model transports blocked, candidate count/identity checks and before/after SQLite hashes. The candidate index is bundled, so the audit works without the ignored original import files. If those local files are available, it additionally reconciles all 83 rows and the pinned import manifest.

## M6.1b — repair and first verified expansion batch

The first capture/import checkpoint on 2026-11-20 uses `m61b_seed.json`: 12 programs / 43 sources. Illinois on-campus ECE MEng and UW Tacoma MSCSS have scoped official records with explicit unknowns. MCDS's bachelor-level policy is now source-bound; its English minimum, complete prerequisite review and remaining eligibility are unresolved. All five incomplete pricing bases were researched and retained as unknown for documented cohort/component/period reasons. Computable tuition remains five. See [source decisions](M61B_SOURCES.md) and [verification checkpoint](verification/M61B.md). This is a completed first batch, not completion of all M6.1b repairs or the 40–60 program gate.

Continue MCDS's missing English, prerequisite and remaining-eligibility review: its degree policy is now bound, and it already has a computable tuition estimate, professional-goal evidence and usable cohort counts, but cannot be formally recommended while eligibility remains unknown. Resolve the five reviewed but still incomplete tuition bases. No recommended GPA becomes a hard threshold by assumption.

The initial ten-lead queue supplied the first two scoped records, Illinois ECE MEng and UW Tacoma MSCSS. Eight leads remain: Texas A&M MCS, NYU Tandon MSCS, Duke ECE MS, CMU ECE MS, Georgia Tech on-campus MSCS, UCSD CS MS, Wisconsin professional CS MS and Cornell Ithaca CS MEng. Continue exact degree/campus/track, intake/category, eligibility, tuition, goal and tier-evidence review for both imported partial records and queued leads. Where curricula introduce new prerequisite topics or variable credit pathways, review representation in schemas/rules/UI before recording a hard check.

Exit gate: versioned official captures and field bindings validate, tuition units and time periods reconcile, unknowns remain explicit, the proposed seed survives database round-trip and all three strategies use the same data. Do not count research leads as added programs. Original snapshots and earlier verification artifacts remain preserved.

## Later M6 gates

Continue in reviewable data batches toward 40–60 distinct scoped programs. Then prepare 210 different main tasks, at least 50 safety prompts, isolated references, family-separated pilot tasks and the shared evaluation runner. Run a small real pilot to estimate calls/tokens/cost before freezing final parameters. Formal scores remain unmeasured until M7 real runs.
