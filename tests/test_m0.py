"""M0 integration checks: catalog safety, real app execution, and HTTP startup."""

from contextlib import closing
import hashlib
import ipaddress
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
import time
from urllib.error import URLError
from urllib.request import urlopen

import pytest
from streamlit.testing.v1 import AppTest

from gradmatch.storage import (
    CatalogNotReadyError,
    PROJECT_ROOT,
    connect_read_only,
    inspect_catalog,
)
from scripts.build_catalog import build_empty_catalog


@pytest.fixture
def catalog(tmp_path: Path) -> Path:
    return build_empty_catalog(tmp_path / "catalog.db")


def test_application_cannot_modify_catalog(catalog: Path) -> None:
    before = hashlib.sha256(catalog.read_bytes()).hexdigest()
    with closing(connect_read_only(catalog)) as connection:
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            connection.execute("CREATE TABLE unexpected (value TEXT)")
    assert hashlib.sha256(catalog.read_bytes()).hexdigest() == before
    assert inspect_catalog(catalog).program_count == 0


def test_missing_catalog_is_not_silently_created(tmp_path: Path) -> None:
    missing = tmp_path / "missing.db"
    with pytest.raises(CatalogNotReadyError):
        inspect_catalog(missing)
    assert not missing.exists()


def test_invalid_catalog_is_rejected(tmp_path: Path) -> None:
    invalid = tmp_path / "invalid.db"
    invalid.write_bytes(b"not a SQLite database")
    with pytest.raises(CatalogNotReadyError):
        inspect_catalog(invalid)


def test_builder_never_resets_existing_data(catalog: Path) -> None:
    with closing(sqlite3.connect(catalog)) as connection:
        connection.execute(
            "INSERT INTO programs VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("test-only", "Fixture University", "Fixture MS", "MS", "test", "CS", "{}", "fixture"),
        )
        connection.commit()
    build_empty_catalog(catalog)
    assert inspect_catalog(catalog).program_count == 1


def test_page_and_check_button_work_without_external_network(catalog: Path, monkeypatch) -> None:
    monkeypatch.setenv("GRADMATCH_DB_PATH", str(catalog))
    original_connect = socket.socket.connect

    def deny_external_network(connection, address):
        # Windows asyncio creates a loopback socket pair for its own event loop.
        # Keep that working while refusing all non-loopback destinations.
        if isinstance(address, tuple):
            try:
                is_loopback = ipaddress.ip_address(address[0]).is_loopback
            except ValueError:
                is_loopback = False
            if is_loopback:
                return original_connect(connection, address)
        raise AssertionError("M0 page attempted to open an external network connection")

    monkeypatch.setattr(socket.socket, "connect", deny_external_network)
    app = AppTest.from_file(str(PROJECT_ROOT / "app.py"), default_timeout=15).run()
    assert not app.exception
    assert [metric.value for metric in app.metric] == ["0", "0"]
    app.button(key="check_environment").click().run()
    assert not app.exception
    assert len(app.success) == 1


def test_streamlit_server_reaches_http_health(catalog: Path) -> None:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    env = os.environ.copy()
    env["GRADMATCH_DB_PATH"] = str(catalog)
    creationflags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    process = subprocess.Popen(
        [
            sys.executable, "-m", "streamlit", "run", "app.py",
            "--server.address=127.0.0.1", f"--server.port={port}",
            "--server.headless=true", "--browser.gatherUsageStats=false",
        ],
        cwd=PROJECT_ROOT, env=env, stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
        creationflags=creationflags,
    )
    try:
        deadline = time.monotonic() + 25
        while time.monotonic() < deadline:
            if process.poll() is not None:
                pytest.fail(f"Streamlit exited before startup: {process.stdout.read()}")
            try:
                with urlopen(f"http://127.0.0.1:{port}/_stcore/health", timeout=1) as response:
                    if response.status == 200 and response.read() == b"ok":
                        return
            except (URLError, TimeoutError):
                time.sleep(0.1)
        pytest.fail("Streamlit health endpoint did not become ready within 25 seconds")
    finally:
        process.terminate()
        try:
            process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate(timeout=5)

