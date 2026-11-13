"""Agent spool state, terminal `[obsidian: ...]` marker detection, and herdr-kanban Linked-Knowledge sync."""

from __future__ import annotations

import json
import os
import re
import subprocess
import time
from pathlib import Path
from typing import Any

from .vault import VaultIndex

OBSIDIAN_MARKER_RE = re.compile(r"\[obsidian:\s*([^\]]+?)\s*\]")
ISSUE_BRANCH_RE = re.compile(r"(?:issue-|#)(\d+)\b", re.IGNORECASE)


def state_dir() -> Path:
    base = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local" / "state")
    path = Path(base) / "herdr-obsidian"
    path.mkdir(parents=True, exist_ok=True)
    return path


def read_spool_state() -> dict[str, Any]:
    path = state_dir() / "spool.json"
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def write_spool_state(
    *,
    vault_root: str | None = None,
    relpath: str | None = None,
    view: str | None = None,
    canvas: str | None = None,
    heading: str | None = None,
    query: str | None = None,
    pane: str | None = None,
) -> dict[str, Any]:
    current = read_spool_state()
    seq = int(current.get("seq", 0)) + 1
    payload = {
        "seq": seq,
        "updated_at": time.time(),
        "vault_root": vault_root if vault_root is not None else current.get("vault_root"),
        "relpath": relpath if relpath is not None else current.get("relpath"),
        "view": view or current.get("view") or "note",
        "canvas": canvas if canvas is not None else current.get("canvas"),
        "heading": heading,
        "query": query,
        "pane": pane or os.environ.get("HERDR_PANE_ID") or os.environ.get("HC_TERMINAL_ID"),
    }
    target = state_dir() / "spool.json"
    tmp = target.with_name(f".spool.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, target)
    return payload


def _infer_repo_prefix(cwd: Path) -> str:
    """Infer the default repository alias from `.herdr-kanban.toml` or directory name."""
    for d in [cwd, *cwd.parents]:
        cfg = d / ".herdr-kanban.toml"
        if cfg.is_file():
            try:
                text = cfg.read_text(encoding="utf-8")
                m = re.search(r'^\s*issues_repo\s*=\s*"([^"]+)"', text, re.MULTILINE)
                if m:
                    return m.group(1).strip()
            except OSError:
                pass
        for ptr in sorted(d.glob(".*umbrella*.json")):
            if ptr.is_file():
                try:
                    data = json.loads(ptr.read_text(encoding="utf-8"))
                    root_str = data.get("umbrella_root")
                    if root_str:
                        return Path(str(root_str)).name
                except (OSError, json.JSONDecodeError):
                    pass
    return cwd.name or "repo"


def detect_active_ticket(cwd: Path, explicit_ticket: str | None = None) -> str | None:
    """Detect the active herdr-kanban ticket (e.g. `repo#42`) from branch, worktree, or claim files."""
    if explicit_ticket:
        return explicit_ticket.strip()

    default_repo = _infer_repo_prefix(cwd)

    # 1. Check worktree umbrella pointer json or issue-N directory name
    for d in [cwd, *cwd.parents]:
        for ptr in sorted(d.glob(".*umbrella*.json")):
            if ptr.is_file():
                try:
                    data = json.loads(ptr.read_text(encoding="utf-8"))
                    kb = str(data.get("knowledge_brief") or "")
                    m = re.search(r"issue-(\d+)", kb)
                    if m:
                        return f"{default_repo}#{m.group(1)}"
                except (OSError, json.JSONDecodeError):
                    pass
        m_wt = re.search(r"issue-(\d+)$", d.name)
        if m_wt:
            return f"{default_repo}#{m_wt.group(1)}"

    # 2. Check current git branch (`kanban/issue-42`)
    try:
        proc = subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=2,
        )
        if proc.returncode == 0:
            m_br = ISSUE_BRANCH_RE.search(proc.stdout.strip())
            if m_br:
                return f"{default_repo}#{m_br.group(1)}"
    except (OSError, subprocess.SubprocessError):
        pass

    # 3. Check .siblings/<repo>/<issue>.json active claim files in workspace root
    for d in [cwd, *cwd.parents]:
        sib = d / ".siblings"
        if sib.is_dir():
            claims = sorted(sib.glob("*/*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
            for claim_file in claims:
                try:
                    c_data = json.loads(claim_file.read_text(encoding="utf-8"))
                    num = c_data.get("issue_number")
                    repo = c_data.get("repo_alias") or default_repo
                    if num:
                        return f"{repo}#{num}"
                except (OSError, json.JSONDecodeError):
                    continue
    return None


def resolve_ticket_brief(
    index: VaultIndex,
    cwd: Path,
    explicit_ticket: str | None = None,
) -> dict[str, Any]:
    """Resolve the Linked-Knowledge Obsidian Vault brief for the active or requested Kanban ticket."""
    ticket_id = detect_active_ticket(cwd, explicit_ticket)
    workspace_root: Path | None = None
    resolver: Path | None = None
    for d in [cwd, index.vault_root, *cwd.parents, *index.vault_root.parents]:
        hooks_dir = d / ".agents" / "hooks"
        if hooks_dir.is_dir():
            candidates = sorted(hooks_dir.glob("suggest_*_skills.py"))
            if candidates:
                workspace_root = d
                resolver = candidates[0]
                break

    raw_brief: dict[str, Any] = {}
    if workspace_root is not None and resolver is not None:
        query = ticket_id or workspace_root.name
        try:
            proc = subprocess.run(
                ["python3", str(resolver), query, "--json"],
                cwd=workspace_root,
                capture_output=True,
                text=True,
                timeout=6,
            )
            if proc.returncode == 0 and proc.stdout.strip():
                raw_brief = json.loads(proc.stdout)
        except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
            pass

    def _enrich_paths(items: list[Any]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        seen: set[str] = set()
        for item in items or []:
            raw_p = item.get("path") if isinstance(item, dict) else str(item)
            if not raw_p:
                continue
            p_str = str(raw_p)
            if p_str.startswith("docs/"):
                p_str = p_str[len("docs/") :]
            resolved = index.resolve_note(p_str)
            if resolved and resolved in index.notes and resolved not in seen:
                seen.add(resolved)
                n = index.notes[resolved]
                out.append(
                    {
                        "relpath": resolved,
                        "title": n.title,
                        "level": n.level,
                        "category": n.category,
                        "excerpt": n.excerpt,
                    }
                )
        return out

    mocs = _enrich_paths(raw_brief.get("role_mocs", []))
    arch_notes = _enrich_paths(raw_brief.get("obsidian_notes", []))
    glossary_terms = _enrich_paths(raw_brief.get("glossary_terms", []))
    adrs = _enrich_paths(raw_brief.get("adrs", []))
    reports = _enrich_paths(raw_brief.get("quality_reports", []))
    proof_items: list[dict[str, Any]] = []
    for pf in (raw_brief.get("formal_proofs") or raw_brief.get("proofs") or []) or []:
        if isinstance(pf, dict) and pf.get("obsidian_note"):
            enriched = _enrich_paths([pf["obsidian_note"]])
            proof_items.extend(enriched)

    # Fallback when no external hook matched: surface top MOCs, architecture notes, and ADRs
    if not (mocs or arch_notes):
        sorted_notes = sorted(index.notes.values(), key=lambda x: x.relpath)
        mocs = [
            {
                "relpath": n.relpath,
                "title": n.title,
                "level": n.level,
                "category": n.category,
                "excerpt": n.excerpt,
            }
            for n in sorted_notes
            if n.category == "moc"
        ][:8]
        arch_notes = [
            {
                "relpath": n.relpath,
                "title": n.title,
                "level": n.level,
                "category": n.category,
                "excerpt": n.excerpt,
            }
            for n in sorted_notes
            if n.category == "product-architecture"
        ][:8]
        adrs = [
            {
                "relpath": n.relpath,
                "title": n.title,
                "level": n.level,
                "category": n.category,
                "excerpt": n.excerpt,
            }
            for n in sorted_notes
            if n.category == "adr-architecture"
        ][:6]

    return {
        "ticket_id": raw_brief.get("ticket_id") or ticket_id or "workspace",
        "title": raw_brief.get("title") or "Workspace Linked-Knowledge Brief",
        "domains": raw_brief.get("domains") or [],
        "ticket_type": raw_brief.get("ticket_type") or "",
        "trl": raw_brief.get("trl") or "",
        "access": raw_brief.get("access") or "",
        "skills": [
            s.get("name") if isinstance(s, dict) else str(s)
            for s in (raw_brief.get("recommended_skills") or [])
        ],
        "deliverables": raw_brief.get("deliverables") or [],
        "sections": [
            {"id": "mocs", "title": "Role Map-Of-Content (MOC) Hubs", "items": mocs},
            {"id": "arch", "title": "L1–L3 Architecture & Process Notes", "items": arch_notes},
            {"id": "glossary", "title": "Ubiquitous Domain Glossary Terms", "items": glossary_terms},
            {"id": "adrs", "title": "Architecture Decision Records (ADRs)", "items": adrs},
            {"id": "proofs", "title": "Formal Verification Notes", "items": proof_items},
            {"id": "reports", "title": "Quality, DoE & Forensics Reports", "items": reports},
        ],
    }
