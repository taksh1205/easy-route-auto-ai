"""Legacy dealership Chromium suite against a disposable stack."""

import sys

from browser_harness import run_suite

if __name__ == "__main__":
    sys.exit(run_suite("tests/customer.cjs", "legacy-browser"))
