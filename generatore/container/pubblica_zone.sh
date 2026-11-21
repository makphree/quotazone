#!/bin/bash
# QuotaZone · pubblica app + ultimo file zone sul ramo gh-pages (un solo commit, sostituito ogni volta:
# la cronologia non cresce). Uso: pubblica_zone.sh /percorso/qz_zone_AAAAMMGG_HHMM.json.gz
set -euo pipefail
FILE="$1"
REPO_DIR="${QZ_REPO_DIR:-/opt/quotazone}"
STATE="${QZ_STATE_DIR:-/var/lib/quotazone}"
URL="${QZ_REPO_SSH:-git@github.com:makphree/quotazone.git}"
export GIT_SSH_COMMAND="ssh -i $STATE/.ssh/quotazone_deploy -o IdentitiesOnly=yes -o UserKnownHostsFile=$STATE/.ssh/known_hosts"
W=$(mktemp -d); trap 'rm -rf "$W"' EXIT

# sito = file dell'app dal ramo main (senza generatore/ e senza data/) + zone nuove
git -C "$REPO_DIR" archive HEAD | tar -x -C "$W"
rm -rf "$W/generatore" "$W/data"; mkdir -p "$W/data"
NAME=$(basename "$FILE")
cp "$FILE" "$W/data/zones.json.gz"
SHA=$(sha256sum "$FILE" | cut -c1-64)
STAMP=$(echo "$NAME" | sed -E 's/^qz_zone_([0-9]{4})([0-9]{2})([0-9]{2})_([0-9]{2})([0-9]{2}).*/\1-\2-\3T\4:\5:00/')
DATE=$(date -d "$STAMP" -Iseconds 2>/dev/null || date -Iseconds)
printf '{"file":"%s","dataDate":"%s","sha256":"%s","fonte":"QuotaZone, zone ricostruite da fonti libere"}\n' "$NAME" "$DATE" "$SHA" > "$W/data/zone.json"
touch "$W/.nojekyll"

cd "$W"
git init -q -b gh-pages
git -c user.name="QuotaZone container" -c user.email="quotazone@localhost" add -A
git -c user.name="QuotaZone container" -c user.email="quotazone@localhost" commit -q -m "Zone $NAME"
git push -q -f "$URL" gh-pages
echo "pubblicato $NAME su gh-pages"
