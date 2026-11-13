"""Unit and integration tests for `herdr-obsidian`."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from herdr_obsidian import cli, keys, skill
from herdr_obsidian.ticket_sync import resolve_ticket_brief
from herdr_obsidian.treemap import build_knowledge_graph, build_treemap
from herdr_obsidian.vault import VaultIndex, discover_vault, parse_frontmatter


def test_parse_frontmatter_handles_lists_and_scalars() -> None:
    sample = """---
title: "Sample Architecture Note"
level: 2
aliases:
  - "Sample Alias"
  - "Short"
tags: [distributed-systems, storage, level/L2]
trl: "production"
enabled: true
---

# Heading 1

Body paragraph with [[Target Note|Custom Label]].
"""
    fm, body = parse_frontmatter(sample)
    assert fm["title"] == "Sample Architecture Note"
    assert fm["level"] == 2
    assert fm["aliases"] == ["Sample Alias", "Short"]
    assert fm["tags"] == ["distributed-systems", "storage", "level/L2"]
    assert fm["trl"] == "production"
    assert fm["enabled"] is True
    assert body.startswith("# Heading 1")


def test_synthetic_vault_indexing_wikilinks_backlinks_and_callouts(tmp_path: Path) -> None:
    vault_dir = tmp_path / "vault"
    (vault_dir / ".obsidian").mkdir(parents=True)
    (vault_dir / "00-Map-Of-Content (MOC)").mkdir(parents=True)
    (vault_dir / "01-Product-Process-Architecture").mkdir(parents=True)
    (vault_dir / "07-Canvases").mkdir(parents=True)
    (vault_dir / "99-Assets").mkdir(parents=True)

    home_md = vault_dir / "00-Map-Of-Content (MOC)" / "00 - Home MOC.md"
    home_md.write_text(
        """---
title: "Home Map-Of-Content"
level: 0
aliases:
  - "Home MOC"
tags:
  - "moc"
---

# Home Map-Of-Content

> [!important] Core Principle
> Links to [[L1 - Event Bus Protocol|Event Bus Spec]].

![[99-Assets/arch.svg|Architecture Diagram]]

```mermaid
flowchart LR
  A --> B
```
""",
        encoding="utf-8",
    )

    wire_md = vault_dir / "01-Product-Process-Architecture" / "L1 - Event Bus Protocol.md"
    wire_md.write_text(
        """---
title: "Event Bus Protocol"
level: 1
tags:
  - "event-bus"
---

# Event Bus Protocol

