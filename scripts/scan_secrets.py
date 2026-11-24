"""Basic repository secret-pattern scan. Does not prove absence of all secret formats."""

import json
import re
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
patterns = [
    re.compile(r"sk-(?:proj-)?[A-Za-z0-9_-]{32,}"),
    re.compile(r"gh[pousr]_[A-Za-z0-9]{30,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
]
exclude = {"node_modules", ".next", ".git", "__pycache__", ".pytest_cache", "rag_index", ".venv"}
findings = []
scanned = 0
for path in root.rglob("*"):
    if (
        not path.is_file()
        or set(path.relative_to(root).parts) & exclude
        or path.suffix in {".zip", ".db", ".faiss", ".pyc"}
    ):
        continue
    if path.name == ".env":
        findings.append(
            {"file": str(path.relative_to(root)), "reason": "runtime env file must not be packaged"}
        )
        continue
    try:
        text = path.read_text()
    except (UnicodeError, OSError):
        continue
    scanned += 1
    for number, line in enumerate(text.splitlines(), 1):
        if any(p.search(line) for p in patterns):
            findings.append(
                {
                    "file": str(path.relative_to(root)),
                    "line": number,
                    "reason": "credential pattern",
                }
            )
result = {
    "scanner": "basic-pattern-v1",
    "files_scanned": scanned,
    "findings": findings,
    "limitations": "Limited key formats; synthetic test secrets and placeholder credentials are not production secrets. Manual review and stronger scanning remain necessary.",
}
print(json.dumps(result, indent=2))
sys.exit(bool(findings))
