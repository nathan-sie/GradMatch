# Four-program catalog review for the admissions datapoint pilot

The local active seed `dp_batch_review_seed.json` updates four existing program records and adds ten official source records. The directory contains 83 programs, including 20 reviewed identities with 163 official sources. The [applicant-report pilot](ADMISSION_DP_PILOT.md) documents the historical data mappings.

| Program | Evidence added | Review still needed |
| --- | --- | --- |
| UW ECE PMP, Seattle | Industry-oriented evening curriculum and career support now supply evidence for an employment goal. The program reports a usual four- to five-quarter full-time pace. | For GPA, use the existing last-60-semester or last-90-quarter credit basis. Applicants can supply the matching basis in the form. |
| NYU Tandon MSCS, Brooklyn | The official program description now supports research goals through available areas including algorithms and cybersecurity, alongside its professional computing electives. | Tandon publishes a 3.0/4 admission threshold. The captured policy leaves its calculation scope unconfirmed. |
| UIUC MCS, Urbana-Champaign | The Graduate College baseline is 3.0/4 over the last two undergraduate years, with individual review possible below it. The MCS separately recommends 3.2/4 and offers a 32-credit, coursework-only degree. The recurring fall deadline is May 1. | The planner uses the new last-two-years GPA option for the baseline. A distinct Fall 2027 deadline confirmation and the self-supporting cohort rate are pending. |
| USC Viterbi general MSCS, Los Angeles | Fall 2027 scholarship consideration is December 15, 2026 and the published final date is January 15, 2027. The 32-unit degree has a documented program goal and checklist. Viterbi's master’s FAQ states there is no admission GPA floor. | The school may still review late on-campus applications. Individual preparation and English eligibility require review. USC sources describe different score-validity anchors, and the central score benchmarks are for placement. |

Official sources for UW include the [PMP program](https://www.ece.uw.edu/academics/pmp/). NYU details come from the [Tandon MSCS program](https://engineering.nyu.edu/academics/programs/computer-science-ms) and [general requirements](https://engineering.nyu.edu/admissions/graduate/apply/admissions-requirements).

The Illinois sources cover the [Urbana program](https://siebelschool.illinois.edu/academics/graduate/professional-mcs/campus-master-computer-science), [Graduate College baseline](https://grad.illinois.edu/admissions/graduate-admissions-minimum-requirements), [MCS application guidance](https://siebelschool.illinois.edu/academics/graduate/professional-mcs/app-info), [deadline table](https://siebelschool.illinois.edu/admissions/graduate/application-deadlines), and [tuition policy](https://siebelschool.illinois.edu/academics/graduate/professional-mcs/tuition-fees).

The USC sources cover the [general MSCS](https://viterbigradadmission.usc.edu/programs/masters/msprograms/computer-science/ms-computer-science/), [dated application cycle](https://viterbigradadmission.usc.edu/), [Viterbi FAQ](https://viterbigradadmission.usc.edu/programs/masters/faq/), and [Graduate Admission English policy](https://gradadm.usc.edu/prospective-international-students/english-proficiency/).

## Reproduce

```powershell
python -m scripts.build_catalog --validate --input data/catalog/dp_batch_review_seed.json
python -m pytest -q tests/test_dp_catalog_batch.py
python -m scripts.audit_target_readiness --input '<path to local admissions export>'
```

The tiering example with a 3.80/4 overall GPA and Fall 2027 intake remains pending in all four programs. USC's official unknown checks fall from six to three. The UW example passes the formal eligibility and budget checks when the user supplies a 3.80/4 last-90-quarter GPA. Those checks are distinct from the admission evidence required for a personal tier. An equivalent eligibility result for UIUC still needs the cohort tuition and other remaining checks, even after a 3.80/4 last-two-years GPA passes the Graduate College baseline.
