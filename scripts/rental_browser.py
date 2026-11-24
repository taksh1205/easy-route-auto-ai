"""Rental desk Chromium suite (desktop + mobile) against a disposable stack."""

import sys

from browser_harness import run_suite

if __name__ == "__main__":
    sys.exit(run_suite("tests/rental.cjs", "rental-browser"))
