#!/usr/bin/env bash
# Build the plugin and either package it as a zip or push it to a device.
#
#   ./deploy.sh zip                 -> out/XboxWireless.zip (install via Decky > Developer > Install from ZIP)
#   ./deploy.sh deck@steammachine   -> rsync to ~/homebrew/plugins/XboxWireless
set -euo pipefail

cd "$(dirname "$0")"
NAME=XboxWireless
FILES=(plugin.json package.json main.py py_modules dist LICENSE README.md)

pnpm run build

stage=$(mktemp -d)
trap 'rm -rf "$stage"' EXIT
mkdir -p "$stage/$NAME"
cp -R "${FILES[@]}" "$stage/$NAME/"
rm -f "$stage/$NAME"/dist/*.map
find "$stage" -name __pycache__ -prune -exec rm -rf {} +

if [[ "${1:-}" == "zip" ]]; then
  mkdir -p out
  rm -f "out/$NAME.zip"
  (cd "$stage" && zip -qr "$OLDPWD/out/$NAME.zip" "$NAME")
  echo "out/$NAME.zip"
elif [[ -n "${1:-}" ]]; then
  host=$1
  rsync -az --delete "$stage/$NAME/" "$host:/tmp/$NAME/"
  ssh "$host" 'start=/tmp/steamos-short-session-start
    if [ -f "$start" ]; then
      age=$(( $(date +%s) - $(date +%s -r "$start") ))
      if [ "$age" -lt 65 ]; then echo "waiting $((65 - age))s before restarting Steam"; sleep $((65 - age)); fi
    fi
    systemctl --user restart steam-launcher.service && echo "Steam restarted"
    for _ in $(seq 60); do curl -s localhost:8080/json | grep -q SharedJSContext && break; sleep 1; done'
  # plugins dir is root-owned; -t so sudo can prompt for a password
  ssh -t "$host" "sudo rsync -a --delete /tmp/$NAME/ ~/homebrew/plugins/$NAME/ && rm -rf /tmp/$NAME && sudo systemctl restart plugin_loader"
else
  echo "usage: $0 zip | <user@host>" >&2
  exit 1
fi
