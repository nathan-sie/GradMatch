# GradMatch

An evidence-grounded U.S. CS/ECE master's program matching course project.

Current stage: **M6.1c second official data batch**. Public app: **https://gradmatch-nathan-sie.streamlit.app/**. The runtime catalog contains **16 programs / 62 source records**. The second batch adds Texas A&M MCS, NYU Tandon MSCS, Wisconsin professional CS MS and Cornell Ithaca CS MEng. All 83 community candidates remain unverified leads; 16 scoped identities link to official records and four initial expansion leads remain queued. The 40–60 program target and final-project evaluation are still incomplete.

M6.1c passed **246 regression checks**. Read the [checkpoint](docs/verification/M61C.md), [current coverage](docs/verification/M61C_catalog_audit.md), [source decisions](docs/M61C_SOURCES.md) and [next data gates](docs/M6_DATA_REVIEW.md). Nineteen new source records support four scoped identities and two additional computable cost estimates: NYU uses a published per-credit rate; Cornell uses a clearly labelled university-budget-plan rate and the two-semester track. Both retain their rate year and future-bill uncertainty. There are seven computable tuition estimates and still one formally supported recommendation for the fixed fictional profile. Incomplete qualification, dates, fee bases and tier evidence remain explicit. The user-accepted [M6.1b first batch](docs/verification/M61B.md) and [M6.1a historical audit](docs/verification/M61.md) are preserved.

M5.3 passed 181 checks, three clean-host scenarios and the actual hosted generation/budget-update/reuse flow. The accepted flow used four model requests; earlier failures remain recorded. User page acceptance passed on 2026-11-19. See [M5 checkpoint](docs/verification/M5.md) and [M5 scope and acceptance steps](docs/M5_SCOPE.md). M4 passed clean-host recovery and a six-request real-model live-evidence task; the user's supplied session confirmed the budget-update page check. A follow-up guard patch passed 146 regression checks and prevents stale context from skipping current ranking. Earlier failures and costs are retained. See [the M4 checkpoint](docs/verification/M4.md) and [scope/commands](docs/M4_SCOPE.md). M3.5's earlier [recommendation checkpoint](docs/verification/M35.md) remains available as historical evidence.

Follow the [milestones](docs/MILESTONES.md) and [program design](docs/PROGRAM_DESIGN.md). The original proposal is retained in `Project_Proposal.md`. **The application and all future user-facing features use English**, including generated explanations and exported assessments; see `AGENTS.md`.

## Cloud deployment

Use [the deployment guide](docs/DEPLOYMENT.md): GitHub repository `nathan-sie/GradMatch`, branch `main`, entrypoint `app.py`, Python **3.12** and server-side Streamlit Secrets. A clean host rebuilds public SQLite from the versioned seed/snapshots automatically and uses read-only connections. Profiles and chats remain private to each connection.

`python -m scripts.verify_m3` checks release files, regression, cold start, restart and cache recovery without paid requests. See [the actual M3 checkpoint](docs/verification/M3.md) for hosted results and usage. Add `--public-url https://gradmatch-nathan-sie.streamlit.app` for an anonymous Cloud health check.

## Run locally

The project uses an isolated Python 3.12 environment. If `.venv` is already prepared, run these commands from the repository root:

```powershell
.\.venv\Scripts\python.exe -m scripts.build_catalog --input data/catalog/m61c_seed.json
.\.venv\Scripts\python.exe -m scripts.verify_m61c
.\.venv\Scripts\python.exe -m streamlit run app.py --server.address 127.0.0.1 --server.port 8501
```

Open `http://127.0.0.1:8501`. Select **ReAct agent** and **Reviewed snapshots**, then load **Load tiering example (USD 140,000)**. After enabling the per-session paid-call checkbox, generate and inspect tool activity. The verified MSAII path can support Lottery; MCDS and unsupported tiers remain pending. Send **Change my tuition budget to 100000**: budget checks must update while other background and cumulative task counters remain. **Live official pages** explicitly allows bounded reads of registered official URLs and may retain older snapshots for other facts. Press `Ctrl+C` to stop the local server.

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
- `data/catalog/m61c_seed.json` is the current seed. `m61b_seed.json`, `m35_seed.json` and `m1_seed.json` preserve earlier catalogs. `data/snapshots/` contains immutable short evidence snapshots for offline rebuilding; full-page research material stays in ignored `work`. A valid older default local database is preserved; startup uses a rebuilt cache when its contents differ from the current seed. An explicitly selected `GRADMATCH_DB_PATH` retains the requested database.
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

M0 and M2 are user-accepted. M3 cloud acceptance passed on 2026-11-15, including the user's another-device check. M4 automated and budget-update user acceptance passed on 2026-11-19; the subsequent finish guard has offline regression verification without a new paid rerun. The page still requires its per-session paid-call checkbox. M5 automated, hosted and user page acceptance passed on 2026-11-19. M6.1b's public 12/43 count display is user-accepted. M6.1c adds the second data batch and passes offline verification; its public 16/62 display awaits user confirmation. Full dataset expansion and final-project evaluation remain incomplete. See [M6.1c checkpoint](docs/verification/M61C.md). The separate 50-task homework stays on its own branch.
