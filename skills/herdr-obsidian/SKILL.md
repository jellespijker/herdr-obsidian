---
name: herdr-obsidian
description: "Navigate, search, read, edit, and display Obsidian Vault notes, [[wikilinks]], backlinks, Squarified DiskTree treemaps, JSON Canvas (.canvas) maps, 2D Knowledge Graphs, and herdr-kanban Linked-Knowledge briefs inside a Herdr-App GPUI side pane (`mods/herdr-obsidian`) or Herdr TUI. Use whenever working in a repository with an Obsidian Vault (`.obsidian` or `docs/.obsidian`), resolving `[[wikilinks]]`, showing architecture notes or canvases to the user, or syncing a Kanban ticket's Linked-Knowledge brief."
---

# herdr-obsidian

`herdr-obsidian` integrates an Obsidian Vault directly into the **Herdr desktop app** (`herdr-app` native GPUI mod `herdr-obsidian`) and the **`herdr` TUI**, synced with coding agents and `herdr-kanban` tickets across local and remote (`hc`) machines.

## Show a Note, Canvas, DiskTree, Graph, or Ticket Brief in the Side Pane

To open or focus a note, `[[Wikilink]]`, alias, JSON Canvas (`.canvas`), DiskTree treemap, 2D Knowledge Graph, or active Kanban ticket brief in the user's Herdr-App side pane:

```bash
herdr-obsidian open "00 - Home - Architecture MOC"
herdr-obsidian open "L1 - Event Bus Architecture"
herdr-obsidian open --view treemap
herdr-obsidian open "01 - System Architecture Map.canvas" --view canvas
herdr-obsidian open --view graph
herdr-obsidian open --view ticket
```

You can also emit an inline `[obsidian: <Note Title or Alias>]` marker in your response:

```text
[obsidian: L1 - Event Bus Architecture]
```

When `Sync ●` is active in the `herdr-obsidian` GPUI panel, the viewer automatically follows the latest `herdr-obsidian open` call or `[obsidian: ...]` marker in the active terminal.

## Search, Read, Inspect Backlinks, and Edit Vault Notes from the CLI

```bash
# Full-text, title, alias, #tag, and L0..L3 progressive-disclosure search
herdr-obsidian search "Consensus Lease" --level 2
herdr-obsidian search "#moc" --json

# Resolve any [[Wikilink]], alias, or relative path and print Markdown + frontmatter
herdr-obsidian read "L2 - Raft Log Replication" --sync

# Inspect incoming backlinks (with context snippets) and outgoing wikilinks
herdr-obsidian backlinks "ADR-0001"

# Resolve the active herdr-kanban ticket's Linked-Knowledge Brief
herdr-obsidian ticket backend#42 --sync

# Create or update a Markdown note inside the vault
herdr-obsidian write "01-Product-Process-Architecture/New Note.md" --stdin <<'EOF'
---
title: "New Note"
level: 2
---
# New Note
EOF
```

## Setup & Diagnostics

```bash
herdr-obsidian install-skill --notify      # Link CLI, agent skills, and Herdr-App GPUI mod
herdr-obsidian setup-keys --notify         # Bind Ctrl+Shift+O in Herdr-App & prefix+u in Herdr TUI
herdr-obsidian doctor                      # Verify vault discovery, GPUI mod, and skill links
```
