import os
import subprocess
import sys


def test_arbitrary_database_url_refused(tmp_path):
    # A harmless nonexistent database URL must fail before the DB engine is imported.
    env = dict(os.environ, DATABASE_URL="sqlite:///" + str(tmp_path / "must-not-exist.db"))
    env.pop("EASY_TEST_POSTGRES_ADMIN_URL", None)
    code = "import runpy;runpy.run_path('tests/conftest.py')"
    result = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True)
    assert result.returncode != 0 and "Refusing DATABASE_URL" in result.stderr
    assert not (tmp_path / "must-not-exist.db").exists()
