"""Obsidian Vault discovery, frontmatter/wikilink/callout parser, backlinks, and JSON Canvas loader."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import struct
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote
from xml.sax.saxutils import escape as xml_escape

from .math_render import transform_markdown_math

ROOT = Path(__file__).resolve().parent.parent.parent

IGNORED_DIRS = {
    ".git",
    ".hg",
    ".svn",
    ".obsidian",
    ".trash",
    "node_modules",
    ".venv",
    "venv",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    "dist",
    "build",
}

ASSET_EXTENSIONS = {".svg", ".png", ".jpg", ".jpeg", ".webp", ".gif"}

WIKILINK_RE = re.compile(r"(!?)\[\[([^\]\n]+)\]\]")
MD_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\(([^)\n]+)\)")
MD_LINK_RE = re.compile(r"(?<!!)\[([^\]]+)\]\(([^)\n]+)\)")
HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.MULTILINE)
CALLOUT_START_RE = re.compile(r"^>\s*\[!([A-Za-z0-9_-]+)\]([+-]?)(?:\s+(.*))?$")
FENCE_START_RE = re.compile(r"^(`{3,}|~{3,})\s*([A-Za-z0-9_+-]*)\s*$")
INLINE_TAG_RE = re.compile(r"(?:^|(?<=\s))#([A-Za-z][A-Za-z0-9_/-]*)")
SVG_VIEWBOX_RE = re.compile(
    r'viewBox=["\']\s*[-0-9.]+\s+[-0-9.]+\s+([0-9.]+)\s+([0-9.]+)\s*["\']',
    re.IGNORECASE,
)
SVG_WIDTH_RE = re.compile(r'\bwidth=["\']([0-9.]+)(?:px)?["\']', re.IGNORECASE)
SVG_HEIGHT_RE = re.compile(r'\bheight=["\']([0-9.]+)(?:px)?["\']', re.IGNORECASE)


@dataclass(slots=True)
class NoteSummary:
    relpath: str
    title: str
    folder: str
    level: int | None
    category: str
    tags: list[str]
    aliases: list[str]
    frontmatter: dict[str, Any]
    size_bytes: int
    line_count: int
    mtime: float
    out_links: list[str] = field(default_factory=list)
    in_links: list[str] = field(default_factory=list)
    embeds: list[str] = field(default_factory=list)
    headings: list[dict[str, Any]] = field(default_factory=list)
    excerpt: str = ""


def _strip_quotes(val: str) -> str:
    val = val.strip()
    if len(val) >= 2 and ((val[0] == '"' and val[-1] == '"') or (val[0] == "'" and val[-1] == "'")):
        return val[1:-1]
    return val


def parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Parse YAML frontmatter at the top of a Markdown file without external dependencies."""
    if not text.startswith("---"):
        return {}, text
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, text

    end_idx: int | None = None
    for idx in range(1, min(len(lines), 150)):
        stripped = lines[idx].strip()
        if stripped in ("---", "..."):
            end_idx = idx
            break
    if end_idx is None:
        return {}, text

    fm: dict[str, Any] = {}
    current_key: str | None = None
    for line in lines[1:end_idx]:
        raw = line.rstrip()
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        if raw.startswith(("  -", " -", "- ")) and current_key is not None:
            item_val = _strip_quotes(raw.lstrip()[1:].strip())
            existing = fm.get(current_key)
            if isinstance(existing, list):
                existing.append(item_val)
            else:
                fm[current_key] = [item_val]
            continue
        if ":" in raw and not raw.startswith((" ", "\t")):
            key_part, val_part = raw.split(":", 1)
            key = key_part.strip()
            val_str = val_part.strip()
            current_key = key
            if not val_str:
                fm[key] = []
            elif val_str.startswith("[") and val_str.endswith("]"):
                inner = val_str[1:-1].strip()
                fm[key] = [_strip_quotes(x) for x in inner.split(",") if _strip_quotes(x)] if inner else []
            elif val_str.lower() in ("true", "false"):
                fm[key] = val_str.lower() == "true"
            elif re.fullmatch(r"-?\d+", val_str):
                fm[key] = int(val_str)
            elif re.fullmatch(r"-?\d+\.\d+", val_str):
                fm[key] = float(val_str)
            else:
                fm[key] = _strip_quotes(val_str)

    body = "\n".join(lines[end_idx + 1 :]).lstrip("\n")
    return fm, body


def infer_category(relpath: str, tags: list[str], fm: dict[str, Any]) -> str:
    """Resolve a note into one of the canonical disktree/vault categories."""
    norm = relpath.replace("\\", "/").lstrip("/")
    lower = norm.lower()
    cat_fm = str(fm.get("category") or "").lower()
    if (
        "moc" in cat_fm
        or "map-of-content" in cat_fm
        or lower.startswith("00-map-of-content")
        or "moc" in tags
    ):
        return "moc"
    if lower.startswith("01-product-process-architecture") or "product" in cat_fm:
        return "product-architecture"
    if lower.startswith("02-quality-and-development-standards") or "quality" in cat_fm:
        return "quality-standards"
    if lower.startswith(("03-ip-portfolio", "03-research")) or "ip" in cat_fm or "patent" in cat_fm:
        return "ip-portfolio"
    if (
        lower.startswith(("04-proofs", "04-formal", "04-verification"))
        or "proof" in cat_fm
        or "formal" in cat_fm
    ):
        return "formal-proofs"
    if lower.startswith("05-glossary") or "glossary" in cat_fm:
        return "glossary"
    if lower.startswith("06-investigation-and-quality-reports") or "report" in cat_fm:
        return "investigation-reports"
    if lower.startswith("07-canvases") or lower.endswith(".canvas"):
        return "canvas"
    if lower.startswith(("adr/", "architecture/")) or "adr" in cat_fm:
        return "adr-architecture"
    return "general"


