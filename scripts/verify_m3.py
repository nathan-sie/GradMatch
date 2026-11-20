"""Verify the exact publishable file set and a fresh host without local secrets or SQLite."""

import argparse
from datetime import datetime, timezone
from http.cookiejar import CookieJar
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from urllib.parse import urlparse
from urllib.request import build_opener, HTTPCookieProcessor

from gradmatch.config import load_settings
from gradmatch.storage import PROJECT_ROOT


def release_files():
    result = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=PROJECT_ROOT, capture_output=True, check=True)
    names = sorted(set(result.stdout.decode("utf-8").split("\0")) - {""})
    key = load_settings().api_key.encode()
    manifest = []
    forbidden = {".git", ".venv", ".tools", "work", "runs", "__pycache__", ".pytest_cache"}
    for name in names:
        relative = Path(name)
        if relative.is_absolute() or ".." in relative.parts or forbidden & set(relative.parts):
            raise ValueError("The release file set includes a private/runtime path.")
        if name in {".env", ".streamlit/secrets.toml", "data/gradmatch.db"} or (relative.name.startswith(".env.") and relative.name != ".env.example"):
            raise ValueError("A real secret or runtime database is in the publishable file set.")
        path = PROJECT_ROOT / relative
        if not path.is_file() or path.is_symlink():
            raise ValueError("A release path is missing or is an unsupported symbolic link.")
        payload = path.read_bytes()
        if (len(key) >= 10 and key in payload) or re.search(rb"sk-(?:proj-)?[A-Za-z0-9_-]{32,}", payload):
            raise ValueError(f"A possible API secret was detected in {name}. No secret value has been printed.")
        manifest.append({"path": name, "sha256": hashlib.sha256(payload).hexdigest(), "bytes": len(payload)})
    from gradmatch.catalog import DEFAULT_SEED
    required = {"app.py", "uv.lock", "pyproject.toml", ".python-version", ".streamlit/config.toml", "data/catalog/m1_seed.json", "data/catalog/m35_seed.json", DEFAULT_SEED.relative_to(PROJECT_ROOT).as_posix(), "data/schema.sql", "gradmatch/bootstrap.py"}
    if not required <= set(names):
        raise ValueError("The release is missing a required application/data/dependency file.")
    return manifest


PROBE = r'''
import json, logging
from pathlib import Path
logging.getLogger("streamlit").setLevel(logging.ERROR)
from streamlit.testing.v1 import AppTest
from gradmatch.bootstrap import resolve_app_database
from gradmatch.catalog import load_seed, read_catalog
from gradmatch.config import load_settings
from gradmatch.storage import PROJECT_ROOT, DEFAULT_DATABASE, inspect_catalog
from gradmatch.validation import data_hash
assert PROJECT_ROOT == Path.cwd()
assert not DEFAULT_DATABASE.exists()
assert not (PROJECT_ROOT / ".env").exists()
assert not (PROJECT_ROOT / ".streamlit/secrets.toml").exists()
assert not load_settings().ready
app=AppTest.from_file(str(PROJECT_ROOT/"app.py"),default_timeout=20).run()
assert not app.exception
expected_programs, expected_sources = load_seed()
assert [m.value for m in app.metric] == [str(len(expected_programs)),str(len(expected_sources))]
assert app.session_state["m2_session"].profile.tuition_budget_usd is None
assert not app.session_state["m2_session"].messages
app.button(key="m2_load_example").click().run()
app.button(key="m2_generate").click().run()
app.chat_input(key="m2_chat").set_value("Change my tuition budget to 50000").run()
assert not app.exception
session=app.session_state["m2_session"]
assert session.profile.tuition_budget_usd == 50000 and not session.usage
assert session.current_result["profile_version"] == session.profile.profile_version
assert not session.current_result.get("recommendations")
database=resolve_app_database()
programs,sources=read_catalog(database)
print("M3_PROBE="+json.dumps({"status":"passed","programs":len(programs),"sources":len(sources),"data_hash":data_hash(programs,sources),"database":str(database),"model_calls":0,"fresh_session":True}))
'''


