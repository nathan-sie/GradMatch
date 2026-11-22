# GradMatch

An evidence-grounded U.S. CS/ECE master's program matching course project.

Current stage: **M6.3 all-program recommendations**. Public app: **https://gradmatch-nathan-sie.streamlit.app/**. The default **Generate / rerun** and **Save profile and generate** workflow now selects from **all 83 maintained programs**, using CS Grad language, GRE and deadline data alongside the 20 officially reviewed identities / 145 sources. Shared baseline, ReAct and plan-and-replan tools can search, check, rank and recommend programs outside those 20. Community-backed recommendations are labelled preliminary and do not invent GPA, tuition or personal admission tiers. See [verification](docs/verification/M63.md). Final-project evaluation remains incomplete.

Keep **Recommendation pool: All 83 programs (official + community data)** to use the broad recommendation workflow. The agent selects a subset after screening, rather than recommending every program. **Reviewed official records only** preserves the original restricted workflow. With paid calls disabled, generation produces clearly labelled rule-based recommendations from the same broad pool; it does not simulate a model run. **Save profile and preview all programs** remains a separate free table of all 83 records. The [M6.2 data batch](docs/verification/M62.md) supplies language fields and portals for 83, known GRE markers for 82, listed rounds for 80 and application fees for 82.

M6.1j adds seven sources for MCDS and NYU Tandon CS. For the fixed fictional profile, MCDS retains only its English hard-check gap and NYU retains only its GPA-scope gap; neither becomes a formal recommendation. The directory exposes source-bound program-cohort context with an explicit distinction from personal admission probability. Preparation coverage reaches ten, reviewed remaining checklists seven, and dated intake/deadline coverage 14/12. All **384 regression checks** pass after the documented fixes, with no paid model calls. See [source decisions](docs/M61J_SOURCES.md) and [verification](docs/verification/M61J.md).

M6.1i reviews seven programs and adds four **conservative tuition ceilings**, alongside the existing eight two-sided estimates and one minimum-only bound. A covered ceiling can pass a published-rate budget; a lower budget remains unknown because the actual bill can be lower. The directory labels ceilings explicitly. Dated intake/deadline coverage rises to 13/11, preparation to nine, degree to 16 and remaining-checklist reviews to five. Reference hard-check readiness stays two and formal tier support stays one. All 360 unique regression checks have passing outcomes across the full run and targeted rerun; the earlier count assertion and timeout are retained in [run accounting](docs/verification/M61I_validation_runs.json). See [source decisions](docs/M61I_SOURCES.md) and [verification](docs/verification/M61I.md).

M6.1h passed **327 regression checks** and reviews seven existing programs: usable preparation policies increase **3 → 8**, complete reviewed English policies **5 → 8**, and reviewed remaining-eligibility checklists **2 → 4**. UCI passes the hard checks for the fixed fictional CS profile but lacks admission-tier evidence. Cornell's department-specific new TOEFL speaking floor is corrected to 5.5; its older-score route remains pending confirmation. Illinois and Wisconsin use published Fall 2027 term dates for test validity; conditional scores remain unknown. Four new specific preparation inputs share the form and follow-up vocabulary. Historical source objects remain intact, with replaced field bindings explicitly archived. See [source decisions](docs/M61H_SOURCES.md) and [verification](docs/verification/M61H.md).

M6.1g passed **299 regression checks**. Twelve existing programs gain 18 sources; full tuition estimates increase to eight, usable GPA policies to eight, degree policies to 15 and GRE policies to 19. Eight additional programs support **English score-floor screening only**: low scores can fail the selected-test check, while meeting a floor leaves validity and other conditions pending. Complete reviewed planning eligibility remains two and fixed-profile formal evidence readiness remains one. See [source decisions](docs/M61G_SOURCES.md), [the checkpoint](docs/verification/M61G.md) and [coverage](docs/verification/M61G_catalog_audit.md).

M6.1f adds Duke ECE MS, CMU Pittsburgh ECE MS, Georgia Tech on-campus MSCS and UCSD CS MS. It completes UW ECE PMP's reviewed planning checklist and adds UCI's cumulative-undergraduate GPA minimum. Seven full tuition estimates remain; Duke separately has a published-rate **minimum of USD 104,820 with no verified upper bound**. A lower budget can be excluded, while a higher budget cannot establish affordability. See [source decisions](docs/M61F_SOURCES.md) and [the checkpoint](docs/verification/M61F.md).

