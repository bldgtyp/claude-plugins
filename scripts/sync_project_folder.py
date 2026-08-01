#!/usr/bin/env python3
"""Sync generated thin agent files into a BLDGTYP project folder."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "templates" / "project-folder"


def sync(target: Path) -> None:
    if not target.is_dir():
        raise SystemExit(f"Target is not a directory: {target}")
    for name in ("CLAUDE.md", "AGENTS.md"):
        (target / name).write_text(
            (TEMPLATE / name).read_text(encoding="utf-8"), encoding="utf-8"
        )
    marker_path = target / ".phn.json"
    if marker_path.exists():
        marker = json.loads(marker_path.read_text(encoding="utf-8"))
        if not isinstance(marker, dict) or set(marker) != {
            "phn_project_id",
            "phn_api",
            "phn_web",
        }:
            raise SystemExit(
                f"Refusing to replace an unexpected marker shape: {marker_path}"
            )
    else:
        marker = json.loads((TEMPLATE / ".phn.json").read_text(encoding="utf-8"))
    canonical_marker = json.loads((TEMPLATE / ".phn.json").read_text(encoding="utf-8"))
    marker["phn_api"] = canonical_marker["phn_api"]
    marker["phn_web"] = canonical_marker["phn_web"]
    marker_path.write_text(json.dumps(marker, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("target", type=Path)
    args = parser.parse_args()
    sync(args.target.expanduser().resolve())


if __name__ == "__main__":
    main()