def infer_level(relpath: str, tags: list[str], fm: dict[str, Any]) -> int | None:
    """Infer L0..L3 progressive disclosure level from frontmatter, tags, or filename."""
    lvl = fm.get("level")
    if isinstance(lvl, int) and 0 <= lvl <= 4:
        return lvl
    if isinstance(lvl, str):
        m = re.search(r"[Ll]?(\d)", lvl)
        if m:
            return int(m.group(1))
    for tag in tags:
        m = re.search(r"(?:^|/)L([0-3])$", tag, re.IGNORECASE)
        if m:
            return int(m.group(1))
    name = Path(relpath).name
    m = re.match(r"^L([0-3])\b", name)
    if m:
        return int(m.group(1))
    if "Map-Of-Content" in name or name.startswith("00 -"):
        return 0
    return None


def discover_vault(start_dir: Path | str | None = None, explicit_vault: Path | str | None = None) -> Path:
    """Discover the Obsidian Vault root directory from a workspace, repo, or herdr-kanban worktree."""
    if explicit_vault:
        cand = Path(explicit_vault).expanduser().resolve()
        if (cand / ".obsidian").is_dir():
            return cand
        if (cand / "docs" / ".obsidian").is_dir():
            return (cand / "docs").resolve()
        if cand.is_dir():
            return cand

    env_vault = os.environ.get("HERDR_OBSIDIAN_VAULT")
    if env_vault:
        cand = Path(env_vault).expanduser().resolve()
        if cand.is_dir():
            return cand

    spool_file = (
        Path(os.environ.get("XDG_STATE_HOME") or (Path.home() / ".local" / "state"))
        / "herdr-obsidian"
        / "spool.json"
    )
    if spool_file.is_file():
        try:
            sp = json.loads(spool_file.read_text(encoding="utf-8"))
            forced = sp.get("force_vault")
            if forced and Path(forced).is_dir():
                return Path(forced).resolve()
        except (OSError, json.JSONDecodeError):
            pass

    cwd = Path(start_dir or os.getcwd()).expanduser().resolve()
    if cwd.is_file():
        cwd = cwd.parent

    # Walk cwd and ancestors
    for directory in [cwd, *cwd.parents]:
        if (directory / ".obsidian").is_dir():
            return directory
        if (directory / "docs" / ".obsidian").is_dir():
            return directory / "docs"
        for umbrella_ptr in sorted(directory.glob(".*umbrella*.json")):
            if umbrella_ptr.is_file():
                try:
                    data = json.loads(umbrella_ptr.read_text(encoding="utf-8"))
                    vault_str = data.get("obsidian_vault")
                    if vault_str and Path(vault_str).is_dir():
                        return Path(vault_str).resolve()
                except (OSError, json.JSONDecodeError):
                    pass

    # Check if cwd is inside a git worktree whose main repo has docs/.obsidian or .obsidian
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--git-common-dir"],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=3,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            common_git = (cwd / proc.stdout.strip()).resolve()
            main_repo = common_git.parent
            for candidate in [main_repo, main_repo.parent]:
                if (candidate / "docs" / ".obsidian").is_dir():
                    return (candidate / "docs").resolve()
                if (candidate / ".obsidian").is_dir():
                    return candidate.resolve()
    except (OSError, subprocess.SubprocessError):
        pass

    # Fallback: check for docs/ with markdown files, or known recent vault in spool
    for directory in [cwd, *cwd.parents]:
        if (
            directory != Path.home()
            and (directory / "docs").is_dir()
            and any((directory / "docs").glob("*.md"))
        ):
            return directory / "docs"

    # If start_dir is $HOME, check spool for the last active vault_root
    spool_file = (
        Path(os.environ.get("XDG_STATE_HOME") or (Path.home() / ".local" / "state"))
        / "herdr-obsidian"
        / "spool.json"
    )
    if spool_file.is_file():
        try:
            sp = json.loads(spool_file.read_text(encoding="utf-8"))
            v_root = sp.get("vault_root")
            if v_root and Path(v_root).is_dir():
                return Path(v_root).resolve()
        except (OSError, json.JSONDecodeError):
            pass

    return cwd


def _clean_wikilink_target(raw_inner: str) -> tuple[str, str | None, str]:
    """Split `Target#Heading|Alias` into `(target_note, heading, display_label)`."""
    if "|" in raw_inner:
        target_part, label = raw_inner.split("|", 1)
    else:
        target_part, label = raw_inner, ""
    target_part = target_part.strip()
    heading: str | None = None
    if "#" in target_part:
        target_part, heading = target_part.split("#", 1)
        target_part = target_part.strip()
        heading = heading.strip() or None
    if not label.strip():
        base = Path(target_part).stem if target_part else (heading or raw_inner)
        label = f"{base} § {heading}" if heading and target_part else base
    return target_part, heading, label.strip()