M6.1e passed **267 regression checks**. Twelve programs gained 20 official sources; usable GRE rules increased from 8 to 15 and degree rules from 8 to 12. Policy details became visible in comparison and detail views. See [the historical batch checkpoint](docs/verification/M61E.md).

M6.1d passed **254 regression checks**, SQLite cache recovery and clean-host startup/restart/recovery. Directory browsing and comparison make no model requests. Read the [directory checkpoint](docs/verification/M61D.md). The user accepted the preceding hosted 16/62 count display.

M6.1c passed **246 regression checks**. Read the [checkpoint](docs/verification/M61C.md), [historical coverage](docs/verification/M61C_catalog_audit.md), [source decisions](docs/M61C_SOURCES.md) and [next data gates](docs/M6_DATA_REVIEW.md). Nineteen new source records support four scoped identities and two additional computable cost estimates: NYU uses a published per-credit rate; Cornell uses a clearly labelled university-budget-plan rate and the two-semester track. Both retain their rate year and future-bill uncertainty. There are seven computable tuition estimates and still one formally supported recommendation for the fixed fictional profile. Incomplete qualification, dates, fee bases and tier evidence remain explicit. The user-accepted [M6.1b first batch](docs/verification/M61B.md) and [M6.1a historical audit](docs/verification/M61.md) are preserved.

M5.3 passed 181 checks, three clean-host scenarios and the actual hosted generation/budget-update/reuse flow. The accepted flow used four model requests; earlier failures remain recorded. User page acceptance passed on 2026-11-19. See [M5 checkpoint](docs/verification/M5.md) and [M5 scope and acceptance steps](docs/M5_SCOPE.md). M4 passed clean-host recovery and a six-request real-model live-evidence task; the user's supplied session confirmed the budget-update page check. A follow-up guard patch passed 146 regression checks and prevents stale context from skipping current ranking. Earlier failures and costs are retained. See [the M4 checkpoint](docs/verification/M4.md) and [scope/commands](docs/M4_SCOPE.md). M3.5's earlier [recommendation checkpoint](docs/verification/M35.md) remains available as historical evidence.

Follow the [milestones](docs/MILESTONES.md) and [program design](docs/PROGRAM_DESIGN.md). The original proposal is retained in `Project_Proposal.md`. **The application and all future user-facing features use English**, including generated explanations and exported assessments; see `AGENTS.md`.

## Cloud deployment

Use [the deployment guide](docs/DEPLOYMENT.md): GitHub repository `nathan-sie/GradMatch`, branch `main`, entrypoint `app.py`, Python **3.12** and server-side Streamlit Secrets. A clean host rebuilds public SQLite from the versioned seed/snapshots automatically and uses read-only connections. Profiles and chats remain private to each connection.

`python -m scripts.verify_m3` checks release files, regression, cold start, restart and cache recovery without paid requests. See [the actual M3 checkpoint](docs/verification/M3.md) for hosted results and usage. Add `--public-url https://gradmatch-nathan-sie.streamlit.app` for an anonymous Cloud health check.

## Run locally

The project uses an isolated Python 3.12 environment. If `.venv` is already prepared, run these commands from the repository root:

```powershell
.\.venv\Scripts\python.exe -m scripts.build_catalog --input data/catalog/m61j_seed.json
.\.venv\Scripts\python.exe -m scripts.verify_m61j
.\.venv\Scripts\python.exe -m streamlit run app.py --server.address 127.0.0.1 --server.port 8501
```

Open `http://127.0.0.1:8501`. Select **ReAct agent**, **Catalog snapshots** and **All 83 programs (official + community data)**, then load **Load tiering example (USD 140,000)**. Generate without paid consent to inspect rule-based recommendations, or enable the per-session paid-call checkbox for an actual model run. The current assessment names the 83-program pool and labels preliminary recommendations. The verified MSAII path can separately support Lottery; unsupported personal tiers remain unassigned. Send **Change my tuition budget to 100000**: budget checks must update while other background and cumulative task counters remain. **Live official pages** allows bounded reads of registered official URLs and retains recorded dates for other facts; community URLs are not silently registered as official fetch targets. Press `Ctrl+C` to stop the local server.

## OpenAI model configuration

Copy `.env.example` to `.env` only if it does not exist. Fill `OPENAI_API_KEY` locally and set `MODEL_ENABLED=true`. Do not commit the key or post it in chat. The default model is `gpt-5.4-mini-2026-03-17`. The page additionally requires **Allow paid model calls for this session**. Without these opt-ins, no model response is simulated.

Run explicit real-model acceptance after configuring the key:

