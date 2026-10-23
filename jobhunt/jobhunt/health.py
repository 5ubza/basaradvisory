"""Run-level health warnings (auth failures, unreachable hosts, missing keys). Shown at the top of the digest and
cause a digest to be sent even when there are no new jobs, so silent failures reach the inbox."""
from __future__ import annotations

_WARNINGS: list[str] = []


def warn(msg: str) -> None:
    if msg not in _WARNINGS:
        _WARNINGS.append(msg)


def warnings() -> list[str]:
    return list(_WARNINGS)


def reset() -> None:
    _WARNINGS.clear()
