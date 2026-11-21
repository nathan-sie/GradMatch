# M6.1 catalog coverage audit

Audit date: 2026-11-20 · Target intake: 2027-fall · Snapshot mode · Model/network requests: 0/0

Reviewed catalog: **16 programs / 82 sources**. Verified computable tuition: **7**. Complete reviewed eligibility: **1**.
For the fixed fictional profile, **1** program has eligibility, goal and tier evidence for formal output. This is a test scenario, not a quality score.

## Existing programs

| Program / campus | Verified tuition upper USD | Reference hard checks | Tier evidence for reference profile | Catalog reviews still needed |
| --- | ---: | --- | --- | --- |
| Carnegie Mellon University — MCDS, Pittsburgh | 97200 | unknown | Reach | english, prerequisites, remaining_eligibility |
| Carnegie Mellon University — MSAII, Pittsburgh | 137400 | pass | Lottery | No required gap for this profile |
| Cornell University — MEng, Ithaca | 73946 | unknown | None | gpa, english, prerequisites, deadline, remaining_eligibility, admission_evidence |
| North Carolina State University — MCS, Raleigh | Unknown | unknown | None | intake, gpa, english, prerequisites, degree, gre, tuition, deadline, remaining_eligibility, goal_features, admission_evidence |
| Northeastern University — MS, Boston | 61504 | unknown | None | intake, gpa, english, prerequisites, degree, deadline, remaining_eligibility, goal_features, admission_evidence |
| New York University — MS, Brooklyn | 78780 | unknown | None | intake, gpa, prerequisites, deadline, remaining_eligibility, admission_evidence |
| Rice University — MCS, Houston | Unknown | unknown | None | gpa, english, prerequisites, degree, tuition, remaining_eligibility, goal_features, admission_evidence |
| Texas A&M University — MCS, College Station | Unknown | unknown | None | intake, gpa, english, prerequisites, tuition, deadline, remaining_eligibility, admission_evidence |
| University of California, Irvine — MCS, Irvine | Unknown | unknown | None | gpa, prerequisites, tuition, remaining_eligibility, goal_features, admission_evidence |
| University of Illinois Urbana-Champaign — MCS, Urbana-Champaign | Unknown | unknown | None | gpa, english, tuition, deadline, remaining_eligibility, goal_features, admission_evidence |
| University of Illinois Urbana-Champaign — MEng, Urbana-Champaign | Unknown | unknown | None | gpa, english, prerequisites, tuition, remaining_eligibility, admission_evidence |
| University of Massachusetts Amherst — MS, Amherst | Unknown | unknown | None | gpa, english, prerequisites, degree, tuition, remaining_eligibility, goal_features, admission_evidence |
| University of Southern California — MS, Los Angeles | 87744 | unknown | None | intake, gpa, english, prerequisites, deadline, remaining_eligibility, goal_features, admission_evidence |
| University of Washington — MSECE, Seattle | 50850 | unknown | None | remaining_eligibility, goal_features, admission_evidence |
| University of Washington Tacoma — MS, Tacoma | Unknown | unknown | None | prerequisites, tuition, remaining_eligibility, admission_evidence |
| University of Wisconsin-Madison — MS, Madison | Unknown | unknown | None | intake, english, prerequisites, tuition, deadline, remaining_eligibility, admission_evidence |

## Bound evidence versus usable rules

| Field group | Bound evidence / programs | Usable rule / programs |
| --- | ---: | ---: |
| identity | 16 | 16 |
| intake | 10 | 10 |
| gpa | 9 | 5 |
| english | 5 | 5 |
| prerequisites | 10 | 3 |
| degree | 12 | 12 |
| gre | 15 | 15 |
| credits | 12 | 12 |
| tuition | 11 | 7 |
| deadline | 8 | 8 |
| remaining_eligibility | 6 | 1 |
| goal_features | 8 | 8 |
| admission_evidence | 2 | 2 |

A bound tuition page with no rate is not computable tuition. A recommended GPA is not a hard minimum. Applicant GPA scope/scale issues are listed separately from catalog gaps. Future published rates are estimates, with living expenses excluded.

## Repair existing records first

