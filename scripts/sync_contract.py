#!/usr/bin/env python3
"""Update the vendored public MCP contract from a PH-Navigator checkout."""

from __future__ import annotations

import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DESTINATION = ROOT / "contract" / "phn-mcp.md"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    args = parser.parse_args()
    source = args.source.expanduser().resolve()
    text = source.read_text(encoding="utf-8")
    if (
        "# PH-Navigator MCP Contract" not in text
        or "mcp-tool-inventory:start" not in text
    ):
        raise SystemExit(f"Not a PH-Navigator MCP contract: {source}")
    DESTINATION.parent.mkdir(parents=True, exist_ok=True)
    DESTINATION.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
