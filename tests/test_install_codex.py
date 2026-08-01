from __future__ import annotations

import stat
import shutil
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import install_codex  # noqa: E402
from codex_install_contract import LOGIN_COMMAND_PLACEHOLDER  # noqa: E402
from install_codex import (  # noqa: E402
    AGENTS_END,
    AGENTS_START,
    CONFIG_END,
    CONFIG_START,
    InstallError,
    install,
)


class CodexInstallTests(unittest.TestCase):
    def test_install_is_idempotent_and_preserves_unmanaged_content(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            codex_home = root / "codex"
            data_home = root / "data"
            codex_home.mkdir()
            config = codex_home / "config.toml"
            agents = codex_home / "AGENTS.md"
            config.write_text('model = "test"\n', encoding="utf-8")
            config.chmod(0o640)
            agents.write_text("# Existing instructions\n", encoding="utf-8")

            first = install(codex_home=codex_home, data_home=data_home)
            first_config = config.read_text(encoding="utf-8")
            first_agents = agents.read_text(encoding="utf-8")
            watched = [
                config,
                agents,
                first[2],
                first[2].parents[1] / "lib/phn_agent.py",
            ]
            mtimes = {path: path.stat().st_mtime_ns for path in watched}
            releases = first[2].parents[2]
            older_release = releases / "0000000000000000"
            fallback_release = releases / "1111111111111111"
            shutil.copytree(first[2].parents[1], older_release)
            shutil.copytree(first[2].parents[1], fallback_release)
            older_release.touch()
            fallback_release.touch()
            second = install(codex_home=codex_home, data_home=data_home)

            self.assertEqual(first, second)
            self.assertEqual(config.read_text(encoding="utf-8"), first_config)
            self.assertEqual(agents.read_text(encoding="utf-8"), first_agents)
            self.assertIn('model = "test"', first_config)
            self.assertIn("# Existing instructions", first_agents)
            self.assertEqual(first_config.count(CONFIG_START), 1)
            self.assertEqual(first_config.count(CONFIG_END), 1)
            parsed = tomllib.loads(first_config)
            self.assertEqual(parsed["mcp_servers"]["phn"]["command"], str(first[2]))
            self.assertEqual(
                parsed["mcp_servers"]["phn"]["env"]["PHN_AGENT_CLIENT"],
                "Codex",
            )
            self.assertEqual(first_agents.count(AGENTS_START), 1)
            self.assertEqual(first_agents.count(AGENTS_END), 1)
            self.assertNotIn(LOGIN_COMMAND_PLACEHOLDER, first_agents)
            self.assertIn(str(first[2].with_name("phn-login")), first_agents)
            self.assertEqual(stat.S_IMODE(config.stat().st_mode), 0o640)
            self.assertTrue(first[2].is_file())
            self.assertTrue(first[2].stat().st_mode & stat.S_IXUSR)
            self.assertEqual(first[2].parents[2].name, "releases")
            self.assertEqual(
                {path: path.stat().st_mtime_ns for path in watched},
                mtimes,
            )
            self.assertFalse(older_release.exists())
            self.assertTrue(fallback_release.exists())

    def test_install_refuses_unmanaged_phn_server(self) -> None:
        variants = [
            '[mcp_servers.phn]\ncommand = "custom"\n',
            '[mcp_servers."phn"]\ncommand = "custom"\n',
            '[mcp_servers]\nphn = { command = "custom" }\n',
        ]
        for content in variants:
            with (
                self.subTest(content=content),
                tempfile.TemporaryDirectory() as directory,
            ):
                root = Path(directory)
                codex_home = root / "codex"
                codex_home.mkdir()
                (codex_home / "config.toml").write_text(content, encoding="utf-8")

                with self.assertRaisesRegex(InstallError, "unmanaged"):
                    install(codex_home=codex_home, data_home=root / "data")

    def test_install_rejects_malformed_managed_agents_section(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            codex_home = root / "codex"
            codex_home.mkdir()
            (codex_home / "AGENTS.md").write_text(
                f"{AGENTS_START}\ntruncated\n", encoding="utf-8"
            )

            with self.assertRaisesRegex(InstallError, "Malformed managed section"):
                install(codex_home=codex_home, data_home=root / "data")

    def test_install_rejects_reversed_managed_markers(self) -> None:
        variants = {
            "config.toml": f"{CONFIG_END}\n{CONFIG_START}\n",
            "AGENTS.md": f"{AGENTS_END}\n{AGENTS_START}\n",
        }
        for filename, content in variants.items():
            with (
                self.subTest(filename=filename),
                tempfile.TemporaryDirectory() as directory,
            ):
                root = Path(directory)
                codex_home = root / "codex"
                codex_home.mkdir()
                (codex_home / filename).write_text(content, encoding="utf-8")

                with self.assertRaisesRegex(InstallError, "precedes"):
                    install(codex_home=codex_home, data_home=root / "data")

    def test_config_write_failure_rolls_back_agents(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            codex_home = root / "codex"
            codex_home.mkdir()
            config = codex_home / "config.toml"
            agents = codex_home / "AGENTS.md"
            config.write_text('model = "test"\n', encoding="utf-8")
            agents.write_text("# Existing instructions\n", encoding="utf-8")
            original_write = install_codex._atomic_write

            def fail_config(
                path: Path, content: str, *, mode: int | None = None
            ) -> None:
                if path == config:
                    raise OSError("simulated config failure")
                original_write(path, content, mode=mode)

            with (
                patch.object(install_codex, "_atomic_write", side_effect=fail_config),
                self.assertRaisesRegex(OSError, "simulated config failure"),
            ):
                install(codex_home=codex_home, data_home=root / "data")

            self.assertEqual(config.read_text(encoding="utf-8"), 'model = "test"\n')
            self.assertEqual(
                agents.read_text(encoding="utf-8"), "# Existing instructions\n"
            )


if __name__ == "__main__":
    unittest.main()