- Priority 1: `cmu-mcds-pittsburgh` — english, prerequisites, remaining_eligibility.
- Priority 2: `ncsu-mcs-raleigh` — intake, gpa, english, prerequisites, degree, gre, tuition, deadline, remaining_eligibility, goal_features, admission_evidence.
- Priority 2: `rice-mcs-houston` — gpa, english, prerequisites, degree, tuition, remaining_eligibility, goal_features, admission_evidence.
- Priority 2: `tamu-mcs-college-station` — intake, gpa, english, prerequisites, tuition, deadline, remaining_eligibility, admission_evidence.
- Priority 2: `uci-mcs-irvine` — gpa, prerequisites, tuition, remaining_eligibility, goal_features, admission_evidence.
- Priority 2: `uiuc-mcs-urbana` — gpa, english, tuition, deadline, remaining_eligibility, goal_features, admission_evidence.
- Priority 2: `uiuc-meng-ece-urbana` — gpa, english, prerequisites, tuition, remaining_eligibility, admission_evidence.
- Priority 2: `umass-mscs-amherst` — gpa, english, prerequisites, degree, tuition, remaining_eligibility, goal_features, admission_evidence.
- Priority 2: `uw-mscss-tacoma` — prerequisites, tuition, remaining_eligibility, admission_evidence.
- Priority 2: `wisc-ms-cs-professional-madison` — intake, english, prerequisites, tuition, deadline, remaining_eligibility, admission_evidence.
- Priority 3: `cornell-meng-cs-ithaca` — gpa, english, prerequisites, deadline, remaining_eligibility, admission_evidence.
- Priority 3: `neu-mscs-boston` — intake, gpa, english, prerequisites, degree, deadline, remaining_eligibility, goal_features, admission_evidence.
- Priority 3: `nyu-mscs-tandon-brooklyn` — intake, gpa, prerequisites, deadline, remaining_eligibility, admission_evidence.
- Priority 3: `usc-mscs-general-los-angeles` — intake, gpa, english, prerequisites, deadline, remaining_eligibility, goal_features, admission_evidence.
- Priority 3: `uw-ece-msece-pmp-seattle` — remaining_eligibility, goal_features, admission_evidence.

## Applicant comparison issues

- `uw-ece-msece-pmp-seattle`: `GPA_SCOPE_MISMATCH` — The GPA calculation scopes differ, such as overall GPA versus the last 60 semester credits.
- `wisc-ms-cs-professional-madison`: `GPA_SCOPE_MISMATCH` — The GPA calculation scopes differ, such as overall GPA versus the last 60 semester credits.

## Candidate screening

Pinned upstream: `a60f321365c0f00594e4d593de6f0383428bd59d`. 83 candidate leads; 4 source-reported halt flags. These flags require official review.
Screening counts: `{'already_linked_identity': 16, 'first_batch_review': 4, 'halt_report_needs_official_check': 4, 'not_selected': 59}`. Candidate recommendation eligibility remains **0**.

## First expansion batch: research queue only

| Order | Proposed degree / campus | Discipline | Official source | Scope still to resolve |
| ---: | --- | --- | --- | --- |
| 5 | Duke University — MS Electrical and Computer Engineering, Durham | ECE | [Program page](https://ece.duke.edu/academics/masters/) | Landing page covers both MS and MEng. Review the MS-specific requirements, campus and billing before import. |
| 6 | Carnegie Mellon University — MS Electrical and Computer Engineering, Pittsburgh | ECE | [Program page](https://www.ece.cmu.edu/academics/ms-ece/index.html) | Page covers Pittsburgh and Silicon Valley. Pittsburgh handbook and track-specific scope must be checked before importing tuition. |
| 7 | Georgia Institute of Technology — MS Computer Science, on-campus, Atlanta | CS | [Program page](https://www.cc.gatech.edu/degree-programs/master-science-computer-science) | Separate from OMSCS; confirm international full-time on-campus intake, options and billing. |
| 8 | University of California San Diego — MS Computer Science major, La Jolla | CS | [Program page](https://cse.ucsd.edu/graduate/degree-programs/ms-program) | Page covers CS and CE majors and three plans. Confirm the CS major/pathway before importing numerical rules. |

Program pages were checked manually for identity leads; no new numerical fact has been imported into the app. Next, capture applicable official requirements/tuition pages with response hashes and exact field bindings, resolve track/campus ambiguities, then import a separately validated seed.

Target expanded catalog: 40–60 programs. Current audited count remains 16; the full M6 data gate is **not met**.

## Provenance and reproducibility

Catalog semantic SHA-256: `169fdbd6a1025e00dcdea54e3d62be2ce4dbb1b9c49adb5508e207fb95097565`.
Candidate upstream SHA-256: `793b4685a323229b99ec39783ca0bb388c2870551e9ee05b6b66b357a31d4ffb`.
Candidate index attribution: [CS Grad contributors](https://csgrad.com/), [CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/). See `data/review/README.md` for scope and changes.

This report uses no LLM and no web connection. The manual research notes are separate inputs. It does not modify either SQLite database or the reviewed catalog. Formal benchmark tasks and scores have not been created by this audit.
