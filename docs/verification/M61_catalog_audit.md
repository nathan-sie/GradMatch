# M6.1 catalog coverage audit

Audit date: 2026-11-19 · Target intake: 2027-fall · Snapshot mode · Model/network requests: 0/0

Reviewed catalog: **10 programs / 30 sources**. Verified computable tuition: **5**. Complete reviewed eligibility: **1**.
For the fixed fictional profile, **1** program has eligibility, goal and tier evidence for formal output. This is a test scenario, not a quality score.

## Existing programs

| Program / campus | Verified tuition upper USD | Reference hard checks | Tier evidence for reference profile | Catalog reviews still needed |
| --- | ---: | --- | --- | --- |
| Carnegie Mellon University — MCDS, Pittsburgh | 97200 | unknown | Reach | english, prerequisites, degree, remaining_eligibility |
| Carnegie Mellon University — MSAII, Pittsburgh | 137400 | pass | Lottery | No required gap for this profile |
| North Carolina State University — MCS, Raleigh | Unknown | unknown | None | intake, gpa, english, prerequisites, degree, gre, tuition, deadline, remaining_eligibility, goal_features, admission_evidence |
| Northeastern University — MS, Boston | 61504 | unknown | None | intake, gpa, english, prerequisites, degree, gre, deadline, remaining_eligibility, goal_features, admission_evidence |
| Rice University — MCS, Houston | Unknown | unknown | None | gpa, english, prerequisites, degree, gre, tuition, remaining_eligibility, goal_features, admission_evidence |
| University of California, Irvine — MCS, Irvine | Unknown | unknown | None | gpa, prerequisites, degree, gre, tuition, remaining_eligibility, goal_features, admission_evidence |
| University of Illinois Urbana-Champaign — MCS, Urbana-Champaign | Unknown | unknown | None | gpa, english, degree, gre, tuition, deadline, remaining_eligibility, goal_features, admission_evidence |
| University of Massachusetts Amherst — MS, Amherst | Unknown | unknown | None | gpa, english, prerequisites, degree, gre, tuition, remaining_eligibility, goal_features, admission_evidence |
| University of Southern California — MS, Los Angeles | 87744 | unknown | None | intake, gpa, english, prerequisites, degree, gre, deadline, remaining_eligibility, goal_features, admission_evidence |
| University of Washington — MSECE, Seattle | 50850 | unknown | None | degree, gre, remaining_eligibility, goal_features, admission_evidence |

## Bound evidence versus usable rules

| Field group | Bound evidence / programs | Usable rule / programs |
| --- | ---: | ---: |
| identity | 10 | 10 |
| intake | 7 | 7 |
| gpa | 5 | 3 |
| english | 3 | 3 |
| prerequisites | 5 | 3 |
| degree | 1 | 1 |
| gre | 2 | 2 |
| credits | 7 | 7 |
| tuition | 8 | 5 |
| deadline | 6 | 6 |
| remaining_eligibility | 2 | 1 |
| goal_features | 2 | 2 |
| admission_evidence | 2 | 2 |

A bound tuition page with no rate is not computable tuition. A recommended GPA is not a hard minimum. Applicant GPA scope/scale issues are listed separately from catalog gaps. Future published rates are estimates, with living expenses excluded.

## Repair existing records first

- Priority 1: `cmu-mcds-pittsburgh` — english, prerequisites, degree, remaining_eligibility.
- Priority 2: `ncsu-mcs-raleigh` — intake, gpa, english, prerequisites, degree, gre, tuition, deadline, remaining_eligibility, goal_features, admission_evidence.
- Priority 2: `rice-mcs-houston` — gpa, english, prerequisites, degree, gre, tuition, remaining_eligibility, goal_features, admission_evidence.
- Priority 2: `uci-mcs-irvine` — gpa, prerequisites, degree, gre, tuition, remaining_eligibility, goal_features, admission_evidence.
- Priority 2: `uiuc-mcs-urbana` — gpa, english, degree, gre, tuition, deadline, remaining_eligibility, goal_features, admission_evidence.
- Priority 2: `umass-mscs-amherst` — gpa, english, prerequisites, degree, gre, tuition, remaining_eligibility, goal_features, admission_evidence.
- Priority 3: `neu-mscs-boston` — intake, gpa, english, prerequisites, degree, gre, deadline, remaining_eligibility, goal_features, admission_evidence.
- Priority 3: `usc-mscs-general-los-angeles` — intake, gpa, english, prerequisites, degree, gre, deadline, remaining_eligibility, goal_features, admission_evidence.
- Priority 3: `uw-ece-msece-pmp-seattle` — degree, gre, remaining_eligibility, goal_features, admission_evidence.

