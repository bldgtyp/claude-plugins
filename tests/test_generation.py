from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

sys.path.insert(0, str(ROOT / "scripts"))

from check_contract import check  # noqa: E402
from generate import generate  # noqa: E402
from sync_project_folder import sync  # noqa: E402


class GenerationTests(unittest.TestCase):
    def test_generated_outputs_are_current(self) -> None:
        self.assertEqual(generate(check=True), 0)

    def test_contract_check_detects_no_required_tool_drift(self) -> None:
        self.assertEqual(check(ROOT / "contract" / "phn-mcp.md"), [])

    def test_plugin_mcp_config_uses_the_runtime_validated_direct_map(self) -> None:
        config = json.loads(
            (ROOT / "plugins" / "bldgtyp" / ".mcp.json").read_text(encoding="utf-8")
        )
        self.assertIn("phn", config)
        self.assertNotIn("mcpServers", config)

    def test_folder_sync_preserves_existing_project_id(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            marker = {
                "phn_project_id": "project-id",
                "phn_api": "https://old.example.test",
                "phn_web": "https://old.example.test",
            }
            (target / ".phn.json").write_text(json.dumps(marker), encoding="utf-8")

            sync(target)

            updated = json.loads((target / ".phn.json").read_text(encoding="utf-8"))
            self.assertEqual(updated["phn_project_id"], "project-id")
            self.assertEqual(updated["phn_api"], "https://api.ph-nav.com")
            self.assertTrue((target / "CLAUDE.md").exists())
            self.assertTrue((target / "AGENTS.md").exists())


if __name__ == "__main__":
    unittest.main()
