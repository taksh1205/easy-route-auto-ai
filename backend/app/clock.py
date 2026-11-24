"""Single injectable clock used by operational services and clock-controlled tests."""

from datetime import UTC, datetime


def utcnow():
    return datetime.now(UTC)


def timestamp():
    return int(utcnow().timestamp())
