# AGENTS.md — `herdr-obsidian`

Instructions for coding agents working in `herdr-obsidian`.

- **Runtime**: Python 3.11+ standard library (`src/herdr_obsidian/`) + Herdr-App GPUI JavaScript mod (`mods/herdr-obsidian/main.js`).
- **Verification**:
  1. `pytest` (unit & integration tests in `tests/`)
  2. `herdr-obsidian install-app-mod`
  3. `herdr-app check ~/.config/herdr-app/mods/herdr-obsidian` (must exit `0` with zero errors)
