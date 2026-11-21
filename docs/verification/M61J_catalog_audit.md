# M6.1 catalog coverage audit

Audit date: 2026-11-21 · Target intake: 2027-fall · Snapshot mode · Model/network requests: 0/0

Reviewed catalog: **20 programs / 145 sources**. Verified computable tuition: **12**. Complete reviewed eligibility: **7**.
Of these tuition upper bounds, **8** have two-sided estimates and **4** are conservative ceilings only. A ceiling is not a quoted bill; a budget below it remains unknown rather than automatically failing.
Verified tuition minimum only: **1**. These bounds may exclude insufficient published-rate budgets but never establish affordability.
An `english_minimum` rule supports score-floor screening only. Meeting that floor leaves English eligibility unknown until the complete applicable policy is verified.
For the fixed fictional profile, **1** program has eligibility, goal and tier evidence for formal output. This is a test scenario, not a quality score.

## Existing programs

| Program / campus | Verified tuition upper USD | Reference hard checks | Tier evidence for reference profile | Catalog reviews still needed |
| --- | ---: | --- | --- | --- |
| Carnegie Mellon University — MCDS, Pittsburgh | 97200 | unknown | Reach | english |
| Carnegie Mellon University — MS, Pittsburgh | 92265 | unknown | None | intake, english, deadline, admission_evidence |
| Carnegie Mellon University — MSAII, Pittsburgh | 137400 | pass | Lottery | No required gap for this profile |
| Cornell University — MEng, Ithaca | 73946 | unknown | None | gpa, english, deadline, remaining_eligibility, admission_evidence |
| Duke University — MS, Durham | Unknown | unknown | None | english, prerequisites, degree, tuition, remaining_eligibility, admission_evidence |
| Georgia Institute of Technology — MS, Atlanta | Unknown | unknown | None | intake, gpa, english, prerequisites, tuition, deadline, remaining_eligibility, admission_evidence |
| North Carolina State University — MCS, Raleigh | 67983 | unknown | None | intake, gpa, english, prerequisites, degree, gre, deadline, remaining_eligibility, goal_features, admission_evidence |
| Northeastern University — MS, Boston | 61504 | unknown | None | intake, gpa, english, prerequisites, degree, deadline, remaining_eligibility, goal_features, admission_evidence |
| New York University — MS, Brooklyn | 78780 | unknown | None | gpa, admission_evidence |
| Rice University — MCS, Houston | Unknown | unknown | None | gpa, english, prerequisites, degree, tuition, remaining_eligibility, goal_features, admission_evidence |
| Texas A&M University — MCS, College Station | Unknown | unknown | None | intake, gpa, english, prerequisites, tuition, deadline, remaining_eligibility, admission_evidence |
| University of California, Irvine — MCS, Irvine | 63500 | pass | None | admission_evidence |
| University of California San Diego — MS, La Jolla | Unknown | unknown | None | gpa, english, prerequisites, tuition, remaining_eligibility, admission_evidence |
| University of Illinois Urbana-Champaign — MCS, Urbana-Champaign | Unknown | unknown | None | gpa, tuition, deadline, remaining_eligibility, goal_features, admission_evidence |
| University of Illinois Urbana-Champaign — MEng, Urbana-Champaign | 60666 | unknown | None | gpa, prerequisites, remaining_eligibility, admission_evidence |
| University of Massachusetts Amherst — MS, Amherst | Unknown | unknown | None | gpa, english, prerequisites, tuition, remaining_eligibility, goal_features, admission_evidence |
| University of Southern California — MS, Los Angeles | 87744 | unknown | None | intake, gpa, english, prerequisites, deadline, remaining_eligibility, goal_features, admission_evidence |
| University of Washington — MSECE, Seattle | 50850 | unknown | None | goal_features, admission_evidence |
| University of Washington Tacoma — MS, Tacoma | Unknown | unknown | None | tuition, admission_evidence |
| University of Wisconsin-Madison — MS, Madison | 45102.00 | unknown | None | remaining_eligibility, admission_evidence |

## Bound evidence versus usable rules

| Field group | Bound evidence / programs | Usable rule / programs |
| --- | ---: | ---: |
| identity | 20 | 20 |
| intake | 14 | 14 |
| gpa | 14 | 8 |
| english | 8 | 8 |
| english_minimum | 5 | 5 |
| prerequisites | 11 | 10 |
| degree | 16 | 16 |
| gre | 19 | 19 |
| credits | 16 | 16 |
| tuition | 15 | 12 |
| deadline | 12 | 12 |
| remaining_eligibility | 10 | 7 |
| goal_features | 13 | 13 |
| admission_evidence | 2 | 2 |

