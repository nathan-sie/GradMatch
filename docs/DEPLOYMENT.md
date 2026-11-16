# Streamlit Community Cloud deployment

Release: M3-2026-11-15. Repository: **nathan-sie/GradMatch**. Branch: **main**. Entrypoint: **app.py**. Python: **3.12**.

## Data and sessions

The repository contains the public seed, SQLite schema and 20 short evidence snapshots, not the generated `data/gradmatch.db`. On a clean host the app validates those records and builds SQLite atomically in an app-managed temporary directory keyed by the public data hash. All normal application connections are read-only. Missing/corrupt managed caches rebuild automatically; an explicitly configured `GRADMATCH_DB_PATH` remains authoritative and never silently falls back.

Only public data is shared. Profiles, chats, results and counters stay in each Streamlit connection; another browser does not see them. Reconnecting or restarting can clear this history. There are at most two simultaneous paid model requests per process, bounded waiting and no automatic retries. Live source retrieval and adaptive agents remain later milestones.

## Prepare and deploy

1. Run `python -m scripts.verify_m3`. It scans the publishable files for secrets/private runtime data, runs regression and tests a clean copy without local keys, SQLite or history. Separate processes verify cold start, restart and cache-loss recovery. No paid API request occurs. Reports: `work/m3_verification.json` and `work/m3_release_manifest.json`.
2. Sign in at [Streamlit Community Cloud](https://share.streamlit.io/), personally completing account terms and GitHub authorization.
3. Click **Create app**, choose an existing GitHub app and select repository **nathan-sie/GradMatch**, branch **main**, entrypoint **app.py**. Type the exact values if selectors do not list them.
4. Under **Advanced settings**, choose **Python 3.12**. Community Cloud prioritizes the root `uv.lock`; exported requirements reflect that same lockfile.
5. Paste top-level TOML in **Secrets**, filling the key only on Streamlit's own account page:

```toml
MODEL_PROVIDER = "openai"
MODEL_NAME = "gpt-5.4-mini-2026-03-17"
OPENAI_API_KEY = "<your key, only in Cloud Secrets>"
MODEL_ENABLED = "true"
```

The blank template is `.streamlit/secrets.example.toml`. A private ready-to-paste local copy can be prepared at `work/streamlit_cloud_secrets.toml`; never commit/share it. Top-level Secrets are available in the server environment. Do not put `.env` in GitHub.

6. Save and deploy. Choose a subdomain if available; record only the URL actually assigned by Streamlit. Make the app public so classmates do not need the owner's account. Writer-only cloud build logs diagnose startup failures.

## Real URL acceptance

1. Open the assigned URL in a signed-out/private browser: expect release **M3-2026-11-15**, 8 programs and 20 sources without an owner login.
2. Enable **Allow paid model calls for this session**, then **Load synthetic example → Generate / rerun**. Inspect actual model completion and usage.
3. Send **Change my tuition budget to 50000**. Profile version increases; GPA, English, experiences, goal and intake remain unchanged. At the fixed verification date 2026-11-15, pending candidates change 7 → 5 with UW/Northeastern over-budget reasons. Formal tiers remain empty because evidence is incomplete.
4. Ask **Which remaining candidates fit employment goals? Do not change my profile.** It must retain USD 50,000 and report unsupported goal comparisons honestly.
5. In an independent device/browser connection, load USD 70,000. The first connection stays at USD 50,000; messages/results do not cross over.
6. Reboot from the owner dashboard. The public catalog recovers and the new session has no earlier personal history. Recheck the URL from another device.

Optional unauthenticated health check: `python -m scripts.verify_m3 --public-url https://<actual-app>.streamlit.app`. Health alone does not establish hosted model behavior, browser isolation, reboot or another-device acceptance. Record the actual URL/revision/checks in `docs/verification/M3.md` and the JSON report.

References: [deploying](https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/deploy), [dependencies and Python](https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/app-dependencies), [server Secrets](https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/secrets-management).
