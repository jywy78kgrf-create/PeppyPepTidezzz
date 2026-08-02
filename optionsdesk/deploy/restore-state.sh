#!/usr/bin/env bash
# Restore atlas-state.tgz into this project's paper-trading volume, so the desk
# continues the SAME account (same ledger, same realized P&L) on this machine.
#
# Run this ON THE SERVER, from the optionsdesk/ folder, with the stack stopped:
#
#   cd ~/optionsdesk
#   docker compose down          # make sure nothing is using the volume
#   bash deploy/restore-state.sh # expects ./atlas-state.tgz next to it
#   docker compose up -d --build
#
# WARNING: this REPLACES any existing state in this project's volume with the
# contents of the tarball. That's what you want for a migration; don't run it
# on a desk whose local history you want to keep.
set -euo pipefail

TARBALL="${1:-atlas-state.tgz}"
if [ ! -f "$TARBALL" ]; then
  echo "!! Missing $TARBALL — copy it into this folder first."
  exit 1
fi

# Volume name = "<compose project>_paperstate"; the project defaults to the
# folder name, so keep this folder named "optionsdesk" on both machines.
PROJ="$(basename "$PWD")"
VOL="${PROJ}_paperstate"
docker volume create "$VOL" >/dev/null

echo "Restoring $TARBALL into volume $VOL ..."
docker run --rm -v "$VOL":/v -v "$PWD":/backup alpine sh -c \
  'rm -rf /v/* /v/..?* /v/.[!.]* 2>/dev/null || true; tar xzf /backup/'"$TARBALL"' -C /v'

echo
echo "State restored. Now bring the desk up:"
echo "  docker compose up -d --build"
