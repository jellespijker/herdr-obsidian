"""Squarified DiskTree Treemap layout and 2D Knowledge Graph layout for Obsidian Vaults."""

from __future__ import annotations

import base64
import hashlib
import math
from typing import Any

from .vault import NoteSummary, VaultIndex

CATEGORY_SPECS: list[dict[str, Any]] = [
    {
        "id": "moc",
        "label": "Map-Of-Content (MOC)",
        "short": "MOC",
        "color": "#c95b78",
        "fill": "#261922",
        "border": "#522939",
    },
    {
        "id": "product-architecture",
        "label": "Product & Architecture",
        "short": "Arch",
        "color": "#5882c9",
        "fill": "#172133",
        "border": "#2d4369",
    },
    {
        "id": "quality-standards",
        "label": "Quality & Standards",
        "short": "Quality",
        "color": "#46a377",
        "fill": "#162621",
        "border": "#254a3d",
    },
    {
        "id": "ip-portfolio",
        "label": "Research & IP Portfolio",
        "short": "IP",
        "color": "#8f6bc9",
        "fill": "#201b2e",
        "border": "#3c3159",
    },
    {
        "id": "formal-proofs",
        "label": "Formal Verification",
        "short": "Proofs",
        "color": "#439fb5",
        "fill": "#15242b",
        "border": "#244754",
    },
    {
        "id": "glossary",
        "label": "Domain Glossary",
        "short": "Glossary",
        "color": "#c49644",
        "fill": "#252017",
        "border": "#4a3e25",
    },
    {
        "id": "investigation-reports",
        "label": "Investigation Reports",
        "short": "Reports",
        "color": "#c97049",
        "fill": "#261c18",
        "border": "#4d3429",
    },
    {
        "id": "adr-architecture",
        "label": "ADR & C4 Architecture",
        "short": "ADR/C4",
        "color": "#6084b5",
        "fill": "#182230",
        "border": "#2f4461",
    },
    {
        "id": "general",
        "label": "General Notes",
        "short": "Notes",
        "color": "#64748b",
        "fill": "#1a2029",
        "border": "#313d4f",
    },
]

CATEGORY_BY_ID = {spec["id"]: spec for spec in CATEGORY_SPECS}


def _worst_aspect(row: list[float], side: float) -> float:
    if not row or side <= 0:
        return float("inf")
    s = sum(row)
    if s <= 0:
        return float("inf")
    r_max = max(row)
    r_min = max(1e-9, min(row))
    side2 = side * side
    s2 = s * s
    return max((side2 * r_max) / s2, s2 / (side2 * r_min))


def squarify_rects(
    items: list[tuple[str, float]],
    x: float,
    y: float,
    w: float,
    h: float,
) -> dict[str, tuple[float, float, float, float]]:
    """Compute deterministic Bruls-Huizing-van Wijk squarified treemap rectangles in `[x, y, w, h]`."""
    out: dict[str, tuple[float, float, float, float]] = {}
    filtered = [(k, max(1.0, float(v))) for k, v in items if v > 0]
    if not filtered or w <= 2 or h <= 2:
        return out

    total = sum(v for _, v in filtered)
    area = w * h
    if total <= 0 or area <= 0:
        return out

    scaled = [(k, v * area / total) for k, v in sorted(filtered, key=lambda kv: (-kv[1], kv[0]))]
    cx, cy, cw, ch = x, y, w, h
    idx = 0
    n = len(scaled)

    while idx < n and cw > 0.5 and ch > 0.5:
        horizontal = cw >= ch
        short_side = ch if horizontal else cw
        row_keys: list[str] = [scaled[idx][0]]
        row_vals: list[float] = [scaled[idx][1]]
        idx += 1

        while idx < n:
            cand_key, cand_val = scaled[idx]
            if _worst_aspect([*row_vals, cand_val], short_side) <= _worst_aspect(row_vals, short_side):
                row_keys.append(cand_key)
                row_vals.append(cand_val)
                idx += 1
            else:
                break

        row_sum = sum(row_vals)
        thickness = row_sum / max(1e-6, short_side)
        if horizontal:
            ry = cy
            for rk, rv in zip(row_keys, row_vals, strict=False):
                rh = rv / max(1e-6, thickness)
                out[rk] = (cx, ry, min(cw, thickness), min(ch, rh))
                ry += rh
            cx += thickness
            cw = max(0.0, cw - thickness)
        else:
            rx = cx
            for rk, rv in zip(row_keys, row_vals, strict=False):
                rw = rv / max(1e-6, thickness)
                out[rk] = (rx, cy, min(cw, rw), min(ch, thickness))
                rx += rw
            cy += thickness
            ch = max(0.0, ch - thickness)

    return out


