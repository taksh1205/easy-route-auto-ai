"""Own an isolated SQLite database and verify the full migration chain with an existing booking."""

import json
import os
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
out = Path(os.environ.get("EASY_EVIDENCE_DIR", ROOT / "docs/v06/evidence"))
out.mkdir(parents=True, exist_ok=True)
commands = []
with (
    tempfile.TemporaryDirectory(prefix="easy_sqlite_upgrade_") as d,
    (out / "sqlite-upgrade.txt").open("w") as log,
):
    path = Path(d) / "upgrade.db"
    env = dict(os.environ, DATABASE_URL="sqlite:///" + str(path))

    def run(args):
        result = subprocess.run(args, cwd=ROOT / "backend", env=env, stdout=log, stderr=log)
        commands.append({"command": args, "exit_code": result.returncode})
        if result.returncode:
            raise RuntimeError("Migration check failed")

    run([sys.executable, "-m", "alembic", "upgrade", "0001"])
    with sqlite3.connect(path) as conn:
        conn.execute(
            "INSERT INTO vehicles VALUES(1,'Synthetic upgrade fixture','sedan',12345,5,'[]',1)"
        )
        conn.execute("INSERT INTO conversations VALUES('owner','hash','{}',0)")
        conn.execute("INSERT INTO appointments VALUES('existing','owner',1,2000000000,0)")
    run([sys.executable, "-m", "alembic", "upgrade", "head"])
    run([sys.executable, "-m", "app.seed"])
    run([sys.executable, "-m", "alembic", "check"])
    with sqlite3.connect(path) as conn:
        conn.execute("PRAGMA foreign_keys=ON")
        assert conn.execute("SELECT id FROM appointments").fetchall() == [("existing",)]
        try:
            conn.execute("DELETE FROM conversations WHERE id='owner'")
        except sqlite3.IntegrityError:
            log.write("PASS: preserved existing booking; parent deletion rejected by FK\n")
        else:
            raise AssertionError("Appointment deletion protection failed")
    (out / "sqlite-upgrade-commands.json").write_text(json.dumps(commands, indent=2))
print(
    "PASS: SQLite 0001→head migration, existing-booking retention, seed, schema check and RESTRICT"
)
