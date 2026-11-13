"""Manage `herdr-obsidian` keybindings in `config.toml` and `keys.json`."""

from __future__ import annotations

import json
import os
import re
import tomllib
from pathlib import Path
from typing import Any

DEFAULT_KEY = "prefix+u"
DEFAULT_APP_KEY = "ctrl-shift-o"
APP_ACTION: dict[str, Any] = {
    "command": "pane.split",
    "args": {"direction": "right", "mod": "herdr-obsidian"},
}
BEGIN = "# >>> herdr-obsidian keys (managed by `herdr-obsidian setup-keys`) >>>"
END = "# <<< herdr-obsidian keys <<<"
ACTION = "herdr-obsidian.open"


def config_path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    path = Path(base) / "herdr" / "config.toml"
    return path.resolve() if path.is_symlink() else path


def _strip_block(text: str) -> str:
    return re.sub(rf"\n?{re.escape(BEGIN)}.*?{re.escape(END)}\n?", "\n", text, flags=re.DOTALL)


def block(key: str) -> str:
    return (
        f"{BEGIN}\n"
        "[[keys.command]]\n"
        f'key = "{key}"\n'
        'type = "plugin_action"\n'
        f'command = "{ACTION}"\n'
        'description = "Obsidian: open vault beside this pane"\n'
        f"{END}\n"
    )


def installed_key(text: str) -> str | None:
    match = re.search(rf'{re.escape(BEGIN)}.*?key = "([^"]+)".*?{re.escape(END)}', text, re.DOTALL)
    return match.group(1) if match else None


def setup(key: str | None = None, *, remove: bool = False, path: Path | None = None) -> tuple[bool, str]:
    target = path or config_path()
    text = target.read_text(encoding="utf-8") if target.is_file() else ""
    current = installed_key(text)

    if remove:
        if current is None:
            return False, f"no herdr-obsidian keybinding in {target}"
        new = _strip_block(text).rstrip("\n") + "\n"
        message = f"removed the {current} keybinding from {target}"
    else:
        chosen = (key or DEFAULT_KEY).lower()
        if current == chosen:
            return False, f"{chosen} already opens the Obsidian Vault ({target})"
        stripped = _strip_block(text).rstrip("\n")
        new = (stripped + "\n\n" if stripped else "") + block(chosen)
        message = f"{chosen} now opens the Obsidian Vault (added to {target})"

    try:
        tomllib.loads(new)
    except tomllib.TOMLDecodeError as exc:
        return False, f"refusing to write invalid config.toml: {exc}"

    if target.is_file():
        backup = target.with_name(target.name + ".bak-herdr-obsidian")
        backup.write_text(text, encoding="utf-8")
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    tmp.write_text(new, encoding="utf-8")
    if target.is_file():
        os.chmod(tmp, target.stat().st_mode & 0o777)
    os.replace(tmp, target)
    return True, message


def app_keys_path(home: Path | None = None) -> Path:
    env_home = os.environ.get("HERDR_APP_HOME")
    if env_home and home is None:
        path = Path(env_home) / "keys.json"
    else:
        xdg = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
        base = (home / ".config") if home else Path(xdg)
        path = base / "herdr-app" / "keys.json"
    return path.resolve() if path.is_symlink() else path


def _is_obsidian_app_action(value: Any) -> bool:
    if isinstance(value, str):
        return value in (
            "mod.open:herdr-obsidian",
            "tab.new:herdr-obsidian",
            "pane.split:herdr-obsidian",
        )
    if isinstance(value, dict):
        cmd = value.get("command") or value.get("action")
        args = value.get("args") if isinstance(value.get("args"), dict) else value
        if cmd == "mod.open" and args.get("name") == "herdr-obsidian":
            return True
        if cmd in ("tab.new", "pane.split") and args.get("mod") == "herdr-obsidian":
            return True
        if cmd == "layout.toggle" and args.get("id") in ("herdr-obsidian", "obsidian-panel"):
            return True
    return False


