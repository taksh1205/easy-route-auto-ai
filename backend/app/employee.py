"""Provision a local staff identity. The generated token is displayed once."""

import argparse
import hashlib
import secrets

from .db import SessionLocal
from .models import Employee

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("name")
    p.add_argument("role", choices=["reviewer", "manager"])
    args = p.parse_args()
    token = secrets.token_urlsafe(32)
    with SessionLocal() as db:
        db.add(
            Employee(
                name=args.name,
                role=args.role,
                digest=hashlib.sha256(token.encode()).hexdigest(),
            )
        )
        db.commit()
    print(token)
