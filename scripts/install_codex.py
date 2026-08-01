#!/usr/bin/env python3
"""Install the generated PH-Navigator bridge and workflow for Codex."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import stat
import tempfile
import tomllib
from pathlib import Path

from codex_install_contract import (
    AGENTS_END,
    AGENTS_START,
    LOGIN_COMMAND_PLACEHOLDER,
)

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_SOURCE = ROOT / "plugins" / "bldgtyp"
AGENTS_SOURCE = ROOT / "dist" / "codex" / "AGENTS.md"
CONFIG_START = "# BEGIN BLDGTYP PHN MCP GENERATED SECTION"
CONFIG_END = "# END BLDGTYP PHN MCP GENERATED SECTION"
RUNTIME_FILES = (
    Path("bin/phn-login"),
    Path("bin/phn-mcp"),
    Path("config/phn.json"),
    Path("lib/phn_agent.py"),
)


class InstallError(RuntimeError):
    """The installer found an unsafe or ambiguous existing configuration."""


def _replace_managed_section(
    text: str,
    section: str,
    *,
    start: str,
    end: str,
) -> str:
    start_count = text.count(start)
    end_count = text.count(end)
    if (start_count, end_count) == (0, 0):
        prefix = text.rstrip()
        return f"{prefix}\n\n{section.strip()}\n" if prefix else f"{section.strip()}\n"
    if (start_count, end_count) != (1, 1):
        raise InstallError(
            f"Malformed managed section: expected one {start!r} and {end!r}."
        )
    start_index = text.index(start)
    raw_end_index = text.index(end)
    if raw_end_index < start_index:
        raise InstallError(f"Malformed managed section: {end!r} precedes {start!r}.")
    end_index = raw_end_index + len(end)
    return f"{text[:start_index]}{section.strip()}{text[end_index:]}"


def _without_managed_section(text: str, *, start: str, end: str) -> str:
    if start not in text and end not in text:
        return text
    return _replace_managed_section(text, "", start=start, end=end)


def _atomic_write(path: Path, content: str, *, mode: int | None = None) -> None:
    if path.exists() and path.read_text(encoding="utf-8") == content:
        if mode is not None and stat.S_IMODE(path.stat().st_mode) != mode:
            path.chmod(mode)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", dir=path.parent, text=True
    )
    temporary_path = Path(temporary_name)
    try:
        if mode is not None:
            os.fchmod(descriptor, mode)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(content)
        os.replace(temporary_path, path)
    except BaseException:
        temporary_path.unlink(missing_ok=True)
        raise


def _runtime_release_path(install_root: Path) -> Path:
    digest = hashlib.sha256()
    for relative in RUNTIME_FILES:
        digest.update(str(relative).encode())
        digest.update(b"\0")
        digest.update((RUNTIME_SOURCE / relative).read_bytes())
        digest.update(b"\0")
    return install_root / "releases" / digest.hexdigest()[:16]


def _install_runtime(release: Path) -> None:
    if release.exists():
        return
    release.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".staging-", dir=release.parent))
    try:
        for relative in RUNTIME_FILES:
            destination = staging / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(RUNTIME_SOURCE / relative, destination)
        for executable in [staging / "bin/phn-login", staging / "bin/phn-mcp"]:
            executable.chmod(executable.stat().st_mode | stat.S_IXUSR)
        try:
            os.replace(staging, release)
        except OSError:
            if not release.exists():
                raise
    finally:
        if staging.exists():
            shutil.rmtree(staging)


def _configured_release(config_text: str, releases: Path) -> Path | None:
    try:
        parsed = tomllib.loads(config_text)
        command = parsed.get("mcp_servers", {}).get("phn", {}).get("command")
    except (AttributeError, tomllib.TOMLDecodeError):
        return None
    if not isinstance(command, str):
        return None
    candidate = Path(command).parent.parent
    return candidate if candidate.parent == releases else None


def _prune_releases(releases: Path, *, keep: set[Path]) -> None:
    hexadecimal = set("0123456789abcdef")
    candidates = [
        candidate
        for candidate in releases.iterdir()
        if candidate.is_dir()
        and len(candidate.name) == 16
        and set(candidate.name) <= hexadecimal
        and all((candidate / relative).is_file() for relative in RUNTIME_FILES)
    ]
    retained = {candidate for candidate in keep if candidate in candidates}
    for candidate in sorted(
        candidates, key=lambda path: path.stat().st_mtime_ns, reverse=True
    ):
        if len(retained) >= 2:
            break
        retained.add(candidate)
    for candidate in candidates:
        if candidate not in retained:
            shutil.rmtree(candidate)


def _config_section(command: Path) -> str:
    quoted_command = json.dumps(str(command))
    return f"""{CONFIG_START}
