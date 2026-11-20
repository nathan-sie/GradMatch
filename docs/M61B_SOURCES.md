# M6.1b first official capture batch

Reviewed 2026-11-20. Active seed: `data/catalog/m61b_seed.json`, containing 12 scoped programs and 43 source records. The previous 10-program seed and its 30 source objects/snapshot files are preserved. This batch adds 13 field-bound records, two new program identities, and a review of all five incomplete pricing bases. It does not establish complete eligibility or planning-tier evidence for either new program.

Actual response URLs, retrieval timestamps, response SHA-256 values, status codes and redirect chains are in `data/review/m61b_capture_receipts.json`. Short versioned snapshots are under `data/snapshots/`; complete responses remain private development material in ignored `work/m61b_research/`. A 404 legacy MCDS response and an empty HTTP 202 Illinois catalog response are recorded as failures and never imported as verified source evidence. Search excerpts are not substitutes for captured responses.

## MCDS repair

The [currently linked AY26-27 handbook](https://www.lti.cs.cmu.edu/academics/masters-programs/files/mcds-ay26-27-masters-student-handbook.pdf), printed page 3, supports bachelor-level entry without requiring a CS major. Its mathematical/programming aptitude statements are recorded as preparation, not invented mandatory course requirements. The document's effective period and possible future policy changes are stated explicitly.

The [current Fall 2027 program instructions](https://www.lti.cs.cmu.edu/academics/masters-programs/mcds.html) and [SCS English policy](https://www.cs.cmu.edu/education/graduate-admissions) establish testing and recency requirements, including MCDS's exclusion from the extended U.S.-degree validity exception. Neither retrieved page establishes a numerical hard English minimum for this record. The legacy apply URL redirects to a 404. Old cached minima and a different program's FAQ are not carried into the record. English, complete prerequisite review and remaining eligibility therefore stay unknown; the existing cohort-based Reach support alone cannot authorize a recommendation.

## Five pricing reviews

| Program | Captured official basis | Decision |
| --- | --- | --- |
| NC State MCS, Raleigh | [MCS-specific nonresident table](https://studentservices.ncsu.edu/finances/tuition-and-fees/tuition-and-fee-rates/graduate-students/) distinguishes base tuition, increments, required fees and the 9+ credit cap. | Keep unknown: a verified complete 31-credit term/billing plan is absent. A flat per-credit product would hide the cap. |
| Rice MCS, Houston | [Professional engineering rates](https://bursar.rice.edu/tuition_fee_rates/graduate-programs/engineering) and [degree requirements](https://ga.rice.edu/programs-study/departments-programs/engineering/computer-science/computer-science-mcs/) distinguish tuition from fees and describe normal duration. | Keep unknown: normal duration is not an invariant required full-program billing count. Online rates are excluded. |
| UCI MCS, Irvine | [Registrar's 2026-27 PDF](https://www.reg.uci.edu/fees/2026-2027/compsci.pdf), page 1, separates program and campus charges across the Fall 2026 cohort's five quarters. | Keep unknown: the Fall 2027 continuation row does not price new Fall 2027 entrants; annual totals are not full-program tuition. |
| UMass Amherst MSCS | [CICS costs](https://www.cics.umass.edu/academics/ms-computer-science-campus/ms-campus-tuition-and-fees) and [Bursar enrollment tiers](https://www.umass.edu/bursar/tuition/graduate-tuition) do not reconcile to one verified 30-credit tuition-only plan. | Keep unknown: combined fees, enrollment-dependent charges and the applicable full-program period remain unresolved. |
| Illinois on-campus MCS | [Fall 2027 self-supporting policy](https://siebelschool.illinois.edu/academics/graduate/professional-mcs/tuition-fees) and [calculator](https://cost.illinois.edu/) are captured. | Keep unknown: the captured start-term selector stops at Summer 2027, before the funding transition for new entrants. |

These reviews improve provenance and explain unknowns; they do not add five computable prices. The catalog still has five verified computable tuition estimates. Structured review decisions are in `data/review/m61b_field_reviews.json`; explanatory notes are source-bound in the active seed.

## First two expansion records

**Illinois ECE MEng, on-campus Urbana-Champaign:** the [program page](https://ece.illinois.edu/academics/grad/meng-campus) verifies identity, 32 credits and professional goals. The [captured admissions instructions](https://ece.illinois.edu/admissions/graduate/meng-degree) support the Fall 2027 intake, May 1 deadline and optional GRE. A numerical GPA threshold with no verified calculation scope stays non-comparable, even for a high overall GPA. Related-field equivalency, English minima, prerequisites, applicable tuition and permitted tier evidence remain incomplete. No online degree's deadline or rate is substituted.

**UW Tacoma MSCSS:** the [program page](https://www.tacoma.uw.edu/set/programs/graduate/mscss) establishes a separate campus/degree, Fall 2027 and the final deadline subject to available space. It has several degree pathways with different quarter-credit totals; no single credit count or tuition path is selected. Individual review of deficient preparation/below-threshold GPA stays conservative. The university's [Policy 3.2](https://grad.uw.edu/policies/3-2-graduate-school-english-language-proficiency-requirements/) supports the represented IELTS minimum/recommended distinction; other English-evidence paths need further program-specific review. Additional preparation topics are available in the English applicant form. Complete eligibility and tier evidence remain absent.

The original 83-row community index remains unchanged and non-recommendable. The new records use independently captured official evidence; tracker identities only retain provenance. Eight other first-batch leads remain queued. No applicant datapoints or unsupported admission probabilities are imported.
