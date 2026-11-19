#!/bin/sh
# Build step run by `herdr plugin install`: verify platform & install skill/mod.
set -eu
case "$(uname -s)" in
  Linux|Darwin) ;;
  *) echo "herdr-obsidian supports Linux and macOS; $(uname -s) is not supported yet." >&2; exit 1 ;;
esac

chmod +x bin/herdr-obsidian
python3 bin/herdr-obsidian install-skill --refresh || true
python3 bin/herdr-obsidian install-app-mod || true

echo "herdr-obsidian installed. Checking this machine:"
python3 bin/herdr-obsidian doctor --brief || true
