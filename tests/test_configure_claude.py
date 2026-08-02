from __future__ import annotations

import json
import stat
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from configure_claude import ConfigureError, MINIMUM_MCP_TIMEOUT_MS, configure  # noqa: E402


class ConfigureClaudeTests(unittest.TestCase):
    def test_configure_preserves_unrelated_settings_and_mode(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            settings = Path(directory) / "settings.json"
            settings.write_text(
                json.dumps(
                    {
                        "env": {"EXISTING": "value"},
                        "enabledPlugins": {"example@test": True},
                    }
                ),
                encoding="utf-8",
            )
            settings.chmod(0o640)

            self.assertTrue(configure(settings))

            payload = json.loads(settings.read_text(encoding="utf-8"))
            self.assertEqual(payload["env"]["EXISTING"], "value")
            self.assertEqual(payload["env"]["MCP_TIMEOUT"], str(MINIMUM_MCP_TIMEOUT_MS))
            self.assertTrue(payload["enabledPlugins"]["example@test"])
            self.assertEqual(stat.S_IMODE(settings.stat().st_mode), 0o640)

    def test_configure_is_idempotent_and_preserves_higher_timeout(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            settings = Path(directory) / "settings.json"
            settings.write_text(
                json.dumps({"env": {"MCP_TIMEOUT": "900000"}}) + "\n",
                encoding="utf-8",
            )
            before = settings.read_text(encoding="utf-8")

            self.assertFalse(configure(settings))
            self.assertEqual(settings.read_text(encoding="utf-8"), before)

    def test_configure_rejects_malformed_env(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            settings = Path(directory) / "settings.json"
            settings.write_text('{"env": []}\n', encoding="utf-8")

            with self.assertRaisesRegex(ConfigureError, "env"):
                configure(settings)


if __name__ == "__main__":
    unittest.main()
