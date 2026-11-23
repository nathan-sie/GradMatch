# UC San Diego CS75 official evidence review

The `cs75_review_seed.json` checkpoint added six source records to the CS75 external MS Comprehensive Standard route in La Jolla. The active `cs75_planning_seed.json` checkpoint adds two more. The M6.4 evaluation still names the earlier versioned seed. The initial 145 source records are preserved.

| Check | Source-backed change |
| --- | --- |
| Admission GPA | The CSE admissions page gives a 3.0 GPA or equivalent minimum. The CSE FAQ asks for overall academic standing on the original scale. The planner checks applicable overall GPAs on a 4.0 scale and leaves equivalency review to the university. |
| Preparation | The CSE degree route covers declared CS and ECE backgrounds. The FAQ lists programming, discrete math, data structures and algorithms as preparation guidance. Other backgrounds require a course-equivalency review. |
| English | The department points to GEPA score rules. Legacy TOEFL iBT 85, new TOEFL iBT 4.5 and DET 120 are bound to two-year test reporting windows. IELTS Academic 7 and PTE Academic 65 are documented for manual review. Exemptions, test delivery, and prior receipt of an expired score require confirmation. |
| Tuition | The ordinary full-time plan requires at least three quarters of residence. At the 2026–2027 published rate of USD 4,574 per quarter, the minimum is USD 13,722. The separately reported nonresident supplement is USD 5,034 per quarter where applicable, for USD 28,824 over three quarters. This is a planning minimum and excludes fees, insurance and living costs. The full-program upper bound and Fall 2027 rates remain unverified. |
| Application checklist | The catalog records the online application, transcripts, statement of purpose, three recommendations, resume or CV and applicable English proof. Duplicate advanced degrees and individual exceptions still need screening. |

The [external CSE admission page](https://cse.ucsd.edu/graduate/admissions), [CSE FAQ](https://cse.ucsd.edu/graduate/graduate-admissions-faq) and [application checklist](https://cse.ucsd.edu/graduate/cse-graduate-application-checklist) cover the application route. The [GEPA proficiency policy](https://www.grad.ucsd.edu/admissions/requirements/international-students/english-proficiency.html) and [test-score FAQ](https://grad.ucsd.edu/admissions/admission-faq/faq-test-scores.html) cover score reporting. The [CSE MS program](https://cse.ucsd.edu/graduate/degree-programs/ms-program) establishes the residency minimum and the [Registrar's rate table](https://students.ucsd.edu/finances/fees/registration/2026-27/graduate.html) establishes the published rates.

For the fictional 3.80/4 applicant, the first review reduced unknown official checks from five to two. The planning update uses the new **Previous academic graduate degree** profile field. With an explicit **None**, the remaining-eligibility check passes for the ordinary route. An unknown response or a prior or expected academic graduate degree keeps the check pending. Professional degrees are outside this duplicate-degree check. See the [CSE duplication policy](https://cse.ucsd.edu/graduate/admissions#duplication-of-degrees).

CSE reports that its average MS student completes the program within two years. The program card shows the six-quarter example at constant published rates, USD 27,444 in base tuition or USD 57,648 with the nonresident supplement. The estimate applies to six regular full-time quarters and excludes fees and living costs. The budget check continues to use the verified starting minimum and reports an unknown upper bound. See the [CSE FAQ](https://cse.ucsd.edu/graduate/graduate-admissions-faq) and the [Registrar's rate table](https://students.ucsd.edu/finances/fees/registration/2026-27/graduate.html).

The local dataset has nine independent self-reported admits that pass the initial GPA band, major and experience screen. Four have GPA notes and five have experience notes. The export supplies no structured GPA calculation scope or independent verification of those decisions. The raw reports remain local and the application treats them as background context.

```powershell
python -m scripts.build_catalog --validate --input data/catalog/cs75_planning_seed.json
python -m pytest -q tests/test_cs75_review.py tests/test_admission_dp_audit.py tests/test_benchmark.py
python -m scripts.audit_target_readiness --input '<path to local admissions export>'
```