def _extract_excerpt(body: str) -> str:
    """Return a clean 180-char plain-text summary of a Markdown note body."""
    cleaned_lines: list[str] = []
    in_fence = False
    for line in body.splitlines():
        s = line.strip()
        if s.startswith(("```", "~~~")):
            in_fence = not in_fence
            continue
        if in_fence or not s:
            continue
        if s.startswith(("#", "![", "![[", "|", "---", "> [!")):
            continue
        if s.startswith(">"):
            s = s.lstrip(">").strip()
        # Replace wikilinks with display labels and render inline math
        s = WIKILINK_RE.sub(lambda m: _clean_wikilink_target(m.group(2))[2], s)
        s = transform_markdown_math(s, escape_md=False)
        s = re.sub(r"[*_`~]+", "", s).strip()
        if s:
            cleaned_lines.append(s)
        if sum(len(x) for x in cleaned_lines) >= 200:
            break
    joined = " ".join(cleaned_lines)
    return (joined[:197] + "…") if len(joined) > 200 else joined


def diagram_cache_dir() -> Path:
    """Return the content-addressed PNG cache directory for rendered Mermaid/D2/PlantUML diagrams."""
    base = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local" / "state")
    path = Path(base) / "herdr-obsidian" / "diagrams"
    path.mkdir(parents=True, exist_ok=True)
    return path


def extract_png_dimensions(raw: bytes) -> tuple[int, int] | None:
    """Read pixel `(width, height)` from a PNG IHDR chunk."""
    if len(raw) >= 24 and raw[:8] == b"\x89PNG\r\n\x1a\n":
        try:
            w, h = struct.unpack(">II", raw[16:24])
            if w > 0 and h > 0:
                return int(w), int(h)
        except struct.error:
            pass
    return None