[mcp_servers.phn]
command = {quoted_command}
args = []
startup_timeout_sec = 600
tool_timeout_sec = 120
enabled = true

[mcp_servers.phn.env]
PHN_AGENT_CLIENT = "Codex"
{CONFIG_END}"""


def install(*, codex_home: Path, data_home: Path) -> tuple[Path, Path, Path]:
    config_path = codex_home / "config.toml"
    agents_path = codex_home / "AGENTS.md"
    install_root = data_home / "bldgtyp" / "phn-agent"
    release = _runtime_release_path(install_root)
    command = release / "bin/phn-mcp"
    login_command = release / "bin/phn-login"

    config_text = (
        config_path.read_text(encoding="utf-8") if config_path.exists() else ""
    )
    previous_release = _configured_release(config_text, release.parent)
    without_managed = _without_managed_section(
        config_text, start=CONFIG_START, end=CONFIG_END
    )
    try:
        unmanaged_config = tomllib.loads(without_managed)
    except tomllib.TOMLDecodeError as exc:
        raise InstallError(
            f"Existing Codex config is invalid TOML: {config_path}"
        ) from exc
    unmanaged_servers = unmanaged_config.get("mcp_servers", {})
    if isinstance(unmanaged_servers, dict) and "phn" in unmanaged_servers:
        raise InstallError(
            f"Refusing to replace unmanaged [mcp_servers.phn] configuration in {config_path}."
        )
    updated_config = _replace_managed_section(
        config_text,
        _config_section(command),
        start=CONFIG_START,
        end=CONFIG_END,
    )
    try:
        tomllib.loads(updated_config)
    except tomllib.TOMLDecodeError as exc:
        raise InstallError(
            "Generated Codex MCP configuration is invalid TOML."
        ) from exc

    agents_section = AGENTS_SOURCE.read_text(encoding="utf-8")
    if agents_section.count(LOGIN_COMMAND_PLACEHOLDER) != 1:
        raise InstallError(
            "Generated Codex instructions lack one login-command placeholder."
        )
    agents_section = agents_section.replace(
        LOGIN_COMMAND_PLACEHOLDER, str(login_command)
    )
    agents_existed = agents_path.exists()
    agents_text = (
        agents_path.read_text(encoding="utf-8") if agents_path.exists() else ""
    )
    updated_agents = _replace_managed_section(
        agents_text,
        agents_section,
        start=AGENTS_START,
        end=AGENTS_END,
    )

    _install_runtime(release)
    config_mode = (
        stat.S_IMODE(config_path.stat().st_mode) if config_path.exists() else 0o600
    )
    agents_mode = (
        stat.S_IMODE(agents_path.stat().st_mode) if agents_path.exists() else 0o644
    )
    _atomic_write(agents_path, updated_agents, mode=agents_mode)
    try:
        _atomic_write(config_path, updated_config, mode=config_mode)
    except BaseException:
        if agents_existed:
            _atomic_write(agents_path, agents_text, mode=agents_mode)
        elif agents_path.exists():
            agents_path.unlink()
        raise
    _prune_releases(
        release.parent,
        keep={candidate for candidate in (release, previous_release) if candidate},
    )
    return config_path, agents_path, command


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Install or update PH-Navigator MCP access for Codex."
    )
    parser.add_argument(
        "--codex-home",
        type=Path,
        default=Path.home() / ".codex",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--data-home",
        type=Path,
        default=Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")),
        help=argparse.SUPPRESS,
    )
    args = parser.parse_args()
    try:
        config_path, agents_path, command = install(
            codex_home=args.codex_home.expanduser(),
            data_home=args.data_home.expanduser(),
        )
    except (InstallError, OSError) as exc:
        raise SystemExit(f"Codex PH-Navigator install failed: {exc}") from exc
    print(f"Installed PH-Navigator MCP bridge: {command}")
    print(f"Updated Codex MCP config: {config_path}")
    print(f"Updated Codex instructions: {agents_path}")


if __name__ == "__main__":
    main()
