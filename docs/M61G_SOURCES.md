# M6.1g source decisions

Reviewed November 20, 2026 (Pacific). This batch repairs 12 existing records using 18 new source objects. The catalog remains 20 identities; source count rises from 94 to 112. All 94 previous source objects, all 83 directory identities and the four original community halt flags are preserved.

## Tuition

- **UCI MCS:** [registrar schedule, page 1](https://www.reg.uci.edu/fees/2026-2027/compsci.pdf) lists the Fall 2026 cohort's five-quarter instructional program fee of USD 63,500. Its annual USD 50,800 covers four quarters, including summer, and omits the final fall quarter. Service, campus, insurance and other fees are separate; some later-quarter fees remain TBD. The full instructional program fee is a published-rate planning reference, not a new Fall 2027 cohort quote or a guaranteed final bill. The page was rendered and visually checked against its cohort header, both tables and footnotes. Complete tuition estimates increase from seven to eight.
- **Rice on-campus MCS:** the [general announcements tuition table](https://ga.rice.edu/graduate-students/student-services-organizations/tuition-fees-expenses/) separates professional-engineering full-time semester tuition (USD 30,720) from approved part-time pricing (USD 2,560 per credit). The [program page](https://csweb.rice.edu/academics/graduate-programs/person-master-computer-science) describes a typical three-semester pathway, which is not a guaranteed maximum. A full program-specific billing schedule remains unverified. Neither the online USD 1,700 rate nor three times a generic annual cost is substituted as the full tuition total. The direct Bursar capture returned 406; the substantive university announcements capture supplies the readable context instead.
- Duke's minimum-only USD 104,820 bound remains separate from the eight full instructional tuition estimates. A minimum never proves affordability.

## English score floors

Eight programs now carry an `english_minimum` evidence group. The corresponding `EnglishRequirement` values are score floors, not complete eligibility policies. Failing a verified floor flags the selected-test route. Meeting it always leaves English eligibility unknown unless a separate complete `english` group is verified. Exemptions are never inferred from citizenship or a degree alone. No applicant is assigned an admission outcome from these checks.

| Program | Official source | Floor and unresolved conditions |
| --- | --- | --- |
| CMU Pittsburgh ECE MS | [ECE FAQ](https://www.ece.cmu.edu/admissions/graduate-faq.html) | TOEFL 86/120 or 4.5/6 with section floors; IELTS 7 with section floors; DET 115 with literacy/comprehension/production/conversation minima. Validity and waiver handling remain pending. |
| UCSD CS MS | [Graduate Education English policy](https://www.grad.ucsd.edu/admissions/requirements/international-students/english-proficiency.html) | University floors: TOEFL 85/120 or 4.5/6, IELTS 7, DET 120. Departmental conditions, validity and exemptions remain open. |
| Georgia Tech on-campus MSCS | [department](https://www.cc.gatech.edu/ms-computer-science-admission-requirements), [institution](https://grad.gatech.edu/english-proficiency) | Apply the stricter departmental overall scores (TOEFL 100/120 or 5/6, IELTS 7.5) with institutional section minima. Both sources are required. Enrollment validity, expired-score exceptions and degree-based proof remain manual. The source group is bounded to Fall 2027. |
| Cornell Ithaca CS MEng | [professional-master English policy](https://gradschool.cornell.edu/admissions/application-steps/required-tests/english-language-proficiency-requirement-2/) | IELTS 7; TOEFL professional-master section minima, including speaking 22 on the legacy scale. Research-degree TA speaking 27 is not used. No TOEFL overall cutoff is asserted; internal total zero disables only that unpublished aggregate test. Deadline validity, field-specific rules, exemptions and 2028 changes remain open. |
| Wisconsin professional CS MS | [Graduate School requirements](https://info.grad.wisc.edu/requirements-for-admission/) | The lower conditional ranges (TOEFL 80/120 or 4.5/6, IELTS 6.5, DET 115) are used only as score floors. Standard thresholds are higher; program approval, ESLAT and enrollment validity remain required checks. A conditional-range score is never an automatic pass. |
| UMass Amherst MSCS | [international applicant policy](https://www.umass.edu/graduate/apply/international-applicants) | University floors: TOEFL 80/120 or 4/6, IELTS 6.5, DET 115. Higher program requirements, entrance validity and exemptions remain open. |
| Illinois Urbana MCS and ECE MEng | [Graduate College policy](https://grad.illinois.edu/admissions/international-applicants) | Limited-status floors: TOEFL 79/120 or 4/6, IELTS 6.5, DET 115. Full-status scores are higher. The two exact programs have separate source bindings; enrollment validity, departmental rules and exemptions remain open. |

Duke's [English instructions](https://gradschool.duke.edu/admissions/application-instructions/english-language-proficiency-test-scores/) describe generally sought scores rather than unconditional rejection thresholds. These remain readable context. MCDS's [program page](https://www.lti.cs.cmu.edu/academics/masters-programs/mcds.html) requires recent scores while the [SCS page](https://www.cs.cmu.edu/education/graduate-admissions) prints an older September 2024 cutoff. The discrepancy remains explicit; successful-applicant score ranges are not converted into hard minima.

## Other qualification fields

- Duke's [Graduate School FAQ](https://gradschool.duke.edu/admissions/admissions-faqs/) and CMU's ECE FAQ establish no hard GPA cutoff in their reviewed policies. Required GPA reporting and admission competitiveness remain separate. CMU ECE and Duke ECE MS GRE are optional for the captured Fall 2027 scope.
- Duke's [exact MS page](https://gradschool.duke.edu/academics/programs-degrees/electrical-and-computer-engineering-ms/) identifies January 16, 2027 for guaranteed review, followed by space-available review through February 25. Later submission does not guarantee places.
- UCSD's [CSE admissions page](https://cse.ucsd.edu/graduate/admissions) requires a recognized bachelor or equivalent while retaining conditional preparation review. UMass's international policy likewise requires recognized equivalent credentials, with explicit review for three-year routes. These are self-reported planning checks; universities decide equivalency.

## Provenance and limits

There were 26 public HTTP capture attempts and zero model calls. Four failures are retained (one 406 and three 404 responses). Other unused responses are listed in the machine proof; in particular, Northeastern engineering rules were not applied to a Khoury MSCS record. Seventeen distinct successful captures supply the 18 imported source objects, because the Illinois university policy has separate exact-program bindings.

Complete reviewed planning eligibility remains two, and formal evidence readiness for the fixed fictional profile remains one. The 10–15 effective-screening target and wider admission-tier evidence are still open. Historical snapshots and homework results are unchanged.