A bound tuition page with no rate is not computable tuition. A recommended GPA is not a hard minimum. Applicant GPA scope/scale issues are listed separately from catalog gaps. Future published rates are estimates, with living expenses excluded.

## Repair existing records first

- Priority 1: `cmu-mcds-pittsburgh` — english.
- Priority 2: `duke-ms-ece-durham` — english, prerequisites, degree, tuition, remaining_eligibility, admission_evidence.
- Priority 2: `gatech-mscs-atlanta` — intake, gpa, english, prerequisites, tuition, deadline, remaining_eligibility, admission_evidence.
- Priority 2: `rice-mcs-houston` — gpa, english, prerequisites, degree, tuition, remaining_eligibility, goal_features, admission_evidence.
- Priority 2: `tamu-mcs-college-station` — intake, gpa, english, prerequisites, tuition, deadline, remaining_eligibility, admission_evidence.
- Priority 2: `ucsd-ms-cs-la-jolla` — gpa, english, prerequisites, tuition, remaining_eligibility, admission_evidence.
- Priority 2: `uiuc-mcs-urbana` — gpa, tuition, deadline, remaining_eligibility, goal_features, admission_evidence.
- Priority 2: `umass-mscs-amherst` — gpa, english, prerequisites, tuition, remaining_eligibility, goal_features, admission_evidence.
- Priority 2: `uw-mscss-tacoma` — tuition, admission_evidence.
- Priority 3: `cmu-ms-ece-pittsburgh` — intake, english, deadline, admission_evidence.
- Priority 3: `cornell-meng-cs-ithaca` — gpa, english, deadline, remaining_eligibility, admission_evidence.
- Priority 3: `ncsu-mcs-raleigh` — intake, gpa, english, prerequisites, degree, gre, deadline, remaining_eligibility, goal_features, admission_evidence.
- Priority 3: `neu-mscs-boston` — intake, gpa, english, prerequisites, degree, deadline, remaining_eligibility, goal_features, admission_evidence.
- Priority 3: `nyu-mscs-tandon-brooklyn` — gpa, admission_evidence.
- Priority 3: `uci-mcs-irvine` — admission_evidence.
- Priority 3: `uiuc-meng-ece-urbana` — gpa, prerequisites, remaining_eligibility, admission_evidence.
- Priority 3: `usc-mscs-general-los-angeles` — intake, gpa, english, prerequisites, deadline, remaining_eligibility, goal_features, admission_evidence.
- Priority 3: `uw-ece-msece-pmp-seattle` — goal_features, admission_evidence.
- Priority 3: `wisc-ms-cs-professional-madison` — remaining_eligibility, admission_evidence.

## Applicant comparison issues

- `cornell-meng-cs-ithaca`: `COURSEWORK_NOT_PROVIDED` — Required coursework or skills have not been fully specified.
- `uw-ece-msece-pmp-seattle`: `GPA_SCOPE_MISMATCH` — The GPA calculation scopes differ, such as overall GPA versus the last 60 semester credits.
- `uw-mscss-tacoma`: `COURSEWORK_NOT_PROVIDED` — Required coursework or skills have not been fully specified.
- `wisc-ms-cs-professional-madison`: `GPA_SCOPE_MISMATCH` — The GPA calculation scopes differ, such as overall GPA versus the last 60 semester credits.

## Candidate screening

Pinned upstream: `a60f321365c0f00594e4d593de6f0383428bd59d`. 83 candidate leads; 4 source-reported halt flags. These flags require official review.
Screening counts: `{'already_linked_identity': 20, 'halt_report_needs_official_check': 4, 'not_selected': 59}`. Candidate recommendation eligibility remains **0**.

## First expansion batch: research queue only

| Order | Proposed degree / campus | Discipline | Official source | Scope still to resolve |
| ---: | --- | --- | --- | --- |

Research-queue entries do not establish numerical requirements. Imported facts are restricted to the separately captured, hashed and field-bound official evidence in the selected seed. Missing eligibility and admission-tier evidence remains open.

Target expanded catalog: 20–25 programs. Current audited count remains 20; the full M6 data gate is **not met**.

## Provenance and reproducibility

Catalog semantic SHA-256: `8304cb75ddbc4c5453841745290d8b9bc32d99d52c09ea1b352ce981608b4478`.
Candidate upstream SHA-256: `793b4685a323229b99ec39783ca0bb388c2870551e9ee05b6b66b357a31d4ffb`.
Candidate index attribution: [CS Grad contributors](https://csgrad.com/), [CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/). See `data/review/README.md` for scope and changes.

This report uses no LLM and no web connection. The manual research notes are separate inputs. It does not modify either SQLite database or the reviewed catalog. Formal benchmark tasks and scores have not been created by this audit.
