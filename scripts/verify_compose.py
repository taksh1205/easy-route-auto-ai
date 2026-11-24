"""Exercise a fresh, uniquely named Compose project. Run on a Docker-capable host."""

import json
import os
import secrets
import shutil
import socket
import subprocess
import time
from datetime import date, timedelta
from pathlib import Path
from urllib.request import Request, urlopen
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]


def main():
    if not shutil.which("docker"):
        raise SystemExit("Docker CLI unavailable; Compose persistence check unexecuted")
    for port in [3000, 8000]:
        with socket.socket() as sock:
            if sock.connect_ex(("127.0.0.1", port)) == 0:
                raise SystemExit(f"Port {port} is already occupied")
    command = ["docker", "compose", "--project-name", "easycheck" + uuid4().hex]
    # Optional host-specific overrides (e.g. a proxy/CA build file), colon-separated.
    extra = [f for f in os.environ.get("EASY_COMPOSE_FILES", "").split(":") if f]
    if extra:
        command += ["-f", str(ROOT / "compose.yaml")] + [a for f in extra for a in ("-f", f)]
    env = {
        **os.environ,
        "AI_MODE": "deterministic",
        "POSTGRES_PASSWORD": secrets.token_hex(24),
        "STAFF_TOKEN": secrets.token_hex(32),
        "OPENAI_API_KEY": "",
        "OPENAI_MODEL": "",
    }

    def compose(*args, capture=False):
        return subprocess.run(
            [*command, *args],
            cwd=ROOT,
            env=env,
            check=True,
            text=True,
            capture_output=capture,
        ).stdout

    def api(path, body=None, headers=None):
        req = Request(
            "http://127.0.0.1:8000" + path,
            data=json.dumps(body).encode() if body is not None else None,
            headers={"Content-Type": "application/json", **(headers or {})},
        )
        with urlopen(req, timeout=10) as response:
            return json.load(response)

    def ready():
        for _ in range(120):
            try:
                api("/health")
                with urlopen("http://127.0.0.1:3000/rentals", timeout=3) as response:
                    if response.status == 200:
                        return
            except OSError:
                time.sleep(1)
        raise RuntimeError("Stack readiness timed out")

    try:
        compose("up", "-d", "--build")
        ready()
        token = compose(
            "exec",
            "-T",
            "api",
            "python",
            "-m",
            "app.employee",
            "persistence-reviewer",
            "reviewer",
            capture=True,
        ).strip()
        session = api("/sessions", {})
        base = "/sessions/" + session["id"] + "/rentals"
        headers = {"X-Session-Token": session["token"]}
        start = date.today() + timedelta(days=10)
        end = start + timedelta(days=2)
        state = api(
            base + "/search",
            dict(start=str(start), end=str(end), body="sedan"),
            headers,
        )
        q = api(
            base + "/reference",
            dict(turn=state["turn"], position=1, operation="quote"),
            headers,
        )["quote"]
        rid = q["id"]
        assert (
            api(
                base + "/" + rid + "/submit",
                {"terms": q["terms"]},
                {**headers, "Idempotency-Key": rid},
            )["status"]
            == "pending"
        )
        assert (
            api(
                "/rental-staff/" + rid + "/decision",
                {"action": "approve"},
                {"X-Employee-Token": token},
            )["status"]
            == "confirmed"
        )

        def snapshot():
            record = next(r for r in api(base, headers=headers)["records"] if r["id"] == rid)
            # Only this generated UUID is interpolated into the read-only verification query.
            from uuid import UUID

            query = f"SELECT day FROM rental_days WHERE reservation='{UUID(rid)}' ORDER BY day"
            days = compose(
                "exec",
                "-T",
                "db",
                "psql",
                "-U",
                "easy",
                "-d",
                "easy",
                "-Atc",
                query,
                capture=True,
            ).splitlines()
            return record, days

        before = snapshot()
        assert before[1] == [str(start), str(start + timedelta(days=1))]
        compose("restart", "db", "api", "web")
        ready()
        assert snapshot() == before
        print(
            json.dumps(
                dict(
                    reservation=rid,
                    status=before[0]["status"],
                    occupied=before[1],
                    restart_verified=True,
                )
            )
        )
    finally:
        compose("down", "--volumes", "--remove-orphans")


if __name__ == "__main__":
    main()