def probe_clean_release(manifest):
    with tempfile.TemporaryDirectory(prefix="gradmatch-m3-") as temporary:
        checkout = Path(temporary) / "checkout"
        checkout.mkdir()
        for item in manifest:
            destination = checkout / item["path"]
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(PROJECT_ROOT / item["path"], destination)
        env = os.environ.copy()
        for key in ["OPENAI_API_KEY", "MODEL_API_KEY", "GRADMATCH_DB_PATH", "MODEL_NAME", "MODEL_PROVIDER"]:
            env.pop(key, None)
        env["MODEL_ENABLED"] = "false"
        env["GRADMATCH_PUBLIC_CACHE_DIR"] = str(Path(temporary) / "public-cache")
        results = []
        for step in ["cold_start", "process_restart", "cache_loss_rebuild"]:
            if step == "cache_loss_rebuild":
                Path(results[0]["database"]).unlink()  # Exact file produced inside our temporary workspace.
            result = subprocess.run([sys.executable, "-c", PROBE], cwd=checkout, env=env,
                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
            if result.returncode:
                raise RuntimeError(f"Clean release {step} failed: {result.stderr[-3000:]}")
            line = next((line for line in result.stdout.splitlines() if line.startswith("M3_PROBE=")), None)
            if line is None: raise RuntimeError("The clean-start probe returned no verification record.")
            results.append({"step": step, **json.loads(line.split("=", 1)[1])})
        if len({record["data_hash"] for record in results}) != 1:
            raise ValueError("Public catalog facts changed across clean start/restart/rebuild.")
        return [{key: value for key, value in result.items() if key != "database"} for result in results]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--public-url", help="Optional real https://*.streamlit.app URL to check without authentication.")
    args = parser.parse_args()
    report = {"milestone": "M3", "verified_at": datetime.now(timezone.utc).isoformat(),
        "offline_status": "failed", "cloud_status": "not_deployed", "public_url": None,
        "cloud_browser_acceptance": "pending", "another_device_acceptance": "pending",
        "model_api_calls": 0, "milestone_complete": False}
    work = PROJECT_ROOT / "work"
    work.mkdir(exist_ok=True)
    code = 1
    try:
        manifest = release_files()
        (work / "m3_release_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        result = subprocess.run([sys.executable, "-m", "pytest", "-q"], cwd=PROJECT_ROOT,
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
        print(result.stdout)
        if result.returncode: raise RuntimeError("Regression checks failed; deployment is not ready.")
        report.update(test_output=result.stdout, clean_release_checks=probe_clean_release(manifest),
            release_file_count=len(manifest), release_hash=hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest(),
            offline_status="passed")
        code = 0
        if args.public_url:
            parsed = urlparse(args.public_url)
            if parsed.scheme != "https" or not (parsed.hostname or "").endswith(".streamlit.app") or parsed.username or parsed.password or parsed.query or parsed.fragment:
                raise ValueError("A real public HTTPS Streamlit app URL is required.")
            url = args.public_url.rstrip("/")
            # Community Cloud's observed frontend embeds the app at /~/+/.
            # Start with an empty guest cookie jar, never the owner's browser session.
            visitor = build_opener(HTTPCookieProcessor(CookieJar()))
            with visitor.open(url + "/", timeout=20) as response:
                if response.status != 200:
                    raise ValueError("The anonymous public landing page is unavailable.")
            with visitor.open(url + "/~/+/_stcore/health", timeout=20) as response:
                if response.status != 200 or response.read() != b"ok":
                    raise ValueError("The unauthenticated public health check did not return ok.")
            report.update(public_url=url, anonymous_health_path="/~/+/_stcore/health", cloud_status="health_passed_browser_acceptance_pending")
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        report["error"] = str(error)
        code = 1
    path = work / "m3_verification.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"M3 offline: {report['offline_status']}; cloud: {report['cloud_status']}; report: {path}")
    if report.get("error"): print(report["error"], file=sys.stderr)
    raise SystemExit(code)


if __name__ == "__main__":
    main()
