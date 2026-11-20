# M4: adaptive tools, official pages and task recovery

Implementation checkpoint: November 19, 2026. Work continues on `main` at the user's request. The completed 50-task homework remains isolated on `homework/eval-harness-50`; its frozen code, evidence and scores are not merged or changed.

## Application behavior

The applicant page offers **ReAct agent** and **Fixed baseline**, plus **Reviewed snapshots** and **Live official pages**. All labels, questions, results and exported notices are English. The existing model consent checkbox is required for paid requests. Without it the app performs explicitly labelled deterministic checks, not simulated Agent decisions or live extraction.

The current UI and CLI pass an explicit strategy to the same `start_task` service. They share the tool dispatcher, ranking contract, catalog, rubric, constraints, validator and task limits. Pre-M4 callers that omit the strategy retain the older fixed-snapshot adapter for compatibility; new comparisons must select their strategies explicitly.

| Tool | Behavior |
| --- | --- |
| `search_programs` | Stable catalog search, typed discipline/ID/field filters, source-ID discovery; no personal data in external queries |
| `fetch_official_page` | Registered program/source ID only; read bounded official HTML/PDF, then extract typed target facts with exact supporting quotes |
| `check_constraints` | Current profile and evidence versions required; batch eligibility/cost checks; stale checks rejected |
| `rank_programs` | Requires current checks; one shared ranking call; no ranking of unchecked programs |
| `validate_shortlist` | Recomputes constraints/costs and blocks unsupported tiers/citations; runs automatically after ranking |

ReAct selects a structured next action from observations. It may fetch missing evidence, change its candidate scope or ask a profile question. A failed validation can trigger one bounded ranking repair on the same arguments. The fixed baseline has a predetermined search/check/rank/validate flow; in live mode it attempts at most four registered pages in a fixed order and does not ask a model which action to take.

## Network and evidence boundaries

The reader permits only registered HTTPS URLs and exact allowlisted university hosts. It rejects user-info, nonstandard ports, fragments and malformed URLs. Every hop resolves DNS and rejects any nonpublic address; the TLS connection pins the checked numeric address while retaining hostname/certificate verification. Environment proxies, cookies and authentication headers are not used. Redirects are validated again; at most three redirects are followed.

Each page has a 15-second ceiling, 10 MB download limit and 30,000-character extracted-text limit. HTML scripts/forms/iframes are not executed. PDFs are parsed in a separate process with a bounded runtime and page count; encrypted, unreadable and oversized documents fail without OCR or browser bypass. Known access failures are cached for the task rather than retried with different field arguments.

New evidence stays in the individual session. It carries actual URL/time, raw-response and text hashes, an exact quote, applicable intake and typed field bindings. Extraction receives the program identity and field schemas, never the applicant's full profile or secrets. Missing/incomplete extraction is not promoted to a fact. Contradictory applicable official claims retain both sources and make the affected check unknown. No live tool changes the shared SQLite database, host allowlist, rubric, profile or budget.

The first live reader supports the registered catalog rather than open-ended website discovery. No paid third-party search provider is configured; `search_queries` is honestly zero. Unknown programs/URLs require a later reviewed catalog addition. Live mode supplements snapshots: only receipt-listed sources were read for the task; other claims keep their original snapshot dates. It does not promise that every requirement is currently reverified. In particular, a rate-only tuition page cannot establish a complete tuition policy or missing billable-unit basis.

## Budgets, pause and replay

Production task ceilings are versioned in `config/agent.json`: 20 tools, 16 model requests, 16 page requests, 6 user turns, 120 seconds per service turn and 300 seconds cumulative service time. Interpretation, action selection, extraction and ranking all count. The existing 20-model-request session ceiling is an additional limit. There are no automatic model retries. Each actual redirect consumes a page-request unit.

LangGraph uses a unique session/task/strategy thread and an in-memory checkpointer. The interrupt node only asks/receives input: no model/network call, logging or profile mutation occurs inside it. Resume retains task identity, counters, completed observations and caches; user think time is excluded. Request-ID replay returns the saved receipt without applying profile changes or paying again. Official page and extraction caches prevent duplicate retrieval/extraction charges. All user changes still cross the shared atomic profile-patch boundary; explicit read-only requests avoid a mutation interpreter.

One pure validation slot is reserved. Exhaustion stops further paid work, validates any partial draft in the reserved slot and returns `budget_exhausted`. This is not a completed success. **Start new task (keep profile)** resets task state explicitly, not the session's paid-call ceiling. Starting a new session clears the connection-local memory. Refresh/server restart can lose this memory; durable cross-process recovery is not claimed.

The model adapter accepts one structured JSON object or up to three canonically identical copies of that object. Identical copies execute once and are logged as normalization. Different objects, trailing junk and schema violations are rejected; the adapter never chooses a convenient action from contradictory outputs. This is response-protocol handling, not a paid repair call.

## Verification and next acceptance

Run offline checks without model requests:

```powershell
python -m scripts.verify_m4
python -m scripts.run_task --synthetic --strategy react --data-mode snapshot --output work/m4/offline-task.json
```

For an intentional bounded live check with fictional data and the existing local key:

```powershell
python -m scripts.verify_m4 --live-pages
python -m scripts.verify_m4 --live-model --max-live-model-calls 8 --output-dir work/m4/new-live-check
```

Use a new output directory. The live acceptance removes the UW credit evidence in an isolated scenario, asks for the official credit count, uses the existing published-rate snapshot for tuition, and requires the computed cost to regain the new credit source citation. It must preserve the profile. Real failures remain failures; offline stubs are not benchmark scores.

Automated acceptance passed: 144 regression checks, genuine HTML/PDF reads, clean-host recovery and a fresh six-request real-model flow. The scoped live task restored UW's credit evidence, recomputed USD 50,850 and completed with zero validation errors while retaining unrelated eligibility gaps. The final status was correctly `insufficient_evidence`, not a fabricated formal recommendation. Earlier failures and the budget-exhausted task remain preserved and separately counted. User page acceptance remains pending; see `docs/verification/M4.md` for the dated outcome, cost accounting and limitations.

Framework references: [LangGraph interrupts](https://docs.langchain.com/oss/python/langgraph/interrupts), [Python HTTPS client](https://docs.python.org/3.12/library/http.client.html), [pypdf text extraction](https://pypdf.readthedocs.io/en/stable/user/extract-text.html). M5 planning, broader catalog coverage and final-project evaluation remain separate milestones.