class VaultIndex:
    """In-memory index of an Obsidian Vault: notes, aliases, wikilinks, backlinks, assets, canvases."""

    def __init__(self, vault_root: Path) -> None:
        self.vault_root = vault_root.resolve()
        self.notes: dict[str, NoteSummary] = {}
        self.canvases: list[str] = []
        self.assets: dict[str, Path] = {}
        self._lookup: dict[str, str] = {}
        self._raw_bodies: dict[str, str] = {}
        self._backlink_snippets: dict[str, list[dict[str, Any]]] = {}
        self._scan()

    def _register_key(self, key: str, relpath: str, *, overwrite: bool = False) -> None:
        k = key.strip().replace("\\", "/")
        if not k:
            return
        for variant in (k, k.lower()):
            if overwrite or variant not in self._lookup:
                self._lookup[variant] = relpath

    def _scan(self) -> None:
        raw_links_by_note: dict[str, list[tuple[str, str]]] = {}
        for root_str, dirs, files in os.walk(self.vault_root):
            dirs[:] = sorted(d for d in dirs if d not in IGNORED_DIRS and not d.startswith("."))
            root_path = Path(root_str)
            for fname in sorted(files):
                if fname.startswith("."):
                    continue
                fpath = root_path / fname
                rel = fpath.relative_to(self.vault_root).as_posix()
                suffix = fpath.suffix.lower()
                if suffix == ".canvas":
                    self.canvases.append(rel)
                    continue
                if suffix in ASSET_EXTENSIONS:
                    self.assets[rel] = fpath
                    self.assets[fpath.name] = fpath
                    self.assets[rel.lower()] = fpath
                    self.assets[fpath.name.lower()] = fpath
                    continue
                if suffix != ".md":
                    continue

                try:
                    stat = fpath.stat()
                    raw_text = fpath.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue

                fm, body = parse_frontmatter(raw_text)
                self._raw_bodies[rel] = body

                stem = fpath.stem
                raw_title = str(fm.get("title") or "").strip()
                if not raw_title:
                    m_h1 = re.search(r"^#\s+(.+?)\s*$", body, re.MULTILINE)
                    raw_title = m_h1.group(1).strip() if m_h1 else stem
                title = transform_markdown_math(raw_title, escape_md=False)

                raw_tags = fm.get("tags") or []
                tags: list[str] = (
                    [str(t).lstrip("#") for t in raw_tags if str(t).strip()]
                    if isinstance(raw_tags, list)
                    else [str(raw_tags).lstrip("#")]
                    if raw_tags
                    else []
                )
                for m_tag in INLINE_TAG_RE.finditer(body):
                    t_val = m_tag.group(1)
                    if t_val not in tags and len(tags) < 25:
                        tags.append(t_val)

                raw_aliases = fm.get("aliases") or []
                aliases: list[str] = (
                    [str(a).strip() for a in raw_aliases if str(a).strip()]
                    if isinstance(raw_aliases, list)
                    else [str(raw_aliases).strip()]
                    if raw_aliases
                    else []
                )

                headings: list[dict[str, Any]] = []
                for line_no, line in enumerate(body.splitlines(), start=1):
                    m_h = HEADING_RE.match(line)
                    if m_h:
                        headings.append(
                            {
                                "level": len(m_h.group(1)),
                                "text": transform_markdown_math(m_h.group(2).strip(), escape_md=False),
                                "line": line_no,
                            }
                        )

                folder = fpath.parent.relative_to(self.vault_root).as_posix()
                if folder == ".":
                    folder = ""

                cat = infer_category(rel, tags, fm)
                lvl = infer_level(rel, tags, fm)
                summary = NoteSummary(
                    relpath=rel,
                    title=title,
                    folder=folder,
                    level=lvl,
                    category=cat,
                    tags=tags,
                    aliases=aliases,
                    frontmatter=fm,
                    size_bytes=stat.st_size,
                    line_count=raw_text.count("\n") + 1,
                    mtime=stat.st_mtime,
                    headings=headings,
                    excerpt=_extract_excerpt(body),
                )
                self.notes[rel] = summary

                # Register lookup keys (path -> stem -> title -> aliases)
                self._register_key(rel, rel, overwrite=True)
                if rel.endswith(".md"):
                    self._register_key(rel[:-3], rel, overwrite=True)
                self._register_key(stem, rel)
                self._register_key(raw_title, rel)
                self._register_key(title, rel)
                for alias in aliases:
                    self._register_key(alias, rel)

                # Collect raw outgoing links and embeds
                note_links: list[tuple[str, str]] = []
                embeds: list[str] = []
                for line in body.splitlines():
                    for m_wl in WIKILINK_RE.finditer(line):
                        is_embed = m_wl.group(1) == "!"
                        target_part, _, _ = _clean_wikilink_target(m_wl.group(2))
                        if not target_part:
                            continue
                        if is_embed:
                            embeds.append(target_part)
                        else:
                            snippet = WIKILINK_RE.sub(
                                lambda m: _clean_wikilink_target(m.group(2))[2], line.strip()
                            )
                            snippet = transform_markdown_math(snippet, escape_md=False)
                            note_links.append((target_part, snippet[:160]))
                    for m_img in MD_IMAGE_RE.finditer(line):
                        embeds.append(m_img.group(2).strip())
                summary.embeds = embeds
                raw_links_by_note[rel] = note_links

        # Second pass: resolve wikilinks and build bidirectional graph + backlink snippets
        for src_rel, link_list in raw_links_by_note.items():
            src_note = self.notes[src_rel]
            seen_out: set[str] = set()
            for target_raw, snippet in link_list:
                resolved = self.resolve_note(target_raw, from_relpath=src_rel)
                if not resolved or resolved == src_rel:
                    continue
                if resolved not in seen_out:
                    seen_out.add(resolved)
                    src_note.out_links.append(resolved)
                dst_note = self.notes[resolved]
                if src_rel not in dst_note.in_links:
                    dst_note.in_links.append(src_rel)
                b_list = self._backlink_snippets.setdefault(resolved, [])
                if not any(b["source"] == src_rel for b in b_list):
                    b_list.append(
                        {
                            "source": src_rel,
                            "title": src_note.title,
                            "level": src_note.level,
                            "category": src_note.category,
                            "snippet": snippet,
                        }
                    )

    def resolve_note(self, query: str, *, from_relpath: str | None = None) -> str | None:
        """Resolve a wikilink target, alias, title, or relative path to a canonical note `relpath`."""
        if not query:
            return None
        q = unquote(query.strip()).replace("\\", "/")
        if q.startswith("vault://"):
            q = q[len("vault://") :]
        if "#" in q:
            q = q.split("#", 1)[0].strip()
        if not q:
            return from_relpath

        # Relative path resolution from current note
        if from_relpath and (q.startswith("./") or q.startswith("../")):
            base_dir = Path(from_relpath).parent
            norm = os.path.normpath((base_dir / q).as_posix()).replace("\\", "/")
            for cand in (norm, f"{norm}.md"):
                if cand in self.notes:
                    return cand

        for candidate in (q, q.lstrip("/"), q[:-3] if q.endswith(".md") else f"{q}.md"):
            hit = self._lookup.get(candidate) or self._lookup.get(candidate.lower())
            if hit:
                return hit

        # Stem / partial fallback
        q_stem = Path(q).stem.lower()
        hit = self._lookup.get(q_stem)
        if hit:
            return hit

        for rel, note in self.notes.items():
            if q_stem in note.title.lower() or q_stem in rel.lower():
                return rel
        return None

    def resolve_asset(self, target: str, *, from_relpath: str | None = None) -> Path | None:
        """Resolve an embedded image/SVG path (`![[...]]` or `![](...)`) to an absolute file on disk."""
        raw = unquote(target.strip()).split("|", 1)[0].strip()
        if not raw or raw.startswith(("http://", "https://", "data:")):
            return None
        raw_norm = raw.replace("\\", "/").lstrip("/")
        if from_relpath:
            rel_cand = (self.vault_root / Path(from_relpath).parent / raw_norm).resolve()
            if rel_cand.is_file() and self.vault_root in rel_cand.parents:
                return rel_cand
        direct = (self.vault_root / raw_norm).resolve()
        if direct.is_file() and self.vault_root in direct.parents:
            return direct
        return (
            self.assets.get(raw_norm)
            or self.assets.get(raw_norm.lower())
            or self.assets.get(Path(raw_norm).name)
            or self.assets.get(Path(raw_norm).name.lower())
        )

    def default_home_note(self) -> str | None:
        """Return the vault's primary Home MOC or index note."""
        bookmarks = self.load_bookmarks()
        for bm in bookmarks:
            if bm["path"] in self.notes:
                return bm["path"]
        for preferred in (
            "00-Index.md",
            "README.md",
            "index.md",
        ):
            if preferred in self.notes:
                return preferred
        mocs = [n.relpath for n in self.notes.values() if n.category == "moc"]
        if mocs:
            return sorted(mocs)[0]
        return sorted(self.notes.keys())[0] if self.notes else None

    def load_bookmarks(self) -> list[dict[str, str]]:
        """Read `.obsidian/bookmarks.json` and append top-level MOC hubs."""
        bm_file = self.vault_root / ".obsidian" / "bookmarks.json"
        out: list[dict[str, str]] = []
        seen: set[str] = set()
        if bm_file.is_file():
            try:
                data = json.loads(bm_file.read_text(encoding="utf-8"))
                for item in data.get("items", []):
                    path = item.get("path")
                    if isinstance(path, str) and (path in self.notes or path in self.canvases):
                        seen.add(path)
                        out.append(
                            {
                                "path": path,
                                "title": str(item.get("title") or Path(path).stem),
                                "kind": "canvas" if path.endswith(".canvas") else "note",
                            }
                        )
            except (OSError, json.JSONDecodeError):
                pass
        for rel, note in sorted(self.notes.items()):
            if note.category == "moc" and rel not in seen:
                seen.add(rel)
                out.append({"path": rel, "title": note.title, "kind": "note"})
        return out

    def backlinks_for(self, relpath: str) -> list[dict[str, Any]]:
        return list(self._backlink_snippets.get(relpath, []))

    def search(
        self,
        query: str = "",
        *,
        tag: str | None = None,
        level: int | None = None,
        category: str | None = None,
        limit: int = 60,
    ) -> list[dict[str, Any]]:
        """Full-text, title, alias, tag (`#tag`), and frontmatter (`level:L1`) search across the vault."""
        q_raw = query.strip()
        tokens = [t for t in q_raw.split() if t]
        req_tags: list[str] = [tag.lstrip("#").lower()] if tag else []
        req_level = level
        req_cat = category.lower() if category else None
        text_terms: list[str] = []

        for tok in tokens:
            if tok.startswith("#") and len(tok) > 1:
                req_tags.append(tok[1:].lower())
            elif tok.lower().startswith("tag:"):
                req_tags.append(tok.split(":", 1)[1].lstrip("#").lower())
            elif tok.lower().startswith("level:"):
                val = tok.split(":", 1)[1].upper().lstrip("L")
                if val.isdigit():
                    req_level = int(val)
            elif tok.lower().startswith(("cat:", "category:", "domain:")):
                req_cat = tok.split(":", 1)[1].lower()
            else:
                text_terms.append(tok.lower())

        scored: list[tuple[int, str, NoteSummary, str]] = []
        for rel, note in self.notes.items():
            if req_level is not None and note.level != req_level:
                continue
            if req_cat and req_cat not in note.category.lower() and req_cat not in rel.lower():
                continue
            note_tags_lower = [t.lower() for t in note.tags]
            if any(not any(rt in nt for nt in note_tags_lower) for rt in req_tags):
                continue

            if not text_terms:
                score = (100 if note.category == "moc" else 50) + len(note.in_links) * 2
                scored.append((score, rel, note, note.excerpt))
                continue

            title_l = note.title.lower()
            rel_l = rel.lower()
            aliases_l = " ".join(note.aliases).lower()
            body = self._raw_bodies.get(rel, "")
            body_l = body.lower()

            score = 0
            matched_all = True
            snippet = note.excerpt
            for term in text_terms:
                if term in title_l:
                    score += 80 if title_l.startswith(term) else 50
                elif term in aliases_l:
                    score += 40
                elif term in rel_l:
                    score += 30
                elif term in body_l:
                    score += 15
                    idx = body_l.find(term)
                    start = max(0, idx - 50)
                    end = min(len(body), idx + 110)
                    snippet = body[start:end].replace("\n", " ").strip()
                else:
                    matched_all = False
                    break

            if matched_all:
                score += min(20, len(note.in_links))
                scored.append((score, rel, note, snippet))

        scored.sort(key=lambda item: (-item[0], item[1]))
        return [
            {
                "relpath": rel,
                "title": note.title,
                "folder": note.folder,
                "level": note.level,
                "category": note.category,
                "tags": note.tags[:6],
                "in_degree": len(note.in_links),
                "out_degree": len(note.out_links),
                "snippet": snip,
                "score": sc,
            }
            for sc, rel, note, snip in scored[:limit]
        ]

    def _transform_inline_links(self, md_chunk: str, from_relpath: str) -> str:
        """Transform `[[Target|Label]]` and relative `[Label](foo.md)` into `[Label](vault://...)`."""

        def _repl_wl(match: re.Match[str]) -> str:
            is_embed = match.group(1) == "!"
            raw_inner = match.group(2)
            target_part, heading, label = _clean_wikilink_target(raw_inner)
            if is_embed:
                return f"*(Embedded: {label})*"
            resolved = (
                self.resolve_note(target_part, from_relpath=from_relpath) if target_part else from_relpath
            )
            if resolved:
                url = f"vault://{quote(resolved)}"
                if heading:
                    url += f"#{quote(heading)}"
                return f"[{label}]({url})"
            return f"**{label}**"

        md_chunk = re.sub(r"`(!?\[\[[^\[\]\n]+?\]\])`", r"\1", md_chunk)
        out = WIKILINK_RE.sub(_repl_wl, md_chunk)

        def _repl_md(match: re.Match[str]) -> str:
            label = match.group(1)
            href = match.group(2).strip()
            if href.startswith(("http://", "https://", "mailto:", "vault://", "#")):
                return match.group(0)
            target_only = href.split("#", 1)[0]
            heading = href.split("#", 1)[1] if "#" in href else None
            if target_only.endswith(".md") or target_only.endswith(".canvas"):
                if target_only.endswith(".canvas"):
                    base_dir = Path(from_relpath).parent
                    norm = os.path.normpath((base_dir / target_only).as_posix()).replace("\\", "/")
                    if norm in self.canvases:
                        return f"[{label}](vault://canvas/{quote(norm)})"
                resolved = self.resolve_note(target_only, from_relpath=from_relpath)
                if resolved:
                    url = f"vault://{quote(resolved)}"
                    if heading:
                        url += f"#{quote(heading)}"
                    return f"[{label}]({url})"
            return match.group(0)

        return transform_markdown_math(MD_LINK_RE.sub(_repl_md, out), escape_md=True)

    def _inspect_asset_metadata(self, asset_path: Path) -> dict[str, Any]:
        """Compute content hash and natural dimensions for an embedded SVG/PNG asset."""
        try:
            raw = asset_path.read_bytes()
        except OSError:
            return {}
        digest = hashlib.sha256(raw).hexdigest()[:20]
        ext = asset_path.suffix.lower()
        cache_name = f"{digest}{ext}"
        width, height = 760, 420
        if ext == ".png":
            dims = extract_png_dimensions(raw[:32])
            if dims:
                width, height = dims
        elif ext == ".svg":
            text = raw[:4096].decode("utf-8", errors="ignore")
            m_vb = SVG_VIEWBOX_RE.search(text)
            if m_vb:
                try:
                    w_f = float(m_vb.group(1))
                    h_f = float(m_vb.group(2))
                    if w_f > 0 and h_f > 0:
                        width, height = int(w_f), int(h_f)
                except ValueError:
                    pass
            else:
                m_w = SVG_WIDTH_RE.search(text)
                m_h = SVG_HEIGHT_RE.search(text)
                if m_w and m_h:
                    try:
                        width, height = int(float(m_w.group(1))), int(float(m_h.group(1)))
                    except ValueError:
                        pass
        return {
            "relpath": asset_path.relative_to(self.vault_root).as_posix(),
            "cache_name": cache_name,
            "ext": ext,
            "width": width,
            "height": height,
        }

    def render_note_payload(self, relpath: str) -> dict[str, Any] | None:
        """Parse a note into rich GPUI blocks (frontmatter, callouts, images, diagrams, markdown)."""
        note = self.notes.get(relpath)
        if not note:
            return None
        fpath = self.vault_root / relpath
        try:
            raw_text = fpath.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None
        _, body = parse_frontmatter(raw_text)

        # Strip leading H1 if it duplicates the note title rendered in the editorial header
        body_lines = body.splitlines()
        first_nonempty = next((idx for idx, ln in enumerate(body_lines) if ln.strip()), None)
        if first_nonempty is not None and body_lines[first_nonempty].lstrip().startswith("# "):
            body_lines = body_lines[first_nonempty + 1 :]

        blocks: list[dict[str, Any]] = []
        md_acc: list[str] = []
        lines = body_lines
        i = 0
        n = len(lines)

        def flush_md() -> None:
            if not md_acc:
                return
            chunk = "\n".join(md_acc).strip()
            md_acc.clear()
            if chunk:
                blocks.append(
                    {
                        "type": "markdown",
                        "content": self._transform_inline_links(chunk, relpath),
                    }
                )

        while i < n:
            line = lines[i]
            stripped = line.strip()

            # 1. Check for fenced code block (Mermaid / Structurizr / PlantUML / D2 / Graphviz or code)
            m_fence = FENCE_START_RE.match(stripped)
            if m_fence:
                marker = m_fence.group(1)
                lang = m_fence.group(2).lower()
                code_lines: list[str] = []
                i += 1
                while i < n and not lines[i].strip().startswith(marker):
                    code_lines.append(lines[i])
                    i += 1
                i += 1  # skip closing fence
                code_body = "\n".join(code_lines)
                if lang in ("mermaid", "plantuml", "d2", "dot", "graphviz", "structurizr", "dsl"):
                    flush_md()
                    norm_fmt = (
                        "graphviz"
                        if lang in ("dot", "graphviz")
                        else ("structurizr" if lang == "dsl" else lang)
                    )
                    diag_digest = hashlib.sha256(
                        f"{norm_fmt}\0{code_body}".encode()
                    ).hexdigest()[:20]
                    cache_name = f"diag-{diag_digest}.png"
                    cached_png = diagram_cache_dir() / cache_name
                    d_w, d_h = 1600, 480
                    is_rendered = False
                    if cached_png.is_file():
                        try:
                            dims = extract_png_dimensions(cached_png.read_bytes()[:32])
                            if dims:
                                d_w, d_h = dims
                            is_rendered = True
                        except OSError:
                            pass
                    blocks.append(
                        {
                            "type": "diagram",
                            "format": norm_fmt,
                            "source": code_body,
                            "title": f"{note.title} ({norm_fmt})",
                            "cache_name": cache_name,
                            "width": d_w,
                            "height": d_h,
                            "rendered": is_rendered,
                        }
                    )
                else:
                    md_acc.append(f"```{lang}\n{code_body}\n```")
                continue

            # 2. Check for Obsidian Callout (`> [!note] Title`)
            m_callout = CALLOUT_START_RE.match(stripped)
            if m_callout:
                flush_md()
                kind = m_callout.group(1).lower()
                fold = m_callout.group(2)
                c_title = (m_callout.group(3) or kind.capitalize()).strip()
                c_title = WIKILINK_RE.sub(lambda m: _clean_wikilink_target(m.group(2))[2], c_title)
                c_title = transform_markdown_math(c_title, escape_md=False)
                c_lines: list[str] = []
                i += 1
                while i < n and lines[i].lstrip().startswith(">"):
                    sub = re.sub(r"^\s*>\s?", "", lines[i])
                    c_lines.append(sub)
                    i += 1
                c_body = "\n".join(c_lines).strip()
                blocks.append(
                    {
                        "type": "callout",
                        "kind": kind,
                        "fold": fold,
                        "title": c_title,
                        "content": self._transform_inline_links(c_body, relpath),
                    }
                )
                continue

            # 3. Check for standalone embedded asset (`![[path.svg|caption]]` or `![caption](path.svg)`)
            m_wl_embed = re.fullmatch(r"!\[\[([^\]\n]+)\]\]", stripped)
            m_md_embed = re.fullmatch(r"!\[([^\]]*)\]\(([^)\n]+)\)", stripped)
            if m_wl_embed or m_md_embed:
                if m_wl_embed:
                    inner = m_wl_embed.group(1)
                    target_part, _, caption = _clean_wikilink_target(inner)
                else:
                    assert m_md_embed is not None
                    caption = m_md_embed.group(1).strip()
                    target_part = m_md_embed.group(2).strip()

                asset_path = self.resolve_asset(target_part, from_relpath=relpath)
                if asset_path is not None:
                    flush_md()
                    meta = self._inspect_asset_metadata(asset_path)
                    if meta:
                        blocks.append(
                            {
                                "type": "image",
                                "caption": caption or asset_path.stem,
                                **meta,
                            }
                        )
                    i += 1
                    continue
                # Or embedded note transclusion (`![[Other Note]]`)
                transcluded = self.resolve_note(target_part, from_relpath=relpath)
                if transcluded and transcluded in self.notes:
                    flush_md()
                    t_note = self.notes[transcluded]
                    blocks.append(
                        {
                            "type": "transclusion",
                            "relpath": transcluded,
                            "title": t_note.title,
                            "level": t_note.level,
                            "excerpt": t_note.excerpt,
                        }
                    )
                    i += 1
                    continue

            md_acc.append(line)
            i += 1

        flush_md()

        out_details = [
            {
                "relpath": dst,
                "title": self.notes[dst].title,
                "level": self.notes[dst].level,
                "category": self.notes[dst].category,
            }
            for dst in note.out_links
            if dst in self.notes
        ]

        return {
            "relpath": note.relpath,
            "title": note.title,
            "folder": note.folder,
            "level": note.level,
            "category": note.category,
            "tags": note.tags,
            "aliases": note.aliases,
            "frontmatter": note.frontmatter,
            "size_bytes": note.size_bytes,
            "line_count": note.line_count,
            "headings": note.headings,
            "out_links": out_details,
            "backlinks": self.backlinks_for(relpath),
            "blocks": blocks,
            "raw_markdown": raw_text,
        }

    def load_canvas(self, canvas_relpath: str | None = None) -> dict[str, Any] | None:
        """Load and enrich an Obsidian JSON Canvas (`.canvas`) file."""
        if not self.canvases:
            return None
        target = canvas_relpath if canvas_relpath in self.canvases else self.canvases[0]
        fpath = self.vault_root / target
        try:
            data = json.loads(fpath.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

        raw_nodes = data.get("nodes", [])
        raw_edges = data.get("edges", [])
        nodes: list[dict[str, Any]] = []
        min_x, min_y = 10**9, 10**9
        max_x, max_y = -(10**9), -(10**9)

        for nd in raw_nodes:
            if not isinstance(nd, dict):
                continue
            x = int(nd.get("x", 0))
            y = int(nd.get("y", 0))
            w = int(nd.get("width", 320))
            h = int(nd.get("height", 180))
            min_x = min(min_x, x)
            min_y = min(min_y, y)
            max_x = max(max_x, x + w)
            max_y = max(max_y, y + h)

            ntype = str(nd.get("type", "text"))
            file_rel = nd.get("file")
            resolved_rel: str | None = None
            title = str(nd.get("label") or "")
            excerpt = str(nd.get("text") or "")
            level: int | None = None
            category = "general"

            if ntype == "file" and isinstance(file_rel, str):
                resolved_rel = self.resolve_note(file_rel)
                if resolved_rel and resolved_rel in self.notes:
                    n_obj = self.notes[resolved_rel]
                    title = n_obj.title
                    excerpt = n_obj.excerpt
                    level = n_obj.level
                    category = n_obj.category
                else:
                    title = Path(file_rel).stem
            elif ntype == "text":
                lines = [ln.strip() for ln in excerpt.splitlines() if ln.strip()]
                if lines and lines[0].startswith("#"):
                    title = lines[0].lstrip("#").strip()
                    excerpt = " ".join(lines[1:])[:160]
                elif lines:
                    title = lines[0][:60]

            nodes.append(
                {
                    "id": str(nd.get("id", "")),
                    "type": ntype,
                    "x": x,
                    "y": y,
                    "width": w,
                    "height": h,
                    "color": str(nd.get("color", "")),
                    "title": title,
                    "excerpt": excerpt,
                    "file": resolved_rel or file_rel,
                    "level": level,
                    "category": category,
                }
            )

        if min_x > max_x:
            min_x, min_y, max_x, max_y = 0, 0, 1200, 800

        # Ensure groups render behind file/text nodes
        nodes.sort(key=lambda item: (0 if item["type"] == "group" else 1, item["y"], item["x"]))

        edges_out = [
            {
                "id": str(e.get("id", "")),
                "fromNode": str(e.get("fromNode", "")),
                "toNode": str(e.get("toNode", "")),
                "fromSide": str(e.get("fromSide", "right")),
                "toSide": str(e.get("toSide", "left")),
                "label": str(e.get("label", "")),
                "color": str(e.get("color", "")),
            }
            for e in raw_edges
            if isinstance(e, dict)
        ]

        pad = 60
        vb_x = min_x - pad
        vb_y = min_y - pad
        vb_w = max(400, (max_x - min_x) + pad * 2)
        vb_h = max(300, (max_y - min_y) + pad * 2)

        node_by_id = {n["id"]: n for n in nodes if n.get("id")}
        canvas_colors = {
            "1": "#d46a6a",
            "2": "#d48852",
            "3": "#c9a24b",
            "4": "#4ea87d",
            "5": "#489fb5",
            "6": "#916dd5",
        }

        def _anchor(nd: dict[str, Any], side: str) -> tuple[float, float]:
            nx, ny = float(nd["x"]), float(nd["y"])
            nw, nh = float(nd["width"]), float(nd["height"])
            if side == "left":
                return nx, ny + nh / 2.0
            if side == "top":
                return nx + nw / 2.0, ny
            if side == "bottom":
                return nx + nw / 2.0, ny + nh
            return nx + nw, ny + nh / 2.0

        def _ctrl_delta(side: str, dist: float) -> tuple[float, float]:
            d = max(48.0, min(180.0, dist * 0.42))
            if side == "left":
                return -d, 0.0
            if side == "top":
                return 0.0, -d
            if side == "bottom":
                return 0.0, d
            return d, 0.0

        svg_parts = [
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{vb_x} {vb_y} {vb_w} {vb_h}" '
            f'width="{vb_w}" height="{vb_h}">',
            "<defs>",
            '<marker id="cv-arrow" viewBox="0 0 10 10" refX="8" refY="5" '
            'markerWidth="6" markerHeight="6" orient="auto-start-reverse">',
            '<path d="M 0 1.5 L 9 5 L 0 8.5 z" fill="#64748b"/>',
            "</marker>",
            "</defs>",
        ]
        for edge in edges_out:
            src_nd = node_by_id.get(edge["fromNode"])
            dst_nd = node_by_id.get(edge["toNode"])
            if not src_nd or not dst_nd:
                continue
            x1, y1 = _anchor(src_nd, edge["fromSide"])
            x2, y2 = _anchor(dst_nd, edge["toSide"])
            dist = ((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5
            dx1, dy1 = _ctrl_delta(edge["fromSide"], dist)
            dx2, dy2 = _ctrl_delta(edge["toSide"], dist)
            stroke = canvas_colors.get(edge["color"], "#64748b")
            svg_parts.append(
                f'<path d="M {x1:.1f} {y1:.1f} C {x1 + dx1:.1f} {y1 + dy1:.1f}, '
                f'{x2 + dx2:.1f} {y2 + dy2:.1f}, {x2:.1f} {y2:.1f}" '
                f'fill="none" stroke="{stroke}" stroke-width="2" stroke-opacity="0.78" '
                f'marker-end="url(#cv-arrow)"/>'
            )
            if edge["label"]:
                mx = (x1 + x2) / 2.0
                my = (y1 + y2) / 2.0 - 6.0
                lbl = xml_escape(edge["label"][:42])
                svg_parts.append(
                    f'<text x="{mx:.1f}" y="{my:.1f}" text-anchor="middle" '
                    f'fill="#94a3b8" font-family="sans-serif" font-size="11">{lbl}</text>'
                )
        svg_parts.append("</svg>")
        svg_bytes = "\n".join(svg_parts).encode("utf-8")
        svg_hash = hashlib.sha256(svg_bytes).hexdigest()[:16]

        return {
            "relpath": target,
            "title": Path(target).stem,
            "available": self.canvases,
            "bounds": {
                "min_x": min_x,
                "min_y": min_y,
                "max_x": max_x,
                "max_y": max_y,
                "width": max(400, max_x - min_x),
                "height": max(300, max_y - min_y),
                "vb_x": vb_x,
                "vb_y": vb_y,
                "vb_w": vb_w,
                "vb_h": vb_h,
            },
            "svg_cache_name": f"canvas-{svg_hash}.svg",
            "svg_b64": base64.b64encode(svg_bytes).decode("ascii"),
            "nodes": nodes,
            "edges": edges_out,
        }
