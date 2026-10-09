from __future__ import annotations

import json
import os
import sys
import tempfile
import tomllib
import unittest
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "prepared_distribution"))

from host_connect import HostConnectError, connect_host, default_config_path  # noqa: E402
from prepared_runtime import PreparedSetupError, setup_prepared  # noqa: E402


COMMAND = r"C:\Prepared library ü\.venv\Scripts\python.exe"
ARGUMENTS = ["-I", r"C:\Prepared library ü\run_mcp.py"]
NOW = datetime(2026, 10, 9, 12, 0, 0, tzinfo=timezone.utc)


class DefaultLocationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="standardsforge-host-paths-")
        self.home = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_documented_locations_require_an_installed_host(self) -> None:
        appdata = self.home / "AppData" / "Roaming"
        with self.assertRaisesRegex(HostConnectError, "does not exist"):
            default_config_path("claude-desktop", platform="win32", environment={"APPDATA": str(appdata)}, home=self.home)
        (appdata / "Claude").mkdir(parents=True)
        self.assertEqual(appdata / "Claude" / "claude_desktop_config.json",
                         default_config_path("claude-desktop", platform="win32", environment={"APPDATA": str(appdata)}, home=self.home))
        mac = self.home / "Library" / "Application Support" / "Claude"
        mac.mkdir(parents=True)
        self.assertEqual(mac / "claude_desktop_config.json",
                         default_config_path("claude-desktop", platform="darwin", environment={}, home=self.home))
        with self.assertRaisesRegex(HostConnectError, "no documented configuration location"):
            default_config_path("claude-desktop", platform="linux", environment={}, home=self.home)
        with self.assertRaisesRegex(HostConnectError, "APPDATA is not set"):
            default_config_path("claude-desktop", platform="win32", environment={}, home=self.home)

    def test_cursor_and_codex_locations(self) -> None:
        with self.assertRaisesRegex(HostConnectError, "does not exist"):
            default_config_path("cursor", platform="linux", environment={}, home=self.home)
        (self.home / ".cursor").mkdir()
        self.assertEqual(self.home / ".cursor" / "mcp.json", default_config_path("cursor", platform="linux", environment={}, home=self.home))
        custom = self.home / "codex-home"
        custom.mkdir()
        self.assertEqual(custom / "config.toml",
                         default_config_path("codex", platform="linux", environment={"CODEX_HOME": str(custom)}, home=self.home))
        with self.assertRaisesRegex(HostConnectError, "Unknown model host"):
            default_config_path("other", platform="linux", environment={}, home=self.home)


class ConnectHostTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="standardsforge-host-connect-")
        self.root = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _backups(self) -> list[Path]:
        return sorted(self.root.glob("*.standardsforge-backup-*"))

    def test_json_creates_new_file_without_backup(self) -> None:
        path = self.root / "claude_desktop_config.json"
        result = connect_host("claude-desktop", COMMAND, ARGUMENTS, config_path=path, now=NOW)
        self.assertEqual(("connected", None), (result["status"], result["backup_path"]))
        self.assertEqual({"mcpServers": {"standardsforge": {"command": COMMAND, "args": ARGUMENTS}}},
                         json.loads(path.read_text(encoding="utf-8")))

    def test_json_preserves_other_entries_and_backs_up_exact_bytes(self) -> None:
        path = self.root / "mcp.json"
        original = '\ufeff{"theme": "dark", "mcpServers": {"other": {"command": "x"}, "standardsforge": {"command": "old"}}}'
        path.write_text(original, encoding="utf-8")
        before = path.read_bytes()
        result = connect_host("cursor", COMMAND, ARGUMENTS, config_path=path, now=NOW)
        self.assertEqual("updated", result["status"])
        backup = Path(result["backup_path"])
        self.assertEqual(before, backup.read_bytes())
        self.assertTrue(backup.name.endswith("standardsforge-backup-20261009T120000Z"))
        document = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual("dark", document["theme"])
        self.assertEqual({"command": "x"}, document["mcpServers"]["other"])
        self.assertEqual({"command": COMMAND, "args": ARGUMENTS}, document["mcpServers"]["standardsforge"])
        again = connect_host("cursor", COMMAND, ARGUMENTS, config_path=path, now=NOW)
        self.assertEqual(("already_connected", None), (again["status"], again["backup_path"]))
        self.assertEqual([backup], self._backups())

    def test_json_that_cannot_be_merged_is_left_untouched(self) -> None:
        path = self.root / "mcp.json"
        for content, message in (('{"mcpServers": [', "not valid JSON"), ("[1, 2]", "JSON object"), ('{"mcpServers": []}', "not an object")):
            path.write_text(content, encoding="utf-8")
            with self.assertRaisesRegex(HostConnectError, message):
                connect_host("cursor", COMMAND, ARGUMENTS, config_path=path, now=NOW)
            self.assertEqual(content, path.read_text(encoding="utf-8"))
        self.assertEqual([], self._backups())
        path.write_bytes(b"\xff\xfe{}")
        with self.assertRaisesRegex(HostConnectError, "not UTF-8"):
            connect_host("cursor", COMMAND, ARGUMENTS, config_path=path, now=NOW)

    def test_toml_replaces_only_its_own_tables(self) -> None:
        path = self.root / "config.toml"
        original = (
            'model = "example"\n\n'
            "[mcp_servers.other]\ncommand = \"other\"\n\n"
            "[mcp_servers.standardsforge]\ncommand = \"old\"\nargs = []\n\n"
            "[mcp_servers.standardsforge.env]\nKEY = \"value\"\n\n"
            "[profiles.fast]\nmodel = \"small\"\n"
        )
        path.write_text(original, encoding="utf-8")
        result = connect_host("codex", COMMAND, ARGUMENTS, config_path=path, now=NOW)
        self.assertEqual("updated", result["status"])
        self.assertEqual(original, Path(result["backup_path"]).read_text(encoding="utf-8"))
        parsed = tomllib.loads(path.read_text(encoding="utf-8"))
        self.assertEqual("example", parsed["model"])
        self.assertEqual({"model": "small"}, parsed["profiles"]["fast"])
        self.assertEqual({"command": "other"}, parsed["mcp_servers"]["other"])
        self.assertEqual({"command": COMMAND, "args": ARGUMENTS}, parsed["mcp_servers"]["standardsforge"])
        self.assertEqual("already_connected", connect_host("codex", COMMAND, ARGUMENTS, config_path=path, now=NOW)["status"])

    def test_toml_forms_that_cannot_be_rewritten_safely_fail_closed(self) -> None:
        path = self.root / "config.toml"
        for content, message in (
            ('mcp_servers = { standardsforge = { command = "old" } }\n', "cannot rewrite safely"),
            ('[mcp_servers]\nstandardsforge.command = "old"\n', "cannot rewrite safely"),
            ("[mcp_servers\n", "not valid TOML"),
            ('mcp_servers = "text"\n', "not a table"),
        ):
            path.write_text(content, encoding="utf-8")
            with self.assertRaisesRegex(HostConnectError, message):
                connect_host("codex", COMMAND, ARGUMENTS, config_path=path, now=NOW)
            self.assertEqual(content, path.read_text(encoding="utf-8"))
        self.assertEqual([], self._backups())

    @unittest.skipIf(os.name == "nt", "symbolic links need privileges on Windows")
    def test_symbolic_link_to_dotfiles_is_preserved(self) -> None:
        real = self.root / "dotfiles"
        real.mkdir()
        target = real / "config.toml"
        target.write_text('model = "example"\n', encoding="utf-8")
        link = self.root / "config.toml"
        link.symlink_to(target)
        connect_host("codex", COMMAND, ARGUMENTS, config_path=link, now=NOW)
        self.assertTrue(link.is_symlink())
        self.assertIn("standardsforge", tomllib.loads(target.read_text(encoding="utf-8"))["mcp_servers"])

    def test_explicit_location_needs_an_existing_folder(self) -> None:
        with self.assertRaisesRegex(HostConnectError, "does not exist; it was not created"):
            connect_host("cursor", COMMAND, ARGUMENTS, config_path=self.root / "missing" / "mcp.json", now=NOW)

    def test_setup_rejects_connect_without_model_connection_before_any_work(self) -> None:
        with self.assertRaisesRegex(PreparedSetupError, "--connect needs the model connection"):
            setup_prepared(self.root, quiet=True, connect=["cursor"])
        with self.assertRaisesRegex(PreparedSetupError, "exactly one --connect"):
            setup_prepared(self.root, quiet=True, mcp_mode="online", connect=["cursor", "codex"], host_config=self.root / "x.json")
        self.assertEqual([], list(self.root.iterdir()))


if __name__ == "__main__":
    unittest.main()