Back-reference to [[Home MOC]] and section [[Home MOC#Home Map-Of-Content]].
""",
        encoding="utf-8",
    )

    svg_file = vault_dir / "99-Assets" / "arch.svg"
    svg_file.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 600 300">'
        '<rect width="600" height="300"/></svg>',
        encoding="utf-8",
    )

    canvas_file = vault_dir / "07-Canvases" / "01 - Overview.canvas"
    canvas_file.write_text(
        json.dumps(
            {
                "nodes": [
                    {
                        "id": "g1",
                        "type": "group",
                        "label": "Core Group",
                        "x": 0,
                        "y": 0,
                        "width": 800,
                        "height": 400,
                        "color": "4",
                    },
                    {
                        "id": "n1",
                        "type": "file",
                        "file": "01-Product-Process-Architecture/L1 - Event Bus Protocol.md",
                        "x": 40,
                        "y": 60,
                        "width": 320,
                        "height": 180,
                        "color": "5",
                    },
                ],
                "edges": [{"id": "e1", "fromNode": "g1", "toNode": "n1", "label": "contains"}],
            }
        ),
        encoding="utf-8",
    )

    discovered = discover_vault(vault_dir / "01-Product-Process-Architecture")
    assert discovered == vault_dir

    idx = VaultIndex(vault_dir)
    assert len(idx.notes) == 2
    assert len(idx.canvases) == 1

    # Alias resolution
    resolved_home = idx.resolve_note("Home MOC")
    assert resolved_home == "00-Map-Of-Content (MOC)/00 - Home MOC.md"

    # Backlinks & outgoing links
    wire_rel = "01-Product-Process-Architecture/L1 - Event Bus Protocol.md"
    backlinks = idx.backlinks_for(wire_rel)
    assert len(backlinks) == 1
    assert backlinks[0]["source"] == resolved_home

    # Rich blocks (callout, image, diagram)
    payload = idx.render_note_payload(resolved_home)
    assert payload is not None
    b_types = [b["type"] for b in payload["blocks"]]
    assert "callout" in b_types
    assert "image" in b_types
    assert "diagram" in b_types

    # Treemap & Knowledge Graph & Canvas
    tm = build_treemap(idx, width=800, height=500, metric="links")
    assert tm["total_notes"] == 2
    assert len(tm["cells"]) == 2

    gr = build_knowledge_graph(idx, center_relpath=resolved_home, mode="local")
    assert len(gr["nodes"]) == 2
    assert len(gr["edges"]) >= 1

    cv = idx.load_canvas()
    assert cv is not None
    assert len(cv["nodes"]) == 2
    file_node = next(n for n in cv["nodes"] if n["type"] == "file")
    assert file_node["title"] == "Event Bus Protocol"
    assert file_node["level"] == 1


def test_ticket_brief_and_cli_app_state_integration(tmp_path: Path) -> None:
    vault_dir = tmp_path / "acme-platform" / "docs"
    (vault_dir / ".obsidian").mkdir(parents=True)
    (vault_dir / "00-Map-Of-Content (MOC)").mkdir(parents=True)
    (vault_dir / "01-Product-Process-Architecture").mkdir(parents=True)

    (vault_dir / "00-Map-Of-Content (MOC)" / "00 - Home Map-Of-Content.md").write_text(
        """---
title: "00 - Home Map-Of-Content"
level: 0
tags: [moc, architecture]
---
# Home Map-Of-Content
Links to [[L1 - Event Bus Architecture]].
""",
        encoding="utf-8",
    )
    (vault_dir / "01-Product-Process-Architecture" / "L1 - Event Bus Architecture.md").write_text(
        """---
title: "L1 - Event Bus Architecture"
level: 1
tags: [architecture, event-bus]
---
# L1 - Event Bus Architecture
Backlink to [[00 - Home Map-Of-Content]].
""",
        encoding="utf-8",
    )

    idx = VaultIndex(vault_dir)
    home_rel = idx.default_home_note()
    assert home_rel is not None
    assert "Home Map-Of-Content" in home_rel

    brief = resolve_ticket_brief(idx, vault_dir.parent, "backend#42")
    assert brief["ticket_id"] == "backend#42"
    assert any(len(sec["items"]) > 0 for sec in brief["sections"])

    rc = cli.main(["doctor", "--json", "--vault", str(vault_dir)])
    assert rc == 0

    mod_dir, state = skill.app_mod_status()
    assert state == "installed"

    proc = subprocess.run(
        ["herdr-app", "check", str(mod_dir)],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert proc.returncode == 0, proc.stderr


def test_keys_setup_and_remove_roundtrip(tmp_path: Path) -> None:
    keys_file = tmp_path / "keys.json"
    keys_file.write_text(
        json.dumps({"global": {"ctrl-shift-o": "pane.split:right"}}, indent=2),
        encoding="utf-8",
    )
    ok, _ = keys.setup_app_keys("ctrl-shift-o", path=keys_file)
    assert ok
    loaded = json.loads(keys_file.read_text(encoding="utf-8"))
    assert loaded["global"]["ctrl-shift-o"]["args"]["mod"] == "herdr-obsidian"
    assert loaded["mod:herdr-obsidian"]["ctrl-shift-o"] == "pane.close"

    ok_rem, _ = keys.setup_app_keys(remove=True, path=keys_file)
    assert ok_rem
    restored = json.loads(keys_file.read_text(encoding="utf-8"))
    assert restored["global"]["ctrl-shift-o"] == "pane.split:right"
    assert "mod:herdr-obsidian" not in restored


def test_latex_math_rendering_and_markdown_escape() -> None:
    from herdr_obsidian.math_render import latex_to_unicode, transform_markdown_math

    assert latex_to_unicode(r"L_1") == "L₁"
    assert latex_to_unicode(r"L_\infty", escape_md=True) == r"L\_∞"
    assert latex_to_unicode(r"\text{mm}^2") == "mm²"
    assert latex_to_unicode(r"90^\circ") == "90°"
    assert latex_to_unicode(r"\sqrt{\Delta x^2 + \Delta y^2}") == "√(Δ x² + Δ y²)"

    md = (
        "Tracks $D_L(t)$ versus $U_L(t)$ on step $L-1$ with "
        r"$[\tau_{\text{sync}}(k), \tau_{\text{raft}}(k)]$ and `code $not_math$`."
    )
    rendered = transform_markdown_math(md, escape_md=True)
    assert "$" not in rendered.replace("`code $not_math$`", "")
    assert r"D\_L(t)" in rendered
    assert r"U\_L(t)" in rendered
    assert r"[τ\_sync(k), τ\_raft(k)]" in rendered
    assert "`code $not_math$`" in rendered

