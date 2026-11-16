"""One-command M0 verification with a machine-readable report."""

import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import importlib.metadata
import json
from pathlib import Path
import subprocess
import sys

from gradmatch.storage import PROJECT_ROOT, inspect_catalog


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, default=PROJECT_ROOT / "work" / "m0_verification.json")
    args = parser.parse_args()
    report = {
        "milestone": "M0",
        "verified_at": datetime.now(timezone.utc).isoformat(),
        "python": sys.version.split()[0],
        "streamlit": importlib.metadata.version("streamlit"),
        "pytest": importlib.metadata.version("pytest"),
        "status": "failed",
        "manual_browser_acceptance": "not_recorded",
    }
    exit_code = 1
    try:
        if sys.version_info[:2] != (3, 12):
            raise RuntimeError("Use the project's current Python 3.12 environment.")
        report["catalog"] = asdict(inspect_catalog())
        completed = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "tests/test_m0.py"],
            cwd=PROJECT_ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=90,
        )
        print(completed.stdout)
        if completed.stderr:
            print(completed.stderr, file=sys.stderr)
        report["test_output"] = completed.stdout
        report["test_exit_code"] = completed.returncode
        report["status"] = "passed" if completed.returncode == 0 else "failed"
        exit_code = completed.returncode
    except (RuntimeError, OSError, subprocess.TimeoutExpired) as error:
        report["error"] = str(error)
        print(str(error), file=sys.stderr)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"M0 {report['status']}; report: {args.report.resolve()}")
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
