#!/usr/bin/env python3
"""Configure Claude Code's MCP startup timeout for browser device login."""

from __future__ import annotations

import argparse
import json
import os
import stat
import tempfile
from pathlib import Path
from typing import Any

MINIMUM_MCP_TIMEOUT_MS = 660_000


class ConfigureError(RuntimeError):
    """Claude settings are malformed or unsafe to update automatically."""


def _atomic_write(path: Path, content: str, *, mode: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", dir=path.parent, text=True
    )
    temporary_path = Path(temporary_name)
    try:
        os.fchmod(descriptor, mode)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(content)
        os.replace(temporary_path, path)
    except BaseException:
        temporary_path.unlink(missing_ok=True)
        raise


def configure(settings_path: Path, *, timeout_ms: int = MINIMUM_MCP_TIMEOUT_MS) -> bool:
    """Set MCP_TIMEOUT without replacing unrelated Claude settings."""
    if timeout_ms < MINIMUM_MCP_TIMEOUT_MS:
        raise ConfigureError(
            f"MCP timeout must be at least {MINIMUM_MCP_TIMEOUT_MS} milliseconds."
        )

    if settings_path.exists():
        try:
            payload: Any = json.loads(settings_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ConfigureError(
                f"Existing Claude settings are invalid JSON: {settings_path}"
            ) from exc
        mode = stat.S_IMODE(settings_path.stat().st_mode)
    else:
        payload = {}
        mode = 0o600

    if not isinstance(payload, dict):
        raise ConfigureError("Claude settings must contain a JSON object.")
    environment = payload.setdefault("env", {})
    if not isinstance(environment, dict):
        raise ConfigureError("Claude settings 'env' must contain a JSON object.")

    current = environment.get("MCP_TIMEOUT")
    if current is not None:
        try:
            current_ms = int(current)
        except (TypeError, ValueError) as exc:
            raise ConfigureError(
                "Existing Claude MCP_TIMEOUT must be an integer number of milliseconds."
            ) from exc
        if current_ms >= timeout_ms:
            return False

    environment["MCP_TIMEOUT"] = str(timeout_ms)
    _atomic_write(settings_path, json.dumps(payload, indent=2) + "\n", mode=mode)
    return True


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Allow Claude Code MCP startup to wait for PH-Navigator's "
            "10-minute browser approval flow."
        )
    )
    parser.add_argument(
        "--settings",
        type=Path,
        default=Path.home() / ".claude" / "settings.json",
        help=argparse.SUPPRESS,
    )
    args = parser.parse_args()
    changed = configure(args.settings)
    action = "Configured" if changed else "Already configured"
    print(f"{action}: {args.settings} MCP_TIMEOUT >= {MINIMUM_MCP_TIMEOUT_MS} ms")


if __name__ == "__main__":
    main()
