#!/usr/bin/env python3
"""Reject client identifiers and credential material from the public repo."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN = {
    "client project name": re.compile(r"\bLinde\b", re.IGNORECASE),
    "client project number": re.compile(r"\b2524(?:_|\b)"),
    "PH-Navigator plaintext token": re.compile(r"phn_mcp_[A-Za-z0-9_-]+"),
    "developer home path": re.compile(r"/Users/em(?:/|\b)"),
    "UUID-shaped project id": re.compile(
        r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}\b"
    ),
}


def tracked_files() -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return [ROOT / line for line in result.stdout.splitlines() if line]


def main() -> None:
    findings: list[str] = []
    for path in tracked_files():
        if path == Path(__file__).resolve():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for label, pattern in FORBIDDEN.items():
            if pattern.search(text):
                findings.append(f"{path.relative_to(ROOT)}: contains {label}")
    for finding in findings:
        print(finding)
    raise SystemExit(bool(findings))


if __name__ == "__main__":
    main()