def installed_app_key(data: dict[str, Any]) -> str | None:
    global_sec = data.get("global")
    if isinstance(global_sec, dict):
        for chord, action in global_sec.items():
            if _is_obsidian_app_action(action):
                return chord
    for chord, action in data.items():
        if _is_obsidian_app_action(action):
            return chord
    return None


def setup_app_keys(
    key: str | None = None,
    *,
    remove: bool = False,
    path: Path | None = None,
    action: str | dict[str, Any] = APP_ACTION,
) -> tuple[bool, str]:
    target = path or app_keys_path()
    raw = target.read_text(encoding="utf-8") if target.is_file() else "{}"
    try:
        loaded = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError as exc:
        return False, f"refusing to modify invalid keys.json ({target}): {exc}"
    if not isinstance(loaded, dict):
        return False, f"refusing to modify non-object keys.json ({target})"

    data: dict[str, Any] = dict(loaded)
    global_sec: dict[str, Any] = dict(data["global"]) if isinstance(data.get("global"), dict) else {}
    current = installed_app_key(data)

    if remove:
        if current is None:
            return False, f"no herdr-obsidian keybinding in {target}"
        for k in [k for k, v in global_sec.items() if _is_obsidian_app_action(v)]:
            if k == "ctrl-shift-o":
                global_sec[k] = "pane.split:right"
            else:
                global_sec.pop(k, None)
        for k in [k for k, v in data.items() if _is_obsidian_app_action(v)]:
            data.pop(k, None)
        if isinstance(data.get("mod:herdr-obsidian"), dict):
            mod_sec = dict(data["mod:herdr-obsidian"])
            mod_sec.pop(current, None)
            if mod_sec:
                data["mod:herdr-obsidian"] = mod_sec
            else:
                data.pop("mod:herdr-obsidian", None)
        if global_sec or "global" in data:
            data["global"] = global_sec
        message = f"removed the {current} keybinding from {target}"
    else:
        chosen = (key or DEFAULT_APP_KEY).strip().lower()
        if current == chosen and global_sec.get(chosen) == action:
            return False, f"{chosen} already opens the Obsidian Vault ({target})"
        existing = global_sec.get(chosen)
        # Allow upgrading default ctrl-shift-o ("pane.split:right")
        if (
            existing is not None
            and not _is_obsidian_app_action(existing)
            and not (chosen == "ctrl-shift-o" and existing == "pane.split:right")
        ):
            return (
                False,
                f"{chosen} is already bound to {existing!r} in {target}. "
                "Pick another chord with `herdr-obsidian setup-keys --app --key <chord>`.",
            )
        for k in [k for k, v in global_sec.items() if _is_obsidian_app_action(v)]:
            if k == "ctrl-shift-o" and chosen != "ctrl-shift-o":
                global_sec[k] = "pane.split:right"
            else:
                global_sec.pop(k, None)
        for k in [k for k, v in data.items() if _is_obsidian_app_action(v)]:
            data.pop(k, None)
        global_sec[chosen] = action
        data["global"] = global_sec
        mod_sec = dict(data["mod:herdr-obsidian"]) if isinstance(data.get("mod:herdr-obsidian"), dict) else {}
        mod_sec[chosen] = "pane.close"
        data["mod:herdr-obsidian"] = mod_sec
        message = f"{chosen} now toggles the docked Obsidian Vault in herdr-app ({target})"

    rendered = json.dumps(data, indent=2) + "\n"
    if target.is_file():
        backup = target.with_name(target.name + ".bak-herdr-obsidian")
        backup.write_text(raw, encoding="utf-8")
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    tmp.write_text(rendered, encoding="utf-8")
    if target.is_file():
        os.chmod(tmp, target.stat().st_mode & 0o777)
    os.replace(tmp, target)
    return True, message