def _metric_value(note: NoteSummary, metric: str) -> float:
    if metric == "lines":
        return float(max(10, note.line_count))
    if metric == "links":
        return float(max(2, len(note.in_links) * 2 + len(note.out_links) + 1))
    return float(max(256, note.size_bytes))


def build_treemap(
    index: VaultIndex,
    *,
    width: int = 920,
    height: int = 580,
    metric: str = "bytes",
    zoom_folder: str = "",
    level_filter: int | None = None,
) -> dict[str, Any]:
    """Build a 2-level hierarchical Squarified DiskTree Treemap (top-level groups -> note cells)."""
    zf = zoom_folder.strip("/")
    notes = [
        n
        for n in index.notes.values()
        if (not zf or n.relpath.startswith(zf + "/") or n.folder == zf)
        and (level_filter is None or n.level == level_filter)
    ]

    groups: dict[str, list[NoteSummary]] = {}
    for note in notes:
        rel_after = note.relpath[len(zf) + 1 :] if zf and note.relpath.startswith(zf + "/") else note.relpath
        parts = rel_after.split("/")
        grp_key = parts[0] if len(parts) > 1 else "(root)"
        groups.setdefault(grp_key, []).append(note)

    group_weights = [
        (g_key, sum(_metric_value(n, metric) for n in g_notes)) for g_key, g_notes in groups.items()
    ]
    group_rects = squarify_rects(group_weights, 0.0, 0.0, float(width), float(height))

    group_out: list[dict[str, Any]] = []
    cells_out: list[dict[str, Any]] = []

    for g_key, g_notes in sorted(groups.items()):
        if g_key not in group_rects:
            continue
        gx, gy, gw, gh = group_rects[g_key]
        cat_id = g_notes[0].category if g_notes else "general"
        cat_spec = CATEGORY_BY_ID.get(cat_id, CATEGORY_BY_ID["general"])
        folder_path = f"{zf}/{g_key}".strip("/") if g_key != "(root)" else zf

        group_out.append(
            {
                "id": g_key,
                "label": g_key,
                "folder": folder_path,
                "category": cat_id,
                "color": cat_spec["color"],
                "fill": cat_spec["fill"],
                "border": cat_spec["border"],
                "count": len(g_notes),
                "x": round(gx),
                "y": round(gy),
                "w": max(16, round(gw)),
                "h": max(16, round(gh)),
            }
        )

        header_h = 20.0 if gh >= 42 else 0.0
        pad = 3.0 if gw >= 24 and gh >= 24 else 1.0
        inner_x = gx + pad
        inner_y = gy + header_h + pad
        inner_w = max(4.0, gw - pad * 2)
        inner_h = max(4.0, gh - header_h - pad * 2)

        note_weights = [(n.relpath, _metric_value(n, metric)) for n in g_notes]
        note_rects = squarify_rects(note_weights, inner_x, inner_y, inner_w, inner_h)
        for note in g_notes:
            rect = note_rects.get(note.relpath)
            if not rect:
                continue
            nx, ny, nw, nh = rect
            if nw < 3 or nh < 3:
                continue
            spec = CATEGORY_BY_ID.get(note.category, cat_spec)
            cells_out.append(
                {
                    "relpath": note.relpath,
                    "title": note.title,
                    "level": note.level,
                    "category": note.category,
                    "color": spec["color"],
                    "fill": spec["fill"],
                    "border": spec["border"],
                    "size_bytes": note.size_bytes,
                    "line_count": note.line_count,
                    "links": len(note.in_links) + len(note.out_links),
                    "x": round(nx),
                    "y": round(ny),
                    "w": max(4, round(nw)),
                    "h": max(4, round(nh)),
                }
            )

    return {
        "width": width,
        "height": height,
        "metric": metric,
        "zoom_folder": zf,
        "level_filter": level_filter,
        "total_notes": len(notes),
        "categories": CATEGORY_SPECS,
        "groups": group_out,
        "cells": cells_out,
    }


