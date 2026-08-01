#!/usr/bin/env python3
"""Generate Claude, Codex, and project-folder outputs from canonical sources."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_SOURCE = ROOT / "source" / "phn-workflow.md"
FOLDER_SOURCE = ROOT / "source" / "project-folder.md"
PROJECT_RESOLUTION_SOURCE = ROOT / "source" / "project-resolution.md"
CONFIG_PATH = ROOT / "plugins" / "bldgtyp" / "config" / "phn.json"


def _outputs() -> dict[Path, str]:
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    workflow_source = WORKFLOW_SOURCE.read_text(encoding="utf-8").strip()
    project_resolution = PROJECT_RESOLUTION_SOURCE.read_text(encoding="utf-8").strip()
    shared = {
        "credentials_path": config["credentials_path"],
        "project_resolution": project_resolution,
    }
    claude_workflow = (
        workflow_source.format(**shared, login_command="`/bldgtyp:phn-login`") + "\n"
    )
    codex_workflow = (
        workflow_source.format(**shared, login_command="the `phn-login` device flow")
        + "\n"
    )
    folder = FOLDER_SOURCE.read_text(encoding="utf-8")
    claude_folder = folder.format(
        project_resolution=project_resolution,
        runtime_instruction="installed `/bldgtyp:phn` skill and `phn` MCP server",
        login_instruction="If the PHN credential is missing, run `/bldgtyp:phn-login`",
    )
    codex_folder = folder.format(
        project_resolution=project_resolution,
        runtime_instruction="global `phn` instructions and `phn` MCP server",
        login_instruction="If the PHN credential is missing, run the `phn-login` device flow",
    )
    marker = (
        json.dumps(
            {
                "phn_project_id": None,
                "phn_api": config["api_url"],
                "phn_web": config["web_url"],
            },
            indent=2,
        )
        + "\n"
    )
    return {
        ROOT / "plugins" / "bldgtyp" / "skills" / "phn" / "SKILL.md": (
            "---\n"
            "description: Use PH-Navigator project data safely through the production phn MCP server\n"
            "---\n\n"
            f"{claude_workflow}"
        ),
        ROOT / "dist" / "codex" / "AGENTS.md": (
            "<!-- BEGIN BLDGTYP PHN GENERATED SECTION -->\n"
            f"{codex_workflow}"
            "<!-- END BLDGTYP PHN GENERATED SECTION -->\n"
        ),
        ROOT / "templates" / "project-folder" / ".phn.json": marker,
        ROOT / "templates" / "project-folder" / "CLAUDE.md": claude_folder,
        ROOT / "templates" / "project-folder" / "AGENTS.md": codex_folder,
    }


def generate(*, check: bool) -> int:
    stale: list[Path] = []
    for path, content in _outputs().items():
        if check:
            if not path.exists() or path.read_text(encoding="utf-8") != content:
                stale.append(path.relative_to(ROOT))
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    if stale:
        print("Generated outputs are stale:", file=sys.stderr)
        for path in stale:
            print(f"  {path}", file=sys.stderr)
        return 1
    return 0


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    raise SystemExit(generate(check=args.check))


if __name__ == "__main__":
    main()
