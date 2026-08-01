#!/usr/bin/env python3
"""Check the curated agent workflow against PH-Navigator's MCP contract."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / "plugins" / "bldgtyp" / "skills" / "phn" / "SKILL.md"
CONFIG_PATH = ROOT / "plugins" / "bldgtyp" / "config" / "phn.json"


def fenced_names(text: str) -> set[str]:
    return set(re.findall(r"`([a-z][a-z0-9_]+)`", text))


def check(contract_path: Path) -> list[str]:
    contract = contract_path.read_text(encoding="utf-8")
    workflow = WORKFLOW.read_text(encoding="utf-8")
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    contract_names = fenced_names(contract)
    workflow_names = fenced_names(workflow)
    errors: list[str] = []
    for tool in sorted(config["required_tools"]):
        if tool not in contract_names:
            errors.append(f"MCP contract no longer registers required tool: {tool}")
        if tool not in workflow_names:
            errors.append(f"Agent workflow omits required tool: {tool}")
    for value in sorted(config["recoverability"]):
        if value not in contract_names:
            errors.append(f"MCP contract omits recoverability value: {value}")
        if value not in workflow_names:
            errors.append(f"Agent workflow omits recoverability value: {value}")
    device = config["device"]
    protocol_values = [
        *config["scopes"],
        device["start_path"],
        device["poll_path"],
        *device["pending_statuses"],
        *device["terminal_statuses"].values(),
        *device["credential_fields"].values(),
    ]
    for value in protocol_values:
        if value not in contract:
            errors.append(f"MCP contract omits agent protocol value: {value}")
    for fragment in config["contract_fragments"]:
        if fragment not in contract:
            errors.append(f"MCP contract semantic anchor changed: {fragment}")
    return errors


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("contract", type=Path)
    args = parser.parse_args()
    errors = check(args.contract)
    for error in errors:
        print(error)
    raise SystemExit(bool(errors))


if __name__ == "__main__":
    main()
