# GradMatch

An evidence-grounded U.S. CS/ECE master's program matching course project.

Current stage: **M2 user-accepted; M3 cloud deployment in progress**. The catalog contains 8 programs and 20 sources. M3 adds automatic public-catalog recovery, clean-host verification and deployment configuration. Regression passes 83 checks. The separate 83-record CS Grad tracker database remains an unverified candidate pool. A real public URL and hosted interaction acceptance are pending.

Follow the [milestones](docs/MILESTONES.md) and [program design](docs/PROGRAM_DESIGN.md). The original proposal is retained in `Project_Proposal.md`. **The application and all future user-facing features use English**, including generated explanations and exported assessments; see `AGENTS.md`.

## Cloud deployment

Use [the deployment guide](docs/DEPLOYMENT.md): GitHub repository `nathan-sie/GradMatch`, branch `main`, entrypoint `app.py`, Python **3.12** and server-side Streamlit Secrets. A clean host rebuilds public SQLite from the versioned seed/snapshots automatically and uses read-only connections. Profiles and chats remain private to each connection.

`python -m scripts.verify_m3` checks release files, regression, cold start, restart and cache recovery without paid requests. See [the actual M3 checkpoint](docs/verification/M3.md); this does not claim a deployed public app.

## Run locally

The project uses an isolated Python 3.12 environment. If `.venv` is already prepared, run these commands from the repository root:

```powershell
.\.venv\Scripts\python.exe -m scripts.build_catalog --input data/catalog/m1_seed.json
.\.venv\Scripts\python.exe -m scripts.verify_m2
.\.venv\Scripts\python.exe -m streamlit run app.py --server.address 127.0.0.1 --server.port 8501
```

Open `http://127.0.0.1:8501`. In **Applicant workflow (M2)** click **Load synthetic example**, then **Generate / rerun**. Send **Change my tuition budget to 50000** and inspect the updated profile and removal reasons. See the [M2 acceptance steps](docs/verification/M2.md). **Data and rule checks (M1)** retains the earlier verification page. Press `Ctrl+C` to stop the local server.

## OpenAI model configuration

Copy `.env.example` to `.env` only if it does not exist. Fill `OPENAI_API_KEY` locally and set `MODEL_ENABLED=true`. Do not commit the key or post it in chat. The default model is `gpt-5.4-mini-2026-03-17`. The page additionally requires **Allow paid model calls for this session**. Without these opt-ins, no model response is simulated.

Run explicit real-model acceptance after configuring the key:

```powershell
.\.venv\Scripts\python.exe -m scripts.verify_m2 --live-model
```

This uses only the synthetic applicant and records actual call/token/latency/cost data. Ordinary `verify_m2` uses offline stubs, which do not count as live results. A reusable task entry is `python -m scripts.run_task --synthetic --followup "Change my tuition budget to 50000"`; add `--live-model` to explicitly permit paid requests. See [M2 verification](docs/verification/M2.md) for limits and the complete checkpoint.

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

Only UW ECE PMP, USC non-thesis MSCS, and Northeastern Boston standard MSCS have reproducible published-rate tuition estimates. Other programs remain unknown where billing periods or fee breakdowns are incomplete. These estimates do not guarantee future actual tuition. Remaining eligibility, goal-fit and risk evidence is incomplete, so M2 cannot populate real tiers yet. It separates pending candidates from formal recommendations.

## Data and secrets

- `data/schema.sql` is versioned; the generated `data/gradmatch.db` is rebuildable and ignored.
- `data/catalog/m1_seed.json` and `data/snapshots/` contain versioned public records and short evidence snapshots for offline rebuilding. Full-page research material stays in the ignored `work` directory.
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
- [CS Grad tracker candidate import](docs/CSGRAD_IMPORT.md)

M0 and M2 are user-accepted. M3 offline preparation passed on 2026-11-15; cloud account setup and hosted acceptance are pending. The page still requires its per-session paid-call checkbox. Agents and formal evaluation remain pending. Localhost does not satisfy the public deployment requirement.
