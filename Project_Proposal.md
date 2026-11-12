# GradMatch

*An Agent for CS and ECE Master’s Program Selection*

EE P 500 D  |   Autumn 2026

## 1 Area

We propose GradMatch to shortlist U.S. CS/ECE master’s programs for international applicants using GPA/scale, institution, academic background, English scores, research, internships, career/research goals, tuition budget, and intake. It recommends 3–5 programs per tier—Lottery, Reach, Target, Safer—when enough  supported matches are available with personalized explanations and latest available sources.

## 2 Problem

Applicants combine university websites, community reports, and spreadsheets to balance fit and admission risk. CS Grad covers program value and employment [1]; Open CS lists programs, tiers, and admission data [2]. Applicants must reconcile sources and verify program, intake, and personal fit.

The agent clarifies missing inputs, verifies requirements, and revises recommendations as evidence changes. It adapts searches to the applicant and incomplete or conflicting evidence, explaining each recommendation and its uncertainty.

## 3 Challenges

Evidence quality. Self-selected community reports are incomplete; requirements and costs change, and similar program names cause confusion. We will prioritize official facts, retain URLs, retrieval dates, and intake years, and flag missing or conflicting evidence.

Personalized judgment. Eligibility, competitiveness, and goal fit differ; GPA minimums cannot establish admission likelihood. We check constraints before fit and tiers, treating institution background as context, not automatic exclusion. Sparse evidence lowers confidence; “Safer” never guarantees admission.

Tiers reflect exceptional selectivity or substantial profile gaps (Lottery), notable gaps (Reach), alignment with comparable reported admits (Target), and relatively lower admission risk supported by available evidence (Safer). Budget and goal fit are assessed separately. Programs without sufficient evidence to support a tier will be excluded from the recommended shortlist.

## 4 Outcomes

By Week 10, our web prototype will cover 40–60 curated CS/ECE programs with live official verification. Outputs show program identity, tier rationale, goal fit, language/prerequisite checks, deadline, full-program tuition estimates with currency and assumptions, and citations. Tiers with too few supported matches are flagged.

Demo scenario: a fictional applicant has GPA 3.5/4.0, TOEFL 100, one research project, one software internship, a USD 70,000 tuition budget, and an employment goal. The agent clarifies missing details and recommends programs. A budget cut to USD 50,000 triggers cost rechecks, replacement options, and explanations.

## 5 Tools

We will use Python, LangGraph for workflow state [3], a tool-calling model, a search API, an HTML/PDF reader, SQLite for structured evidence, and Streamlit. A pilot will select the model, then fix its version and settings. CS Grad and Open CS identify candidates; official pages verify facts.

Shared tools—search_programs, fetch_official_page, check_constraints, rank_programs, validate_shortlist—support both variants’ action/planning strategies. Code handles costs, deduplication, and validation; a shared call budget limits retries. Program records and source passages ground recommendations and further searches.

Evaluation uses synthetic profiles, with no identifiable applicant data in search queries. Retrieved pages are evidence, not instructions. We will respect source access and attribution requirements; the prototype cannot submit applications, contact schools, or make payments.

## 6 Experiments

We will compare (A) a ReAct baseline that selects its next action from the current context and tool results, and (B) a plan-and-replan agent that creates an explicit task plan before execution and updates it when new evidence requires changes. Both use the same model, settings, evidence snapshot, tools, and maximum tool-call budget. Scripted user replies make clarification cases reproducible.

After debugging, both variants will run about 10 main scenarios withheld from prompt tuning: typical applicants, missing inputs, conflicting sources, and infeasible constraints, with manually checked facts and expected behaviors. Both also run Section 7’s 10 adversarial cases. Tests use fixed search/page snapshots; the demo retrieves current official facts. We will add cases and repeat runs as the prototype develops.

## 7 Measurement

Accuracy. Automatic checks cover structure, unique programs, required fields, tier counts or justified shortfalls, costs, and verified constraints. Task success is each variant’s fraction of main runs passing all applicable checks, including expected clarification/infeasibility responses; safety is separate. A blinded citation audit checks factual support; two reviewers score goal fit and tier reasoning with a shared rubric, without estimating admission probabilities.

Safety. Ten additional adversarial cases test instructions embedded in retrieved pages, profile disclosure, and unsupported guarantees. We will measure attack success and fabricated-citation rates, using synthetic profiles and disabling external write actions.

Efficiency and targets. We will report tokens, model/tool calls, median and 95th-percentile latency, and per-run cost, including failures. Targets: at least 80% task success, 95% factual support among audited claims, and zero known hard-constraint violations in accepted recommendations. We will compare both variants on success, factual support, runtime, and cost, reporting limitations without assuming improvement. Tool, evidence, plan-revision, and validation logs support debugging and evaluation.

Sources [ [1] CS Grad](https://csgrad.com/)  [ [2] Open CS](https://opencs.app/)  [ [3] LangGraph documentation](https://docs.langchain.com/oss/python/langgraph/overview)
