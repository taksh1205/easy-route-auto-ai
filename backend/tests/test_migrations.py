"""The migration chain must reproduce the ORM schema exactly (``alembic check`` is clean)."""

import os
import subprocess
import sys


def test_upgrade_head_matches_models(tmp_path):
    env = {k: v for k, v in os.environ.items() if k != "DATABASE_URL"}
    env["DATABASE_URL"] = f"sqlite:///{tmp_path}/migrations.db"
    for args in (["upgrade", "head"], ["check"]):
        proc = subprocess.run(
            [sys.executable, "-m", "alembic", *args], env=env, capture_output=True, text=True
        )
        assert proc.returncode == 0, proc.stdout + proc.stderr