def build_knowledge_graph(
    index: VaultIndex,
    *,
    center_relpath: str | None = None,
    mode: str = "local",
    max_nodes: int = 48,
) -> dict[str, Any]:
    """Compute a 2D Knowledge Graph layout (`local` ego-graph or `global` L0->L3 hub map)."""
    center = center_relpath if center_relpath and center_relpath in index.notes else index.default_home_note()
    if not center or center not in index.notes:
        return {"mode": mode, "center": None, "nodes": [], "edges": []}

    selected_paths: list[str] = []
    if mode == "local":
        local_cap = min(max_nodes, 23)
        selected_paths.append(center)
        center_note = index.notes[center]
        in_set = set(center_note.in_links)
        out_set = set(center_note.out_links)
        hop1_raw = list(dict.fromkeys([*center_note.out_links, *center_note.in_links]))
        hop1_ranked = sorted(
            [p for p in hop1_raw if p in index.notes and p != center],
            key=lambda p: (
                0 if (p in in_set and p in out_set) else (1 if p in out_set else 2),
                -(len(index.notes[p].in_links) * 2 + len(index.notes[p].out_links)),
                p,
            ),
        )
        for p in hop1_ranked:
            if len(selected_paths) < local_cap:
                selected_paths.append(p)
        # Fill up to local_cap with highest-degree 2-hop neighbors
        if len(selected_paths) < local_cap:
            hop2_cands: list[tuple[int, str]] = []
            for p1 in hop1_ranked:
                n1 = index.notes.get(p1)
                if not n1:
                    continue
                for p2 in [*n1.out_links, *n1.in_links]:
                    if p2 in index.notes and p2 not in selected_paths:
                        deg = len(index.notes[p2].in_links) + len(index.notes[p2].out_links)
                        hop2_cands.append((deg, p2))
            for _, p2 in sorted(hop2_cands, reverse=True):
                if p2 not in selected_paths and len(selected_paths) < local_cap:
                    selected_paths.append(p2)
    else:
        # Global hierarchy view: up to 7 top hubs per L0..L3 tier so rows never crowd
        tiers_rank: dict[int, list[NoteSummary]] = {0: [], 1: [], 2: [], 3: []}
        for n in index.notes.values():
            lvl = n.level if n.level in (0, 1, 2, 3) else (0 if n.category == "moc" else 2)
            tiers_rank[lvl].append(n)
        for lvl in (0, 1, 2, 3):
            tiers_rank[lvl].sort(
                key=lambda n: (
                    0 if n.relpath == center else 1,
                    -(len(n.in_links) * 2 + len(n.out_links)),
                    n.relpath,
                )
            )
            for n in tiers_rank[lvl][:7]:
                if n.relpath not in selected_paths:
                    selected_paths.append(n.relpath)
        if center not in selected_paths:
            selected_paths.insert(0, center)

    selected_set = set(selected_paths)
    nodes_out: list[dict[str, Any]] = []
    pos_by_path: dict[str, tuple[int, int]] = {}

    if mode == "local":
        # Two-shell staggered elliptical layout: up to 8 on inner ring, up to 14 on outer ring
        pos_by_path[center] = (0, 0)
        neighbors = [p for p in selected_paths if p != center]
        shell1 = neighbors[:8]
        shell2 = neighbors[8:22]

        r1_rx, r1_ry = 300.0, 200.0
        for idx, p in enumerate(shell1):
            angle = (2.0 * math.pi * idx) / max(1, len(shell1)) - math.pi / 2.0
            pos_by_path[p] = (round(r1_rx * math.cos(angle)), round(r1_ry * math.sin(angle)))

        r2_rx, r2_ry = 560.0, 365.0
        offset = math.pi / max(1, len(shell2))
        for idx, p in enumerate(shell2):
            angle = (2.0 * math.pi * idx) / max(1, len(shell2)) - math.pi / 2.0 + offset
            pos_by_path[p] = (round(r2_rx * math.cos(angle)), round(r2_ry * math.sin(angle)))
    else:
        # Layered L0 -> L1 -> L2 -> L3 horizontal bands with generous 220px column pitch
        tiers: dict[int, list[str]] = {0: [], 1: [], 2: [], 3: []}
        for p in selected_paths:
            n = index.notes[p]
            lvl = n.level if n.level in (0, 1, 2, 3) else (0 if n.category == "moc" else 2)
            tiers[lvl].append(p)
        for lvl, p_list in tiers.items():
            y = (lvl - 1) * 195
            cols = max(1, len(p_list))
            spacing = 215
            start_x = -((cols - 1) * spacing) // 2
            for idx, p in enumerate(p_list):
                pos_by_path[p] = (start_x + idx * spacing, y)

    for p in selected_paths:
        n = index.notes[p]
        x, y = pos_by_path.get(p, (0, 0))
        spec = CATEGORY_BY_ID.get(n.category, CATEGORY_BY_ID["general"])
        nodes_out.append(
            {
                "relpath": p,
                "title": n.title,
                "level": n.level,
                "category": n.category,
                "color": spec["color"],
                "fill": spec["fill"],
                "border": spec["border"],
                "in_degree": len(n.in_links),
                "out_degree": len(n.out_links),
                "is_center": p == center,
                "x": x,
                "y": y,
            }
        )

    edges_out: list[dict[str, str]] = []
    for src in selected_paths:
        src_note = index.notes[src]
        for dst in src_note.out_links:
            if dst in selected_set:
                edges_out.append({"from": src, "to": dst})
    edges_out = edges_out[:160]

    # Build vector SVG underlay for graph edges and hop rings / tier swimlanes
    xs = [nd["x"] for nd in nodes_out] or [0]
    ys = [nd["y"] for nd in nodes_out] or [0]
    min_x = min(*xs, -420) - 180
    max_x = max(*xs, 420) + 180
    min_y = min(*ys, -300) - 120
    max_y = max(*ys, 300) + 120
    vb_w = max(800, max_x - min_x)
    vb_h = max(560, max_y - min_y)

    svg_parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{min_x} {min_y} {vb_w} {vb_h}" '
        f'width="{vb_w}" height="{vb_h}">',
        "<defs>",
        '<marker id="gr-arrow-hi" viewBox="0 0 10 10" refX="8" refY="5" '
        'markerWidth="5.5" markerHeight="5.5" orient="auto-start-reverse">',
        '<path d="M 0 1.5 L 9 5 L 0 8.5 z" fill="#6084b5"/>',
        "</marker>",
        '<marker id="gr-arrow-dim" viewBox="0 0 10 10" refX="8" refY="5" '
        'markerWidth="5" markerHeight="5" orient="auto-start-reverse">',
        '<path d="M 0 1.5 L 9 5 L 0 8.5 z" fill="#334155"/>',
        "</marker>",
        "</defs>",
    ]

    if mode == "local":
        svg_parts.append(
            '<ellipse cx="0" cy="0" rx="300" ry="200" fill="none" '
            'stroke="#1e293b" stroke-width="1.5" stroke-dasharray="5 5"/>'
        )
        svg_parts.append(
            '<text x="0" y="-208" text-anchor="middle" fill="#475569" '
            'font-family="sans-serif" font-size="10.5">PRIMARY NEIGHBORS</text>'
        )
        if any(abs(nd["x"]) > 340 or abs(nd["y"]) > 230 for nd in nodes_out):
            svg_parts.append(
                '<ellipse cx="0" cy="0" rx="560" ry="365" fill="none" '
                'stroke="#17202e" stroke-width="1.5" stroke-dasharray="4 6"/>'
            )
            svg_parts.append(
                '<text x="0" y="-373" text-anchor="middle" fill="#334155" '
                'font-family="sans-serif" font-size="10.5">EXTENDED NEIGHBORHOOD</text>'
            )
    else:
        tier_labels = {
            0: ("L0 · ROOT & MOC HUBS", "#c95b78"),
            1: ("L1 · SYSTEM ARCHITECTURE", "#5882c9"),
            2: ("L2 · SUBSYSTEM & MATHEMATICAL MODELS", "#46a377"),
            3: ("L3 · CONCRETE IMPLEMENTATION & PROOFS", "#8f6bc9"),
        }
        for lvl, (t_label, t_color) in tier_labels.items():
            ty = (lvl - 1) * 195
            svg_parts.append(
                f'<line x1="{min_x + 40}" y1="{ty}" x2="{max_x - 40}" y2="{ty}" '
                f'stroke="{t_color}" stroke-opacity="0.18" stroke-width="1" stroke-dasharray="4 6"/>'
            )
            svg_parts.append(
                f'<text x="{min_x + 48}" y="{ty - 36}" fill="{t_color}" fill-opacity="0.7" '
                f'font-family="sans-serif" font-size="10.5" font-weight="600">{t_label}</text>'
            )

    # Draw non-center edges first, then center-connected edges on top
    for pass_center in (False, True):
        for edge in edges_out:
            src_p, dst_p = edge["from"], edge["to"]
            is_incident = src_p == center or dst_p == center
            if is_incident != pass_center:
                continue
            x1, y1 = pos_by_path.get(src_p, (0, 0))
            x2, y2 = pos_by_path.get(dst_p, (0, 0))
            if (x1, y1) == (x2, y2):
                continue
            mx = (x1 + x2) / 2.0
            my = (y1 + y2) / 2.0
            dx = x2 - x1
            dy = y2 - y1
            # Slight perpendicular curve offset so bidirectional edges separate cleanly
            cx_pt = mx - dy * 0.08
            cy_pt = my + dx * 0.08
            stroke = "#5882c9" if is_incident else "#334155"
            opacity = "0.72" if is_incident else "0.38"
            width_px = "1.75" if is_incident else "1.15"
            marker = "url(#gr-arrow-hi)" if is_incident else "url(#gr-arrow-dim)"
            svg_parts.append(
                f'<path d="M {x1} {y1} Q {cx_pt:.1f} {cy_pt:.1f} {x2} {y2}" '
                f'fill="none" stroke="{stroke}" stroke-opacity="{opacity}" '
                f'stroke-width="{width_px}" marker-end="{marker}"/>'
            )

    svg_parts.append("</svg>")
    svg_bytes = "\n".join(svg_parts).encode("utf-8")
    svg_hash = hashlib.sha256(svg_bytes).hexdigest()[:16]

    return {
        "mode": mode,
        "center": center,
        "bounds": {
            "vb_x": min_x,
            "vb_y": min_y,
            "vb_w": vb_w,
            "vb_h": vb_h,
        },
        "svg_cache_name": f"graph-{svg_hash}.svg",
        "svg_b64": base64.b64encode(svg_bytes).decode("ascii"),
        "nodes": nodes_out,
        "edges": edges_out,
    }
