#!/bin/bash
# QuotaZone · installa il ciclo "zone proprie" dentro il container (come root).
# Lo lancia crea_container.sh; si può rilanciare senza perdere configurazione e chiave.
set -eu
[ "$(id -u)" -eq 0 ] || { echo "Esegui come root."; exit 1; }
REPO_DIR=/opt/quotazone
CODE=$REPO_DIR/generatore
STATE=/var/lib/quotazone
CONF=/etc/quotazone/config.env
[ -f "$CODE/genera_zone.py" ] || { echo "Manca $CODE: clona prima la repo in $REPO_DIR"; exit 1; }

export DEBIAN_FRONTEND=noninteractive
apt-get install -y -qq git curl ca-certificates openssh-client python3 python3-venv gzip >/dev/null
id quotazone >/dev/null 2>&1 || useradd --system --home-dir "$STATE" --create-home --shell /usr/sbin/nologin quotazone
mkdir -p "$STATE/zone-proprie/fonti" "$STATE/.ssh" "$(dirname "$CONF")"
chown -R quotazone:quotazone "$STATE" "$REPO_DIR"; chmod 700 "$STATE/.ssh"
runuser -u quotazone -- git -C "$REPO_DIR" config core.fileMode false
runuser -u quotazone -- git config --global --add safe.directory "$REPO_DIR" || true

echo "· Python + shapely"
[ -x "$STATE/venv/bin/python" ] || runuser -u quotazone -- python3 -m venv "$STATE/venv"
runuser -u quotazone -- "$STATE/venv/bin/pip" install -q --upgrade pip shapely

echo "· Configurazione"
[ -f "$CONF" ] || cp "$CODE/container/config.env.esempio" "$CONF"
chown root:quotazone "$CONF"; chmod 640 "$CONF"

echo "· Chiave per pubblicare sulla repo"
KEY="$STATE/.ssh/quotazone_deploy"
[ -f "$KEY" ] || runuser -u quotazone -- ssh-keygen -q -t ed25519 -N '' -C "quotazone-container" -f "$KEY"
runuser -u quotazone -- bash -c "ssh-keyscan -t ed25519 github.com > '$STATE/.ssh/known_hosts' 2>/dev/null"

echo "· Servizio e timer (06:45 e 18:45)"
chmod +x "$CODE"/container/*.sh
install -m 644 "$CODE/container/quotazone-zone.service" "$CODE/container/quotazone-zone.timer" /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now quotazone-zone.timer >/dev/null

cat <<FINE

Installato. Prossimi avvii:
$(systemctl list-timers quotazone-zone.timer --no-legend | sed 's/^/  /')

PUBBLICAZIONE AUTOMATICA (facoltativa ma è lo scopo):
  a) GitHub → makphree/quotazone → Settings → Deploy keys → Add deploy key
     Title: container-quotazone · spunta "Allow write access" · Key:

     $(cat "$KEY.pub")

  b) nano $CONF   →   QZ_PUBBLICA=1
     (facoltativi: NTFY_URL per gli avvisi sul telefono, OPENAIP_API_KEY)
FINE
