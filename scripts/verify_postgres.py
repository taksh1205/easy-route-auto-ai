"""Local verification utility. Owns a fresh temporary PostgreSQL cluster.

Uses PostgreSQL server binaries from ``PG_BIN``, from ``pg_config --bindir``/Debian paths,
or from the ``pgserver`` wheel, in that order.
Never connects to or drops an existing application database. No fixed-date appointment tests.
"""

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from contextlib import suppress
from pathlib import Path

import psycopg

ROOT = Path(__file__).resolve().parents[1]
out = Path(os.environ.get("EASY_EVIDENCE_DIR", ROOT / "docs/v06/evidence"))
out.mkdir(parents=True, exist_ok=True)


def server_binaries() -> Path:
    candidates = [os.environ.get("PG_BIN")]
    with suppress(FileNotFoundError):  # pg_config is optional
        candidates.append(
            subprocess.run(["pg_config", "--bindir"], capture_output=True, text=True).stdout.strip()
        )
    candidates += sorted((str(p) for p in Path("/usr/lib/postgresql").glob("*/bin")), reverse=True)
    for candidate in filter(None, candidates):
        if (Path(candidate) / "initdb").exists():
            return Path(candidate)
    import pgserver  # optional fallback wheel

    return Path(pgserver.__file__).parent / "pginstall/bin"


binary = server_binaries()
results = []
with (
    tempfile.TemporaryDirectory(prefix="easy_pg_") as d,
    (out / "postgres-tests.txt").open("w") as log,
):

    def run(cmd, env):
        log.write("\nCOMMAND: " + " ".join(cmd) + "\n")
        log.flush()
        r = subprocess.run(cmd, cwd=ROOT / "backend", env=env, stdout=log, stderr=log)
        results.append({"command": cmd, "exit_code": r.returncode})
        log.flush()
        if r.returncode:
            raise RuntimeError("Command failed: " + str(cmd))

    subprocess.run(
        [
            str(binary / "initdb"),
            "-D",
            d + "/data",
            "-A",
            "trust",
            "-U",
            "easy",
            "--no-locale",
            "--encoding=UTF8",
        ],
        stdout=log,
        stderr=log,
        check=True,
    )
    # Temporary cluster listens only on loopback and exposes no UNIX socket.
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    p = subprocess.Popen(
        [str(binary / "postgres"), "-D", d + "/data", "-h", "127.0.0.1", "-p", str(port), "-k", ""],
        stdout=log,
        stderr=log,
    )
    url = f"postgresql://easy@127.0.0.1:{port}/postgres"
    try:
        for _attempt in range(100):
            try:
                conn = psycopg.connect(url, autocommit=True)
                if (
                    Path(conn.execute("SHOW data_directory").fetchone()[0]).resolve()
                    != Path(d + "/data").resolve()
                ):
                    conn.close()
                    raise RuntimeError("Refusing an existing/unowned PostgreSQL server")
                if p.poll() is not None:
                    conn.close()
                    raise RuntimeError("Owned PostgreSQL process exited")
                break
            except psycopg.OperationalError:
                time.sleep(0.1)
        else:
            raise RuntimeError("Temporary PostgreSQL startup failed")
        log.write(str(conn.execute("SELECT version()").fetchone()) + "\n")
        conn.close()
        env = dict(os.environ, DATABASE_URL=url.replace("postgresql://", "postgresql+psycopg://"))
        run([sys.executable, "-m", "alembic", "upgrade", "0001"], env)
        with psycopg.connect(url) as conn:
            conn.execute(
                "INSERT INTO vehicles(id,name,body,price,seats,features,available) VALUES(1,'Synthetic upgrade fixture','sedan',12345,5,'[]',false)"
            )
        run([sys.executable, "-m", "alembic", "upgrade", "head"], env)
        run([sys.executable, "-m", "app.seed"], env)
        with psycopg.connect(url) as conn:
            assert conn.execute(
                "SELECT price,available,mileage FROM vehicles WHERE id=1"
            ).fetchone() == (12345, False, 32000)
        log.write(
            "PASS: v0.1 upgrade preserves existing SQL price/availability and adds attributes\n"
        )
        run([sys.executable, "-m", "alembic", "check"], env)
        safe_env = dict(os.environ, EASY_TEST_POSTGRES_ADMIN_URL=url)
        safe_env.pop("DATABASE_URL", None)
        run([sys.executable, "-m", "pytest", "-q"], safe_env)
        (out / "postgres-commands.json").write_text(json.dumps(results, indent=2))
        print(
            "PASS: PostgreSQL upgrade, seed preservation, schema check and isolated backend tests"
        )
    finally:
        p.terminate()
        p.wait()
