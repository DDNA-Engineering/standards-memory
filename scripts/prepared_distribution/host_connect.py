"""Explicitly requested registration of the prepared MCP launcher in a model host.

Setup never edits host settings unless the person running it names the host. The
existing file is parsed first, backed up byte-for-byte, changed only in the
``standardsforge`` entry, re-parsed to prove nothing else changed, and replaced
atomically. Anything that cannot be proven safe is left untouched.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import sys
import tomllib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


HOSTS = ("claude-desktop", "cursor", "codex")
SERVER_NAME = "standardsforge"
RESTART_HINT = {
    "claude-desktop": "Quit Claude Desktop completely and open it again.",
    "cursor": "Restart Cursor or reload its MCP servers.",
    "codex": "Start a new Codex session.",
}


class HostConnectError(RuntimeError):
    pass


def default_config_path(host: str, *, platform: str | None = None, environment: dict[str, str] | None = None,
                        home: Path | None = None) -> Path:
    """Return the documented per-user configuration file for ``host``.

    The host's own settings directory must already exist, which shows the host is
    installed for this user; setup never invents a configuration location.
    """
    platform = platform or sys.platform
    environment = os.environ if environment is None else environment
    home = home or Path.home()
    if host == "claude-desktop":
        if platform == "win32":
            appdata = environment.get("APPDATA")
            if not appdata:
                raise HostConnectError("APPDATA is not set, so the Claude Desktop settings folder is unknown. Pass --host-config with its config file.")
            directory = Path(appdata) / "Claude"
        elif platform == "darwin":
            directory = home / "Library" / "Application Support" / "Claude"
        else:
            raise HostConnectError("Claude Desktop has no documented configuration location on this platform. Pass --host-config with its config file.")
        path = directory / "claude_desktop_config.json"
    elif host == "cursor":
        directory = home / ".cursor"
        path = directory / "mcp.json"
    elif host == "codex":
        codex_home = environment.get("CODEX_HOME")
        directory = Path(codex_home) if codex_home else home / ".codex"
        path = directory / "config.toml"
    else:
        raise HostConnectError(f"Unknown model host: {host}")
    if not directory.is_dir():
        raise HostConnectError(
            f"The {host} settings folder {directory} does not exist. Install and open {host} once, "
            "or pass --host-config with the configuration file to change."
        )
    return path


def _read_text(path: Path) -> tuple[str | None, bytes | None]:
    if not path.exists():
        return None, None
    if not path.is_file():
        raise HostConnectError(f"{path} is not a regular file; it was not changed.")
    raw = path.read_bytes()
    try:
        return raw.decode("utf-8-sig"), raw
    except UnicodeDecodeError as exc:
        raise HostConnectError(f"{path} is not UTF-8 text; it was not changed.") from exc


def _json_document(original: str | None, command: str, arguments: list[str], path: Path) -> tuple[str, bool, bool]:
    try:
        document = json.loads(original) if original is not None and original.strip() else {}
    except json.JSONDecodeError as exc:
        raise HostConnectError(f"{path} is not valid JSON (line {exc.lineno}); fix it first. It was not changed.") from exc
    if not isinstance(document, dict):
        raise HostConnectError(f"{path} does not contain a JSON object; it was not changed.")
    servers = document.setdefault("mcpServers", {})
    if not isinstance(servers, dict):
        raise HostConnectError(f"{path} has an mcpServers value that is not an object; it was not changed.")
    entry = {"command": command, "args": arguments}
    existed = SERVER_NAME in servers
    unchanged = servers.get(SERVER_NAME) == entry
    servers[SERVER_NAME] = entry
    return json.dumps(document, indent=2, ensure_ascii=False) + "\n", unchanged, existed


_TABLE_HEADER = re.compile(r"^\s*\[")
_OWN_HEADER = re.compile(
    r"""^\s*\[\s*mcp_servers\s*\.\s*(?:standardsforge|"standardsforge"|'standardsforge')\s*(?:\.[^\]]*)?\]\s*(?:\#.*)?$"""
)


def _toml_document(original: str | None, command: str, arguments: list[str], path: Path) -> tuple[str, bool, bool]:
    text = original or ""
    try:
        parsed = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise HostConnectError(f"{path} is not valid TOML ({exc}); fix it first. It was not changed.") from exc
    servers = parsed.get("mcp_servers", {})
    if not isinstance(servers, dict):
        raise HostConnectError(f"{path} has an mcp_servers value that is not a table; it was not changed.")
    entry = {"command": command, "args": arguments}
    existed = SERVER_NAME in servers
    if servers.get(SERVER_NAME) == entry:
        return text, True, existed
    # Remove only this server's own table (and its sub-tables), then append the new one.
    kept: list[str] = []
    skipping = False
    for line in text.splitlines(keepends=True):
        if _OWN_HEADER.match(line):
            skipping = True
            continue
        if skipping and _TABLE_HEADER.match(line):
            skipping = False
        if not skipping:
            kept.append(line)
    # Separate the appended table from the remaining content by exactly one blank line.
    updated = "".join(kept).rstrip()
    if updated:
        updated += "\n\n"
    updated += (
        f"[mcp_servers.{SERVER_NAME}]\n"
        # JSON string escaping is also valid for TOML basic strings.
        f"command = {json.dumps(command, ensure_ascii=False)}\n"
        f"args = {json.dumps(arguments, ensure_ascii=False)}\n"
    )
    expected = dict(parsed)
    expected["mcp_servers"] = {**servers, SERVER_NAME: entry}
    try:
        observed = tomllib.loads(updated)
    except tomllib.TOMLDecodeError:
        observed = None
    if observed != expected:
        raise HostConnectError(
            f"{path} defines {SERVER_NAME} in a form setup cannot rewrite safely (for example inline or dotted keys). "
            f"It was not changed; replace that definition with the generated .standardsforge/codex-mcp.toml section."
        )
    return updated, False, existed


def connect_host(host: str, command: str, arguments: list[str], *, config_path: Path | None = None,
                 now: datetime | None = None) -> dict[str, Any]:
    if host not in HOSTS:
        raise HostConnectError(f"Unknown model host: {host}")
    requested = Path(config_path) if config_path is not None else default_config_path(host)
    if config_path is not None and not requested.parent.is_dir():
        raise HostConnectError(f"The folder for {requested} does not exist; it was not created.")
    # Follow a symbolic link (for example a dotfiles checkout) so the link itself survives.
    target = Path(os.path.realpath(requested))
    original, raw = _read_text(target)
    render = _toml_document if host == "codex" else _json_document
    updated, unchanged, existed = render(original, command, arguments, target)
    result: dict[str, Any] = {"host": host, "config_path": str(requested), "restart": RESTART_HINT[host]}
    if unchanged:
        return {**result, "status": "already_connected", "backup_path": None}
    backup = None
    if raw is not None:
        stamp = (now or datetime.now(timezone.utc)).strftime("%Y%m%dT%H%M%SZ")
        backup = target.with_name(f"{target.name}.standardsforge-backup-{stamp}")
        if backup.exists():
            raise HostConnectError(f"Backup {backup} already exists; wait a second and run setup again.")
        shutil.copy2(target, backup)
    temporary = target.with_name(f".{target.name}.standardsforge.tmp")
    temporary.write_text(updated, encoding="utf-8", newline="\n")
    if raw is not None:
        shutil.copymode(target, temporary)
    os.replace(temporary, target)
    return {**result, "status": "updated" if existed else "connected", "backup_path": str(backup) if backup else None}