```powershell
.\.venv\Scripts\python.exe -m scripts.verify_m4 --live-model --max-live-model-calls 8
```

`verify_m35 --live-model` permits at most two paid requests using only the fictional tiering applicant and records actual call/token/latency/cost data. Ordinary `verify_m35` runs regression without paid calls. Offline stubs do not count as live results. Earlier M2/M3 records are historical checkpoints and are not overwritten by this verifier.

## Install in a clean environment

With an existing, executable Python 3.12 installation, use uv and the lockfile:

```powershell
uv sync --locked --no-managed-python --python 3.12
```

Alternatively, use Python 3.12 and pip:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
```

On Windows, call `.venv\Scripts\python.exe` directly; activation and PowerShell execution-policy changes are unnecessary. On macOS/Linux, use `.venv/bin/python`. Runtime and development dependencies are exported from the same lockfile to `requirements.txt` and `requirements-dev.txt`.

Windows application control blocked the downloaded portable Python 3.11 during M1 verification. The current standard `.venv` was created from an existing executable Python 3.12, and the full regression suite passed. System security policy was not changed. The old environment is archived in the ignored `.tools/venv311_blocked_20261113` directory. The current machine can use the prepared `.venv` directly.

## Data and rule verification

`verify_m1` validates typed records, evidence bindings, hashes and database consistency. Its original 43 checks remain in the regression suite. `verify_m2` adds state, trust, metering and actual-page regressions and writes `work/m2_verification.json`. These are milestone checks, separate from the future 210-task benchmark.

`build_catalog --input data/catalog/m1_seed.json` validates and imports records using stable program IDs, preserving other records and historical sources. Add `--validate` to validate without writing. Without `--input`, it only creates the empty schema or checks an existing database. Missing or invalid databases produce an explicit error.

The seven computable cost estimates include the earlier UW ECE PMP, USC MSCS, Northeastern Boston MSCS and two CMU estimates, plus the new NYU per-credit and Cornell budget-plan calculations. Each retains its rate year and scope; future prices are not guaranteed, and unverified fees/living costs are excluded. MSAII retains a supported pilot recommendation path. Other programs remain pending where qualification or tier evidence is incomplete. Cohort-selectivity planning tiers are not personal admission probabilities. See [M6.1c source decisions](docs/M61C_SOURCES.md) and the historical [M3.5 source audit](docs/M35_SOURCES.md).

## Data and secrets

- `data/schema.sql` is versioned; the generated `data/gradmatch.db` is rebuildable and ignored.
- `data/catalog/active.json` selects `m61j_seed.json` at call time, including after data updates. Earlier versioned seeds preserve historical catalogs. `data/snapshots/` contains immutable short evidence snapshots for offline rebuilding; full-page research material stays in ignored `work`. A valid older default local database is preserved; startup uses a rebuilt cache when its contents differ from the current seed. An explicitly selected `GRADMATCH_DB_PATH` retains the requested database.
- Applicant profiles and sessions are not written into the public catalog.
- `.venv`, `.tools`, temporary records, `.env`, and `.streamlit/secrets.toml` are ignored.
- A real OpenAI key is needed for explicit M2 live checks. Never commit secrets.

## Documentation and status

- [Milestones](docs/MILESTONES.md)
- [Program design](docs/PROGRAM_DESIGN.md)
- [M0 verification](docs/verification/M0.md)
- [M1 verification and page acceptance](docs/verification/M1.md)
- [M2 verification and page acceptance](docs/verification/M2.md)
- [M3 deployment verification](docs/verification/M3.md)
- [M3.5 recommendation verification](docs/verification/M35.md)
- [CS Grad tracker candidate import](docs/CSGRAD_IMPORT.md)
- [Offline evaluation and resume instructions](docs/verification/M64.md)

M0 and M2 are user-accepted. M3 cloud acceptance passed on 2026-11-15, including the user's another-device check. M4 automated and budget-update user acceptance passed on 2026-11-19; the subsequent finish guard has offline regression verification without a new paid rerun. The page still requires its per-session paid-call checkbox. M5 automated, hosted and user page acceptance passed on 2026-11-19. M6.1b's public 12/43 count display is user-accepted. M6.1c passes offline verification and its public 16/62 display is user-accepted. M6.1d exposes all 83 leads; hosted count, search, halt-filter and comparison checks passed without model calls. Full dataset expansion and final-project evaluation remain incomplete. See [M6.1c checkpoint](docs/verification/M61C.md). The separate 50-task homework stays on its own branch.
