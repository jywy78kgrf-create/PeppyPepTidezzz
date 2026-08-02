#!/usr/bin/env bash
# Export the paper-trading state (the append-only ledger + the live book) to a
# single file, atlas-state.tgz, so it can be carried to another machine WITHOUT
# losing your trade history.
#
# Run this ON THE MAC, from the optionsdesk/ folder where the desk runs now:
#
#   cd ~/peppypeptidezzz/optionsdesk
#   bash deploy/backup-state.sh
#
# It writes ./atlas-state.tgz. Copy that to the server (the walkthrough shows how).
set -euo pipefail

# Find this project's state volume (named "<project>_paperstate").
VOL="$(docker volume ls --format '{{.Name}}' | grep -E 'paperstate$' | head -1)"
if [ -z "${VOL:-}" ]; then
  echo "!! No 'paperstate' Docker volume found."
  echo "   Is the desk running from this folder?  Check:  docker compose ps"
  exit 1
fi

echo "Exporting state volume: $VOL"
docker run --rm -v "$VOL":/v -v "$PWD":/backup alpine \
  tar czf /backup/atlas-state.tgz -C /v .

echo
echo "Wrote  $(pwd)/atlas-state.tgz   ($(du -h atlas-state.tgz | cut -f1))"
echo "This contains your ledger (every closed trade) and the current open book."
echo "Next: copy it to the server, then run deploy/restore-state.sh there."