## Applicant comparison issues

- `uw-ece-msece-pmp-seattle`: `GPA_SCOPE_MISMATCH` — The GPA calculation scopes differ, such as overall GPA versus the last 60 semester credits.

## Candidate screening

Pinned upstream: `a60f321365c0f00594e4d593de6f0383428bd59d`. 83 candidate leads; 4 source-reported halt flags. These flags require official review.
Screening counts: `{'already_linked_identity': 10, 'first_batch_review': 10, 'halt_report_needs_official_check': 4, 'not_selected': 59}`. Candidate recommendation eligibility remains **0**.

## First expansion batch: research queue only

| Order | Proposed degree / campus | Discipline | Official source | Scope still to resolve |
| ---: | --- | --- | --- | --- |
| 1 | University of Illinois Urbana-Champaign — MEng ECE, on-campus, Urbana | ECE | [Program page](https://ece.illinois.edu/academics/grad/meng-campus) | On-campus MEng is distinct from the online degree and MS research program. |
| 2 | University of Washington Tacoma — MS Computer Science & Systems, Tacoma | CS | [Program page](https://www.tacoma.uw.edu/set/programs/graduate/mscss) | Separate campus and degree from UW Seattle ECE PMP. Multiple degree pathways need distinct credit/tuition treatment. |
| 3 | Texas A&M University — Master of Computer Science, College Station | CS | [Program page](https://engineering.tamu.edu/cse/academics/degrees/graduate/mcs.html) | Non-thesis MCS is distinct from thesis MSCS. The 30-credit degree total is not a tuition quote. |
| 4 | New York University, Tandon — MS Computer Science, Brooklyn | CS | [Program page](https://engineering.nyu.edu/academics/programs/computer-science-ms) | Use Tandon rules and tuition; do not merge with Courant or the Data Science MS. |
| 5 | Duke University — MS Electrical and Computer Engineering, Durham | ECE | [Program page](https://ece.duke.edu/academics/masters/) | Landing page covers both MS and MEng. Review the MS-specific requirements, campus and billing before import. |
| 6 | Carnegie Mellon University — MS Electrical and Computer Engineering, Pittsburgh | ECE | [Program page](https://www.ece.cmu.edu/academics/ms-ece/index.html) | Page covers Pittsburgh and Silicon Valley. Pittsburgh handbook and track-specific scope must be checked before importing tuition. |
| 7 | Georgia Institute of Technology — MS Computer Science, on-campus, Atlanta | CS | [Program page](https://www.cc.gatech.edu/degree-programs/master-science-computer-science) | Separate from OMSCS; confirm international full-time on-campus intake, options and billing. |
| 8 | University of California San Diego — MS Computer Science major, La Jolla | CS | [Program page](https://cse.ucsd.edu/graduate/degree-programs/ms-program) | Page covers CS and CE majors and three plans. Confirm the CS major/pathway before importing numerical rules. |
| 9 | University of Wisconsin-Madison — MS Computer Sciences, Professional, Madison | CS | [Program page](https://www.cs.wisc.edu/grad/programs/pmp/) | Separate from traditional MS/PhD. Review program-specific tuition, admissions and current internship-policy wording before goal-fit claims. |
| 10 | Cornell University — MEng Computer Science, Ithaca | CS | [Program page](https://www.cs.cornell.edu/masters-engineering-computer-science) | Separate from Cornell Tech in New York City; use the Ithaca MEng rules. |

Program pages were checked manually for identity leads; no new numerical fact has been imported into the app. Next, capture applicable official requirements/tuition pages with response hashes and exact field bindings, resolve track/campus ambiguities, then import a separately validated seed.

Target expanded catalog: 40–60 programs. Current audited count remains 10; the full M6 data gate is **not met**.

## Provenance and reproducibility

Catalog semantic SHA-256: `7d9cad506f56167c91480536f11c1813770cb5b44718f89e85f8f2e70f9d3592`.
Candidate upstream SHA-256: `793b4685a323229b99ec39783ca0bb388c2870551e9ee05b6b66b357a31d4ffb`.
Candidate index attribution: [CS Grad contributors](https://csgrad.com/), [CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/). See `data/review/README.md` for scope and changes.

This report uses no LLM and no web connection. The manual research notes are separate inputs. It does not modify either SQLite database or the reviewed catalog. Formal benchmark tasks and scores have not been created by this audit.
