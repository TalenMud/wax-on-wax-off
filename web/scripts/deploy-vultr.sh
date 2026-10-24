#!/usr/bin/env bash
# Build the phone app against the prod Convex backend and upload it to the Vultr box,
# where Caddy serves /var/www/waxon at https://waxonwaxoff.ink.
#   web/scripts/deploy-vultr.sh            (needs SSH key access to root@$HOST)
set -euo pipefail
HOST="${HOST:-155.138.216.43}"
cd "$(dirname "$0")/.."
[ -d node_modules ] || npm ci --no-audit --no-fund
VITE_CONVEX_URL="${VITE_CONVEX_URL:-https://abundant-roadrunner-265.convex.cloud}" npm run build
rsync -az --delete dist/ "root@$HOST:/var/www/waxon/"
echo "deployed: https://waxonwaxoff.ink"
