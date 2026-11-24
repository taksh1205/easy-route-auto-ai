"""Disposable full-stack browser harness shared by every Chromium suite.

Guarantees, in order:

1. Refuse to run if ``DATABASE_URL`` is set or if the API/frontend ports are already in
   use. The harness never tests (or kills) a process it did not start.
2. Build a temporary SQLite database and policy index, migrate, seed, ingest and create
   a synthetic reviewer identity.
3. Start uvicorn and ``next start`` each in its **own process group**. ``npm start``
   forks ``next-server``; terminating npm alone leaves that child holding port 3000,
   which is why back-to-back runs used to collide.
4. On exit (success, failure or Ctrl-C) signal each owned process group, escalate to
   SIGKILL after a grace period, and wait until both ports are actually released.
"""

from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
API_PORT, WEB_PORT = 8000, 3000


def port_open(port: int) -> bool:
    with socket.socket() as probe:
        probe.settimeout(0.2)
        return probe.connect_ex(("127.0.0.1", port)) == 0


def wait_for(predicate, timeout: float, what: str) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.2)
    raise RuntimeError(f"Timed out waiting for {what}")


def http_ok(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=2) as response:
            return response.status == 200
    except Exception:
        return False


def stop_group(process: subprocess.Popen, grace: float = 10.0) -> None:
    """Terminate an owned process group, escalating to SIGKILL if needed."""
    if process.poll() is not None and not _group_alive(process.pid):
        return
    for sig, wait in ((signal.SIGTERM, grace), (signal.SIGKILL, 5.0)):
        try:
            os.killpg(process.pid, sig)
        except ProcessLookupError:
            return
        deadline = time.monotonic() + wait
        while time.monotonic() < deadline:
            if not _group_alive(process.pid):
                process.poll()
                return
            time.sleep(0.1)


def _group_alive(pgid: int) -> bool:
    try:
        os.killpg(pgid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def run_suite(test_script: str, evidence_name: str, extra_env: dict | None = None) -> int:
    out = Path(os.environ.get("EASY_EVIDENCE_DIR", ROOT / "docs/evidence")) / evidence_name
    out.mkdir(parents=True, exist_ok=True)
    if os.environ.get("DATABASE_URL"):
        raise SystemExit("Unset DATABASE_URL. Browser tests allocate a disposable database.")
    for port in (API_PORT, WEB_PORT):
        if port_open(port):
            raise SystemExit(
                f"Refusing occupied port {port}; stop the existing app before the disposable E2E run"
            )

    python = sys.executable
    with tempfile.TemporaryDirectory(prefix="easy_browser_") as temp:
        env = dict(
            os.environ,
            DATABASE_URL="sqlite:///" + str(Path(temp) / "browser.db"),
            RAG_PATH=str(Path(temp) / "rag"),
            AI_MODE="deterministic",
            STAFF_TOKEN="browser-test-only",
            HF_HUB_DISABLE_XET="1",
            **(extra_env or {}),
        )
        commands = []
        for step, args in enumerate(
            [["-m", "alembic", "upgrade", "head"], ["-m", "app.seed"], ["-m", "app.ingest"]],
            start=1,
        ):
            r = subprocess.run(
                [python, *args], cwd=ROOT / "backend", env=env, capture_output=True, text=True
            )
            commands.append({"command": ["python", *args], "exit_code": r.returncode})
            (out / f"setup-{step}.txt").write_text(r.stdout + r.stderr)
            if r.returncode:
                return r.returncode
        identity = subprocess.run(
            [python, "-m", "app.employee", "browser-reviewer-" + os.urandom(3).hex(), "reviewer"],
            cwd=ROOT / "backend",
            env=env,
            capture_output=True,
            text=True,
            check=True,
        )
        env["DEMO_EMPLOYEE_TOKEN"] = identity.stdout.strip()

        owned: list[subprocess.Popen] = []
        started = time.monotonic()
        try:
            with (out / "api.log").open("w") as api_log, (out / "web.log").open("w") as web_log:
                owned.append(
                    subprocess.Popen(
                        [
                            python,
                            "-m",
                            "uvicorn",
                            "app.main:app",
                            "--host",
                            "127.0.0.1",
                            "--port",
                            str(API_PORT),
                        ],
                        cwd=ROOT / "backend",
                        env=env,
                        stdout=api_log,
                        stderr=api_log,
                        start_new_session=True,
                    )
                )
                owned.append(
                    subprocess.Popen(
                        ["npm", "start", "--", "--hostname", "127.0.0.1", "--port", str(WEB_PORT)],
                        cwd=ROOT / "frontend",
                        env=env,
                        stdout=web_log,
                        stderr=web_log,
                        start_new_session=True,
                    )
                )
                wait_for(lambda: http_ok(f"http://127.0.0.1:{API_PORT}/health"), 60, "API health")
                wait_for(lambda: http_ok(f"http://127.0.0.1:{WEB_PORT}/"), 60, "frontend")
                if any(p.poll() is not None for p in owned):
                    raise RuntimeError("Owned server exited; refusing to test another process")
                r = subprocess.run(
                    ["node", test_script],
                    cwd=ROOT / "frontend",
                    env=env,
                    text=True,
                    capture_output=True,
                )
                (out / "browser.txt").write_text(r.stdout + r.stderr)
                commands.append({"command": ["node", test_script], "exit_code": r.returncode})
                print(r.stdout + r.stderr)
                return r.returncode
        finally:
            for process in reversed(owned):
                stop_group(process)
            wait_for(
                lambda: not port_open(API_PORT) and not port_open(WEB_PORT), 30, "port release"
            )
            (out / "commands.json").write_text(
                json.dumps(
                    {
                        "commands": commands,
                        "ports_released": True,
                        "seconds": round(time.monotonic() - started, 1),
                    },
                    indent=2,
                )
            )
