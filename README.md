# GradMatch

An evidence-grounded U.S. CS/ECE master's program matching course project.

Current stage: **M3.5 recommendation pilot**. Public app: **https://gradmatch-nathan-sie.streamlit.app/**. The current catalog contains 10 programs and 30 official sources. M3's hosted model interaction, session isolation, reboot recovery and another-device access passed. The pilot adds explicit degree / GRE inputs and evidence-backed planning tiers. The separate 83-record CS Grad tracker database remains unverified. Adaptive agents and formal benchmarks are future milestones.

M3.5 passed 107 checks, clean-host recovery and actual local/hosted model generation plus budget updates. User acceptance remains pending. See [the M3.5 checkpoint and acceptance steps](docs/verification/M35.md).

Follow the [milestones](docs/MILESTONES.md) and [program design](docs/PROGRAM_DESIGN.md). The original proposal is retained in `Project_Proposal.md`. **The application and all future user-facing features use English**, including generated explanations and exported assessments; see `AGENTS.md`.

## Cloud deployment

Use [the deployment guide](docs/DEPLOYMENT.md): GitHub repository `nathan-sie/GradMatch`, branch `main`, entrypoint `app.py`, Python **3.12** and server-side Streamlit Secrets. A clean host rebuilds public SQLite from the versioned seed/snapshots automatically and uses read-only connections. Profiles and chats remain private to each connection.

`python -m scripts.verify_m3` checks release files, regression, cold start, restart and cache recovery without paid requests. See [the actual M3 checkpoint](docs/verification/M3.md) for hosted results and usage. Add `--public-url https://gradmatch-nathan-sie.streamlit.app` for an anonymous Cloud health check.

## Run locally

The project uses an isolated Python 3.12 environment. If `.venv` is already prepared, run these commands from the repository root:

```powershell
.\.venv\Scripts\python.exe -m scripts.build_catalog --input data/catalog/m35_seed.json
.\.venv\Scripts\python.exe -m scripts.verify_m35
.\.venv\Scripts\python.exe -m streamlit run app.py --server.address 127.0.0.1 --server.port 8501
```

Open `http://127.0.0.1:8501`. Click **Load tiering example (USD 140,000)**, enable the per-session paid-call checkbox, then **Generate / rerun**. Expect MSAII in Lottery with source-linked eligibility, costs and limitations. Send **Change my tuition budget to 100000**; MSAII should be excluded by budget while other background stays intact. MCDS remains pending; Target/Safer have no qualifying comparable cases yet. The original **Load synthetic example** and **Data and rule checks (M1)** remain available. Press `Ctrl+C` to stop the local server.

## OpenAI model configuration

Copy `.env.example` to `.env` only if it does not exist. Fill `OPENAI_API_KEY` locally and set `MODEL_ENABLED=true`. Do not commit the key or post it in chat. The default model is `gpt-5.4-mini-2026-03-17`. The page additionally requires **Allow paid model calls for this session**. Without these opt-ins, no model response is simulated.

Run explicit real-model acceptance after configuring the key:

```powershell
.\.venv\Scripts\python.exe -m scripts.verify_m35 --live-model
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

Five programs have computable published-rate tuition: the original UW ECE PMP, USC MSCS and Northeastern Boston MSCS, plus CMU MCDS (USD 97,200, standard three-semester timing) and MSAII (USD 133,500–137,400 including required summer tuition). These estimates use stated rate years and exclude unverified fees/living costs; future prices are not guaranteed. MSAII has a supported pilot recommendation path. MCDS and other programs remain pending where entry requirements or tier evidence are incomplete. Cohort-selectivity planning tiers are not personal admission probabilities. See [the M3.5 scope](docs/M35_SCOPE.md) and [source audit](docs/M35_SOURCES.md).

## Data and secrets

- `data/schema.sql` is versioned; the generated `data/gradmatch.db` is rebuildable and ignored.
- `data/catalog/m35_seed.json` is the current seed. `m1_seed.json` preserves the historical eight-program baseline. `data/snapshots/` contains immutable short evidence snapshots for offline rebuilding; full-page research material stays in ignored `work`.
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

M0 and M2 are user-accepted. M3 cloud acceptance passed on 2026-11-15, including the user's another-device check. The page requires its per-session paid-call checkbox. M4 and later agents/formal evaluation have not started.
