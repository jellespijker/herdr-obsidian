"""Command-line interface and GPUI backend for `herdr-obsidian`."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from . import __version__, keys, skill
from .ticket_sync import (
    OBSIDIAN_MARKER_RE,
    read_spool_state,
    resolve_ticket_brief,
    state_dir,
    write_spool_state,
)
from .treemap import CATEGORY_SPECS, build_knowledge_graph, build_treemap
from .vault import (
    VaultIndex,
    diagram_cache_dir,
    discover_vault,
    extract_png_dimensions,
    find_vault_root,
)


def _notify_herdr(message: str, *, level: str = "info") -> None:
    if os.environ.get("HERDR_ENV") == "1":
        herdr_bin = shutil.which("herdr")
        if herdr_bin:
            try:
                subprocess.run(
                    [herdr_bin, "display-message", f"Obsidian Vault: {message}"],
                    capture_output=True,
                    timeout=2,
                )
                return
            except (OSError, subprocess.SubprocessError):
                pass
    notify_send = shutil.which("notify-send")
    if notify_send:
        urgency = "critical" if level == "error" else "normal"
        try:
            subprocess.run(
                [notify_send, "-u", urgency, "Obsidian Vault", message],
                capture_output=True,
                timeout=2,
            )
        except (OSError, subprocess.SubprocessError):
            pass


def _trigger_herdr_app_refresh() -> None:
    # Spool updates in ~/.local/state/herdr-obsidian/spool.json are watched
    # directly by the herdr-obsidian GPUI mod via watchFolder(); calling
    # `herdr-app do herdr-obsidian.refresh` when the mod pane is hidden triggers
    # an "unknown command 'herdr-obsidian.refresh'" error toast in herdr-app.
    return


def _detect_terminal_marker(pane: str | None) -> str | None:
    """Inspect recent lines of a herdr-core (`hc`) or `herdr` terminal for `[obsidian: <Target>]`."""
    if not pane:
        return None
    hc_bin = shutil.which("hc") or shutil.which("herdr-core")
    if hc_bin:
        try:
            proc = subprocess.run(
                [hc_bin, "read", pane, "--lines", "45"],
                capture_output=True,
                text=True,
                timeout=2,
            )
            if proc.returncode == 0 and proc.stdout:
                matches = OBSIDIAN_MARKER_RE.findall(proc.stdout)
                if matches:
                    return matches[-1].strip()
        except (OSError, subprocess.SubprocessError):
            pass
    return None


def _build_folder_tree(index: VaultIndex) -> list[dict[str, Any]]:
    """Return a sorted list of folders and their notes for fast tree rendering in GPUI."""
    folders: dict[str, list[dict[str, Any]]] = {}
    for rel, note in sorted(index.notes.items()):
        top = rel.split("/", 1)[0] if "/" in rel else "(root)"
        folders.setdefault(top, []).append(
            {
                "relpath": rel,
                "title": note.title,
                "folder": note.folder,
                "level": note.level,
                "category": note.category,
                "in_degree": len(note.in_links),
                "out_degree": len(note.out_links),
            }
        )
    out: list[dict[str, Any]] = []
    for folder_name, items in sorted(folders.items()):
        out.append(
            {
                "folder": folder_name,
                "count": len(items),
                "category": items[0]["category"] if items else "general",
                "items": items,
            }
        )
    return out


def _ensure_local_asset_cache(index: VaultIndex, note_payload: dict[str, Any] | None) -> None:
    """Copy local embedded SVG/PNG assets into `~/.config/herdr-app/data/obsidian-cache/`."""
    if not note_payload:
        return
    env_home = os.environ.get("HERDR_APP_HOME")
    app_home = Path(env_home) if env_home else (Path.home() / ".config" / "herdr-app")
    if not app_home.is_dir():
        return
    cache_dir = app_home / "data" / "obsidian-cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    for block in note_payload.get("blocks", []):
        btype = block.get("type")
        cache_name = block.get("cache_name")
        if not cache_name:
            continue
        dst = cache_dir / cache_name
        if dst.is_file():
            continue
        if btype == "image":
            rel = block.get("relpath")
            if not rel:
                continue
            src = (index.vault_root / rel).resolve()
            if src.is_file() and index.vault_root in src.parents:
                try:
                    tmp = cache_dir / f".{cache_name}.{os.getpid()}.tmp"
                    tmp.write_bytes(src.read_bytes())
                    os.replace(tmp, dst)
                except OSError:
                    pass
        elif btype == "diagram":
            src = diagram_cache_dir() / cache_name
            if src.is_file():
                try:
                    tmp = cache_dir / f".{cache_name}.{os.getpid()}.tmp"
                    tmp.write_bytes(src.read_bytes())
                    os.replace(tmp, dst)
                except OSError:
                    pass


def cmd_app_state(args: argparse.Namespace) -> int:
    cwd = Path(args.cwd or os.getcwd()).expanduser().resolve()
    vault_root = find_vault_root(cwd, args.vault)
    spool = read_spool_state()
    if vault_root is None:
        print(
            json.dumps(
                {
                    "ok": True,
                    "has_vault": False,
                    "version": __version__,
                    "vault_root": None,
                    "vault_name": None,
                    "cwd": str(cwd),
                    "spool_dir": str(state_dir()),
                    "spool_seq": int(spool.get("seq", 0)),
                    "spool_view": spool.get("view"),
                    "spool_ticket": spool.get("ticket"),
                    "spool": spool,
                    "marker_target": None,
                    "stats": {
                        "total_notes": 0,
                        "total_canvases": 0,
                        "total_assets": 0,
                        "total_links": 0,
                    },
                    "categories": CATEGORY_SPECS,
                    "bookmarks": [],
                    "tree": [],
                    "canvases": [],
                    "active_note": None,
                    "search_results": [],
                    "treemap": {"rects": [], "folders": []},
                    "graph": {"nodes": [], "edges": []},
                    "canvas": None,
                    "ticket_brief": None,
                }
            )
        )
        return 0

    index = VaultIndex(vault_root)

    spool_seq = int(spool.get("seq", 0))
    known_seq = int(getattr(args, "spool_seq", 0) or 0)
    spool_updated = bool(args.follow_sync and spool_seq > known_seq)
    marker_target = _detect_terminal_marker(args.pane) if args.follow_sync else None

    requested_note = None if spool_updated else args.note
    if not requested_note and args.follow_sync:
        if spool.get("relpath"):
            requested_note = str(spool["relpath"])
        elif marker_target:
            requested_note = marker_target
    if not requested_note and args.note:
        requested_note = args.note

    active_rel = index.resolve_note(requested_note) if requested_note else None
    if not active_rel or active_rel not in index.notes:
        active_rel = index.default_home_note()

    note_payload = index.render_note_payload(active_rel) if active_rel else None
    _ensure_local_asset_cache(index, note_payload)

    query = (args.query or "").strip()
    search_results = index.search(
        query,
        tag=args.tag,
        level=args.level,
        category=args.category,
        limit=80,
    )

    treemap_data = build_treemap(
        index,
        width=max(320, int(args.width or 880)),
        height=max(240, int(args.height or 520)),
        metric=args.metric or "bytes",
        zoom_folder=args.zoom_folder or "",
        level_filter=args.level,
    )

    graph_data = build_knowledge_graph(
        index,
        center_relpath=active_rel,
        mode=args.graph_mode or "local",
    )

    canvas_target = (spool.get("canvas") if spool_updated else args.canvas) or spool.get("canvas")
    canvas_data = index.load_canvas(canvas_target)

    active_ticket = (
        (spool.get("ticket") if spool_updated else args.ticket)
        or args.ticket
        or spool.get("ticket")
    )
    ticket_brief = resolve_ticket_brief(index, cwd, active_ticket)

    payload = {
        "ok": True,
        "has_vault": True,
        "version": __version__,
        "vault_root": str(vault_root),
        "vault_name": f"{vault_root.parent.name}/{vault_root.name}"
        if vault_root.name == "docs"
        else vault_root.name,
        "spool_dir": str(state_dir()),
        "spool_seq": int(spool.get("seq", 0)),
        "spool_view": spool.get("view"),
        "spool_ticket": spool.get("ticket"),
        "spool": spool,
        "marker_target": marker_target,
        "stats": {
            "total_notes": len(index.notes),
            "total_canvases": len(index.canvases),
            "total_assets": len({p for p in index.assets.values()}),
            "total_links": sum(len(n.out_links) for n in index.notes.values()),
        },
        "categories": CATEGORY_SPECS,
        "bookmarks": index.load_bookmarks(),
        "tree": _build_folder_tree(index),
        "canvases": index.canvases,
        "active_note": note_payload,
        "search_results": search_results,
        "treemap": treemap_data,
        "graph": graph_data,
        "canvas": canvas_data,
        "ticket_brief": ticket_brief,
    }
    print(json.dumps(payload))
    return 0


def cmd_app_artifact(args: argparse.Namespace) -> int:
    cwd = Path(args.cwd or os.getcwd()).expanduser().resolve()
    vault_root = discover_vault(cwd, args.vault)
    index = VaultIndex(vault_root)
    asset_path = index.resolve_asset(args.asset)
    if not asset_path or not asset_path.is_file():
        print(json.dumps({"ok": False, "error": f"Asset not found: {args.asset}"}))
        return 1
    raw = asset_path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()[:20]
    ext = asset_path.suffix.lower()
    print(
        json.dumps(
            {
                "ok": True,
                "cache_name": f"{digest}{ext}",
                "ext": ext,
                "b64": base64.b64encode(raw).decode("ascii"),
            }
        )
    )
    return 0


def cmd_render_diagram(args: argparse.Namespace) -> int:
    """Render a Mermaid/D2/PlantUML/Graphviz block to a cached dark-theme PNG and return base64 + dims."""
    cache_name = os.path.basename(str(args.cache_name or "")).strip()
    if not cache_name.startswith("diag-") or not cache_name.endswith(".png"):
        print(json.dumps({"ok": False, "error": f"Invalid diagram cache name: {cache_name}"}))
        return 1

    cache_dir = diagram_cache_dir()
    dst_png = cache_dir / cache_name

    if not dst_png.is_file():
        fmt = (args.format or "mermaid").strip().lower()
        source = args.source
        if not source and args.note:
            cwd = Path(args.cwd or os.getcwd()).expanduser().resolve()
            vault_root = discover_vault(cwd, args.vault)
            index = VaultIndex(vault_root)
            resolved = index.resolve_note(args.note)
            if resolved:
                payload = index.render_note_payload(resolved)
                for blk in (payload or {}).get("blocks", []):
                    if blk.get("type") == "diagram" and blk.get("cache_name") == cache_name:
                        source = str(blk.get("source") or "")
                        fmt = str(blk.get("format") or fmt)
                        break

        if not source:
            print(json.dumps({"ok": False, "error": f"Diagram source not found for {cache_name}"}))
            return 1

        herdr_diag = shutil.which("herdr-diagram") or str(Path.home() / ".local" / "bin" / "herdr-diagram")
        if not os.access(herdr_diag, os.X_OK):
            print(json.dumps({"ok": False, "error": "herdr-diagram binary not found"}))
            return 1

        ext_map = {
            "mermaid": ".mmd",
            "d2": ".d2",
            "plantuml": ".puml",
            "graphviz": ".dot",
            "structurizr": ".dsl",
        }
        in_ext = ext_map.get(fmt, ".mmd")
        with tempfile.TemporaryDirectory(prefix="herdr-obs-diag-") as td:
            td_path = Path(td)
            in_file = td_path / f"diagram{in_ext}"
            out_file = td_path / "rendered.png"
            in_file.write_text(source, encoding="utf-8")
            proc = subprocess.run(
                [
                    herdr_diag,
                    "render",
                    "-f",
                    fmt,
                    "--theme",
                    "dark",
                    "-o",
                    str(out_file),
                    str(in_file),
                ],
                capture_output=True,
                text=True,
                timeout=35,
            )
            if proc.returncode != 0 or not out_file.is_file():
                err_msg = (proc.stderr or proc.stdout or "herdr-diagram render failed").strip()
                print(json.dumps({"ok": False, "error": err_msg}))
                return 1
            tmp_dst = cache_dir / f".{cache_name}.{os.getpid()}.tmp"
            tmp_dst.write_bytes(out_file.read_bytes())
            os.replace(tmp_dst, dst_png)

    raw = dst_png.read_bytes()
    dims = extract_png_dimensions(raw[:32]) or (1600, 480)

    # Also populate local ~/.config/herdr-app/data/obsidian-cache/ if available
    env_home = os.environ.get("HERDR_APP_HOME")
    app_home = Path(env_home) if env_home else (Path.home() / ".config" / "herdr-app")
    if app_home.is_dir():
        app_cache = app_home / "data" / "obsidian-cache"
        app_cache.mkdir(parents=True, exist_ok=True)
        local_dst = app_cache / cache_name
        if not local_dst.is_file():
            try:
                tmp_local = app_cache / f".{cache_name}.{os.getpid()}.tmp"
                tmp_local.write_bytes(raw)
                os.replace(tmp_local, local_dst)
            except OSError:
                pass

    print(
        json.dumps(
            {
                "ok": True,
                "cache_name": cache_name,
                "width": dims[0],
                "height": dims[1],
                "b64": base64.b64encode(raw).decode("ascii"),
            }
        )
    )
    return 0


def cmd_open(args: argparse.Namespace) -> int:
    cwd = Path(args.cwd or os.getcwd()).expanduser().resolve()
    vault_root = discover_vault(cwd, args.vault)
    index = VaultIndex(vault_root)

    relpath: str | None = None
    canvas: str | None = None
    ticket: str | None = None
    view = args.view or "note"

    if args.target:
        if view == "ticket":
            ticket = args.target.strip()
        elif args.target.endswith(".canvas") and args.target in index.canvases:
            canvas = args.target
            view = "canvas"
        else:
            relpath = index.resolve_note(args.target)
            if not relpath:
                # Check if target matches a canvas stem
                for c_rel in index.canvases:
                    if args.target.lower() in c_rel.lower():
                        canvas = c_rel
                        view = "canvas"
                        break
            if not relpath and not canvas:
                hits = index.search(args.target, limit=1)
                if hits:
                    relpath = hits[0]["relpath"]

    if not relpath and not args.target and view == "note":
        relpath = read_spool_state().get("relpath") or index.default_home_note()

    spool = write_spool_state(
        vault_root=str(vault_root),
        relpath=relpath,
        view=view,
        canvas=canvas,
        ticket=ticket,
        heading=args.heading,
    )

    # Ensure GPUI mod is installed if ~/.config/herdr-app exists
    if (Path.home() / ".config" / "herdr-app").is_dir():
        _, mod_state = skill.app_mod_status()
        if mod_state != "installed":
            skill.install_app_mod()

    herdr_app = shutil.which("herdr-app")
    opened_in_app = False
    if herdr_app:
        if not args.no_window:
            status_proc = subprocess.run(
                [herdr_app, "status"],
                capture_output=True,
                text=True,
                timeout=3,
            )
            if status_proc.returncode == 0:
                if args.placement == "tab":
                    subprocess.run(
                        [
                            herdr_app,
                            "do",
                            "tab.new",
                            json.dumps({"name": "Obsidian", "mod": "herdr-obsidian"}),
                        ],
                        capture_output=True,
                        timeout=4,
                    )
                else:
                    # Prefer revealing the layout's built-in knowledge stage (`col-knowledge`)
                    show_proc = subprocess.run(
                        [
                            herdr_app,
                            "do",
                            "layout.show",
                            json.dumps({"id": "col-knowledge"}),
                        ],
                        capture_output=True,
                        text=True,
                        timeout=3,
                    )
                    if show_proc.returncode == 0 and '"ok": true' in (show_proc.stdout or ""):
                        subprocess.run(
                            [
                                herdr_app,
                                "do",
                                "layout.select",
                                json.dumps({"stack": "knowledge-stack", "child": "obsidian"}),
                            ],
                            capture_output=True,
                            timeout=3,
                        )
                    else:
                        subprocess.run(
                            [
                                herdr_app,
                                "do",
                                "pane.split",
                                json.dumps({"direction": "right", "mod": "herdr-obsidian"}),
                            ],
                            capture_output=True,
                            timeout=4,
                        )
                opened_in_app = True
        _trigger_herdr_app_refresh()

    title = (
        index.notes[relpath].title
        if relpath and relpath in index.notes
        else (ticket or canvas or view)
    )
    if args.json:
        print(
            json.dumps(
                {
                    "ok": True,
                    "vault_root": str(vault_root),
                    "relpath": relpath,
                    "title": title,
                    "view": view,
                    "canvas": canvas,
                    "ticket": ticket,
                    "opened_in_app": opened_in_app,
                    "seq": spool["seq"],
                },
                indent=2,
            )
        )
    else:
        print(f"obsidian: {title} ({relpath or ticket or view}) — shown in Herdr Obsidian Vault viewer")
        print(f"[obsidian: {title}]")
    return 0


def cmd_read(args: argparse.Namespace) -> int:
    cwd = Path(args.cwd or os.getcwd()).expanduser().resolve()
    vault_root = discover_vault(cwd, args.vault)
    index = VaultIndex(vault_root)
    rel = index.resolve_note(args.target)
    if not rel or rel not in index.notes:
        sys.stderr.write(f"herdr-obsidian: note not found for {args.target!r} in {vault_root}\n")
        return 1
    payload = index.render_note_payload(rel)
    if not payload:
        return 1
    if args.sync:
        write_spool_state(vault_root=str(vault_root), relpath=rel, view="note")
        _trigger_herdr_app_refresh()
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print(f"# {payload['title']} ({payload['relpath']})")
        print(
            f"Level: L{payload['level']} | Category: {payload['category']} | "
            f"Backlinks: {len(payload['backlinks'])} | Outgoing: {len(payload['out_links'])}\n"
        )
        print(payload["raw_markdown"])
    return 0


def cmd_write(args: argparse.Namespace) -> int:
    cwd = Path(args.cwd or os.getcwd()).expanduser().resolve()
    vault_root = discover_vault(cwd, args.vault)
    rel = args.relpath.replace("\\", "/").lstrip("/")
    if not rel.endswith(".md"):
        rel += ".md"
    target = (vault_root / rel).resolve()
    if vault_root not in target.parents:
        sys.stderr.write(f"herdr-obsidian: refusing to write outside vault {vault_root}\n")
        return 1
    content = sys.stdin.read() if args.stdin else (args.content or "")
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    tmp.write_text(content, encoding="utf-8")
    os.replace(tmp, target)
    write_spool_state(vault_root=str(vault_root), relpath=rel, view="note")
    _trigger_herdr_app_refresh()
    if args.json:
        print(json.dumps({"ok": True, "relpath": rel, "bytes": len(content.encode("utf-8"))}))
    else:
        print(f"Saved {rel} ({len(content)} chars)")
    return 0


def cmd_search(args: argparse.Namespace) -> int:
    cwd = Path(args.cwd or os.getcwd()).expanduser().resolve()
    vault_root = discover_vault(cwd, args.vault)
    index = VaultIndex(vault_root)
    q = " ".join(args.query).strip()
    results = index.search(
        q,
        tag=args.tag,
        level=args.level,
        category=args.category,
        limit=args.limit,
    )
    if args.json:
        print(json.dumps({"vault_root": str(vault_root), "query": q, "results": results}, indent=2))
        return 0
    print(f"Obsidian Vault: {vault_root} ({len(results)} matches for {q!r})")
    for item in results:
        lvl = f"L{item['level']}" if item["level"] is not None else "  "
        print(
            f"  [{lvl}] {item['title']} ({item['relpath']}) [in:{item['in_degree']} out:{item['out_degree']}]"
        )
        if item.get("snippet"):
            print(f"       {item['snippet']}")
    return 0


def cmd_backlinks(args: argparse.Namespace) -> int:
    cwd = Path(args.cwd or os.getcwd()).expanduser().resolve()
    vault_root = discover_vault(cwd, args.vault)
    index = VaultIndex(vault_root)
    rel = index.resolve_note(args.target)
    if not rel or rel not in index.notes:
        sys.stderr.write(f"herdr-obsidian: note not found: {args.target!r}\n")
        return 1
    note = index.notes[rel]
    backlinks = index.backlinks_for(rel)
    outgoing = [
        {"relpath": d, "title": index.notes[d].title, "level": index.notes[d].level}
        for d in note.out_links
        if d in index.notes
    ]
    if args.json:
        print(
            json.dumps(
                {
                    "relpath": rel,
                    "title": note.title,
                    "backlinks": backlinks,
                    "out_links": outgoing,
                },
                indent=2,
            )
        )
        return 0
    print(f"# Links for {note.title} ({rel})")
    print(f"\n## Backlinks ({len(backlinks)})")
    for b in backlinks:
        print(f"  <- {b['title']} ({b['source']})")
        if b.get("snippet"):
            print(f'     "{b["snippet"]}"')
    print(f"\n## Outgoing Links ({len(outgoing)})")
    for o in outgoing:
        print(f"  -> {o['title']} ({o['relpath']})")
    return 0


def cmd_ticket(args: argparse.Namespace) -> int:
    cwd = Path(args.cwd or os.getcwd()).expanduser().resolve()
    vault_root = discover_vault(cwd, args.vault)
    index = VaultIndex(vault_root)
    brief = resolve_ticket_brief(index, cwd, args.ticket)
    if args.sync:
        write_spool_state(
            vault_root=str(vault_root),
            view="ticket",
            ticket=str(brief.get("ticket_id") or args.ticket or ""),
        )
        _trigger_herdr_app_refresh()
    if args.json:
        print(json.dumps(brief, indent=2))
        return 0
    print(f"# Linked-Knowledge Brief: {brief['ticket_id']} — {brief['title']}")
    for sec in brief["sections"]:
        items = sec["items"]
        if not items:
            continue
        print(f"\n## {sec['title']} ({len(items)})")
        for it in items:
            lvl = f"L{it['level']} " if it.get("level") is not None else ""
            print(f"  - [{lvl}{it['title']}]({it['relpath']})")
    return 0


def cmd_install_app_mod(args: argparse.Namespace) -> int:
    lines = skill.install_app_mod(
        uninstall=args.uninstall,
        machines=args.machine,
    )
    for line in lines:
        print(line)
    if args.notify and lines:
        _notify_herdr(lines[0], level="success")
    return 0


def cmd_install_skill(args: argparse.Namespace) -> int:
    lines = skill.install(
        args.targets or None,
        uninstall=args.uninstall,
        refresh_only=args.refresh,
    )
    for line in lines:
        print(line)
    if args.notify and lines:
        _notify_herdr(lines[0], level="success")
    return 0


def cmd_setup_keys(args: argparse.Namespace) -> int:
    ok_tui, msg_tui = keys.setup(args.key, remove=args.remove)
    ok_app, msg_app = keys.setup_app_keys(args.app_key, remove=args.remove)
    print(msg_tui)
    print(msg_app)
    if args.notify:
        _notify_herdr(msg_app if ok_app else msg_tui, level="success" if (ok_tui or ok_app) else "info")
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    cwd = Path(args.cwd or os.getcwd()).expanduser().resolve()
    vault_root = discover_vault(cwd, args.vault)
    index = VaultIndex(vault_root)
    mod_path, mod_state = skill.app_mod_status()
    skill_rows = skill.status()

    report = {
        "version": __version__,
        "vault_root": str(vault_root),
        "notes_count": len(index.notes),
        "canvases_count": len(index.canvases),
        "assets_count": len({p for p in index.assets.values()}),
        "herdr_app_mod": {"path": str(mod_path), "state": mod_state},
        "skills": [
            {"target": name, "path": str(dest), "readers": readers, "state": st}
            for name, dest, readers, st in skill_rows
        ],
    }
    if args.json:
        print(json.dumps(report, indent=2))
        return 0

    print(f"herdr-obsidian {__version__}")
    print(
        f"  Vault:         {vault_root} "
        f"({len(index.notes)} notes, {len(index.canvases)} canvases, "
        f"{len({p for p in index.assets.values()})} assets)"
    )
    print(f"  Herdr-App mod: {mod_path} ({mod_state})")
    for name, dest, readers, st in skill_rows:
        print(f"  Skill [{name:6s}]: {dest} ({st} — {readers})")
    if args.wait:
        try:
            input("\nPress Enter to close...")
        except EOFError:
            pass
    return 0


def cmd_tui(args: argparse.Namespace) -> int:
    """Interactive terminal fallback viewer when run inside `herdr` TUI."""
    cwd = Path(args.cwd or os.getcwd()).expanduser().resolve()
    vault_root = discover_vault(cwd, args.vault)
    index = VaultIndex(vault_root)
    spool = read_spool_state()
    active = index.resolve_note(spool.get("relpath") or "") or index.default_home_note()

    while True:
        os.system("clear")
        print(
            f"=== Herdr Obsidian Vault: {vault_root.name} "
            f"({len(index.notes)} notes, {len(index.canvases)} canvases) ==="
        )
        if active and active in index.notes:
            note = index.notes[active]
            print(f"\nNote: {note.title} ({note.relpath})")
            print(
                f"Level: L{note.level} | Category: {note.category} | "
                f"Backlinks: {len(note.in_links)} | Outgoing: {len(note.out_links)}"
            )
            print("-" * 76)
            payload = index.render_note_payload(active)
            if payload:
                lines = payload["raw_markdown"].splitlines()[:32]
                print("\n".join(lines))
                if len(payload["raw_markdown"].splitlines()) > 32:
                    print("\n... (use Herdr-App GPUI mod `Ctrl+Shift+O` for full interactive view)")
        print("\n" + "-" * 76)
        try:
            cmd = input("[s]earch  [o]pen wikilink  [b]acklinks  [t]icket brief  [q]uit > ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if cmd in ("q", "quit", "exit"):
            break
        if cmd.startswith("s"):
            q = cmd[1:].strip() or input("Search query: ").strip()
            hits = index.search(q, limit=12)
            for idx, h in enumerate(hits, 1):
                print(f"  {idx}. {h['title']} ({h['relpath']})")
            pick = input("Select # (or Enter): ").strip()
            if pick.isdigit() and 1 <= int(pick) <= len(hits):
                active = hits[int(pick) - 1]["relpath"]
                write_spool_state(relpath=active)
        elif cmd.startswith("o"):
            q = cmd[1:].strip() or input("Note or [[Wikilink]]: ").strip()
            resolved = index.resolve_note(q, from_relpath=active)
            if resolved:
                active = resolved
                write_spool_state(relpath=active)
        elif cmd.startswith("b") and active:
            for b in index.backlinks_for(active):
                print(f"  <- {b['title']} ({b['source']}): {b['snippet']}")
            input("Press Enter...")
        elif cmd.startswith("t"):
            brief = resolve_ticket_brief(index, cwd)
            print(f"\nTicket: {brief['ticket_id']} — {brief['title']}")
            for sec in brief["sections"]:
                for it in sec["items"]:
                    print(f"  [{sec['id']}] {it['title']} ({it['relpath']})")
            input("Press Enter...")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="herdr-obsidian",
        description="Integrated Obsidian Vault plugin & GPUI mod for Herdr-App and Herdr TUI.",
    )
    p.add_argument("--version", action="version", version=f"herdr-obsidian {__version__}")
    p.add_argument("--cwd", help="Working directory override")
    p.add_argument("--vault", help="Explicit Obsidian Vault directory")

    sub = p.add_subparsers(dest="subcommand")

    # app-state
    p_state = sub.add_parser("app-state", help="Return JSON state for the Herdr-App GPUI mod")
    p_state.add_argument("--cwd")
    p_state.add_argument("--vault")
    p_state.add_argument("--note", help="Active note path or wikilink")
    p_state.add_argument("--query", default="", help="Search query")
    p_state.add_argument("--tag", help="Filter by tag")
    p_state.add_argument("--level", type=int, help="Filter by L0..L3 level")
    p_state.add_argument("--category", help="Filter by category")
    p_state.add_argument("--metric", default="bytes", choices=["bytes", "lines", "links"])
    p_state.add_argument("--zoom-folder", default="")
    p_state.add_argument("--width", type=int, default=880)
    p_state.add_argument("--height", type=int, default=520)
    p_state.add_argument("--graph-mode", default="local", choices=["local", "global"])
    p_state.add_argument("--canvas", help="Active .canvas relative path")
    p_state.add_argument("--ticket", help="Explicit Kanban ticket ID")
    p_state.add_argument("--pane", help="Bound terminal pane ID")
    p_state.add_argument("--spool-seq", type=int, default=0, help="Last known spool sequence number")
    p_state.add_argument("--follow-sync", action="store_true")
    p_state.set_defaults(func=cmd_app_state)

    # app-artifact
    p_art = sub.add_parser("app-artifact", help="Return base64-encoded vault SVG/PNG asset")
    p_art.add_argument("asset", help="Relative asset path or filename")
    p_art.add_argument("--cwd")
    p_art.add_argument("--vault")
    p_art.set_defaults(func=cmd_app_artifact)

    # render-diagram
    p_rdiag = sub.add_parser(
        "render-diagram",
        help="Render a Mermaid/D2/PlantUML/Graphviz block to a cached dark-theme PNG",
    )
    p_rdiag.add_argument("cache_name", help="Target cache filename (diag-<hash>.png)")
    p_rdiag.add_argument("--note", help="Vault note relative path containing the diagram")
    p_rdiag.add_argument("--format", default="mermaid", help="Diagram format")
    p_rdiag.add_argument("--source", help="Explicit diagram source text")
    p_rdiag.add_argument("--cwd")
    p_rdiag.add_argument("--vault")
    p_rdiag.set_defaults(func=cmd_render_diagram)

    # open
    p_open = sub.add_parser("open", help="Open a note, canvas, treemap, graph, or ticket brief in Herdr-App")
    p_open.add_argument("target", nargs="?", help="Note path, [[Wikilink]], alias, or .canvas")
    p_open.add_argument("--view", choices=["note", "treemap", "canvas", "graph", "ticket"], default="note")
    p_open.add_argument("--placement", choices=["split", "tab", "popup"], default="split")
    p_open.add_argument("--heading", help="Target heading anchor")
    p_open.add_argument("--no-window", action="store_true", help="Update spool state without splitting pane")
    p_open.add_argument("--json", action="store_true")
    p_open.add_argument("--cwd")
    p_open.add_argument("--vault")
    p_open.set_defaults(func=cmd_open)

    # show (alias for open)
    p_show = sub.add_parser("show", help="Alias for `open`: show a note or view in the Obsidian side pane")
    p_show.add_argument("target", nargs="?")
    p_show.add_argument("--view", choices=["note", "treemap", "canvas", "graph", "ticket"], default="note")
    p_show.add_argument("--placement", choices=["split", "tab", "popup"], default="split")
    p_show.add_argument("--heading")
    p_show.add_argument("--no-window", action="store_true")
    p_show.add_argument("--json", action="store_true")
    p_show.add_argument("--cwd")
    p_show.add_argument("--vault")
    p_show.set_defaults(func=cmd_open)

    # read
    p_read = sub.add_parser("read", help="Resolve and read a note by path, title, or [[Wikilink]]")
    p_read.add_argument("target", help="Note path, title, alias, or [[Wikilink]]")
    p_read.add_argument("--sync", action="store_true", help="Also sync the Herdr-App viewer to this note")
    p_read.add_argument("--json", action="store_true")
    p_read.add_argument("--cwd")
    p_read.add_argument("--vault")
    p_read.set_defaults(func=cmd_read)

    # write
    p_write = sub.add_parser("write", help="Write or update a Markdown note inside the vault")
    p_write.add_argument("relpath", help="Relative path inside the vault")
    p_write.add_argument("--content", help="Markdown content string")
    p_write.add_argument("--stdin", action="store_true", help="Read content from stdin")
    p_write.add_argument("--json", action="store_true")
    p_write.add_argument("--cwd")
    p_write.add_argument("--vault")
    p_write.set_defaults(func=cmd_write)

    # search
    p_search = sub.add_parser("search", help="Search notes by full-text, title, alias, #tag, or level:L0..L3")
    p_search.add_argument("query", nargs="*", help="Search query tokens")
    p_search.add_argument("--tag", help="Filter by tag")
    p_search.add_argument("--level", type=int, help="Filter by L0..L3 level")
    p_search.add_argument("--category", help="Filter by category")
    p_search.add_argument("--limit", type=int, default=30)
    p_search.add_argument("--json", action="store_true")
    p_search.add_argument("--cwd")
    p_search.add_argument("--vault")
    p_search.set_defaults(func=cmd_search)

    # backlinks
    p_bl = sub.add_parser("backlinks", help="List incoming backlinks and outgoing wikilinks for a note")
    p_bl.add_argument("target", help="Note path, title, alias, or [[Wikilink]]")
    p_bl.add_argument("--json", action="store_true")
    p_bl.add_argument("--cwd")
    p_bl.add_argument("--vault")
    p_bl.set_defaults(func=cmd_backlinks)

    # ticket
    p_ticket = sub.add_parser(
        "ticket", help="Resolve Linked-Knowledge Obsidian Vault brief for a Kanban ticket"
    )
    p_ticket.add_argument("ticket", nargs="?", help="Kanban ticket ID (e.g. repo#42 or #42)")
    p_ticket.add_argument("--sync", action="store_true")
    p_ticket.add_argument("--json", action="store_true")
    p_ticket.add_argument("--cwd")
    p_ticket.add_argument("--vault")
    p_ticket.set_defaults(func=cmd_ticket)

    # install-app-mod
    p_mod = sub.add_parser(
        "install-app-mod", help="Install the native GPUI mod into ~/.config/herdr-app/mods/"
    )
    p_mod.add_argument("--uninstall", action="store_true")
    p_mod.add_argument("--machine", action="append", help="Also sync GPUI mod to remote hc peer(s)")
    p_mod.add_argument("--notify", action="store_true")
    p_mod.set_defaults(func=cmd_install_app_mod)

    # install-skill
    p_skill = sub.add_parser("install-skill", help="Install CLI symlink, agent skills, and GPUI mod")
    p_skill.add_argument("targets", nargs="*", help="Optional target subset (agents, claude, agy, cli, app)")
    p_skill.add_argument("--uninstall", action="store_true")
    p_skill.add_argument("--refresh", action="store_true")
    p_skill.add_argument("--notify", action="store_true")
    p_skill.set_defaults(func=cmd_install_skill)

    # setup-keys
    p_keys = sub.add_parser(
        "setup-keys", help="Configure Ctrl+Shift+O in Herdr-App and prefix+u in Herdr TUI"
    )
    p_keys.add_argument("--key", help="TUI key chord (default: prefix+u)")
    p_keys.add_argument("--app-key", help="Herdr-App key chord (default: ctrl-shift-o)")
    p_keys.add_argument("--remove", action="store_true")
    p_keys.add_argument("--notify", action="store_true")
    p_keys.set_defaults(func=cmd_setup_keys)

    # doctor
    p_doc = sub.add_parser("doctor", help="Check vault discovery, GPUI mod, and agent skills")
    p_doc.add_argument("--brief", action="store_true")
    p_doc.add_argument("--wait", action="store_true")
    p_doc.add_argument("--json", action="store_true")
    p_doc.add_argument("--cwd")
    p_doc.add_argument("--vault")
    p_doc.set_defaults(func=cmd_doctor)

    # tui / popup
    p_tui = sub.add_parser("tui", help="Run interactive terminal viewer")
    p_tui.add_argument("--compact", action="store_true")
    p_tui.add_argument("--cwd")
    p_tui.add_argument("--vault")
    p_tui.set_defaults(func=cmd_tui)

    p_pop = sub.add_parser("popup", help="Open a popup pane")
    p_pop.add_argument("pane_id", nargs="?", default="vault-popup")
    p_pop.set_defaults(
        func=cmd_open, target=None, view="note", placement="popup", heading=None, no_window=False, json=False
    )

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if not getattr(args, "subcommand", None):
            return cmd_open(
                argparse.Namespace(
                    cwd=args.cwd,
                    vault=args.vault,
                    target=None,
                    view="note",
                    placement="split",
                    heading=None,
                    no_window=False,
                    json=False,
                )
            )
        return int(args.func(args))
    except BrokenPipeError:
        try:
            sys.stdout.close()
        except OSError:
            pass
        return 0


if __name__ == "__main__":
    sys.exit(main())
