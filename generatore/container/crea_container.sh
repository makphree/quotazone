#!/bin/bash
# QuotaZone · crea il container LXC su Proxmox (da lanciare nella Shell del NODO Proxmox, come root):
#
#   bash <(curl -fsSL https://raw.githubusercontent.com/makphree/quotazone/main/generatore/container/crea_container.sh)
#
# Valori modificabili davanti al comando, es.:  CTID=150 STORAGE=local-zfs bash <(curl …)
#   CTID     numero del container        (default: il primo libero)
#   STORAGE  dove mettere il disco        (default: local-lvm, se no il primo che accetta container)
#   BRIDGE   rete                         (default: vmbr0, indirizzo via DHCP)
#   CT_HOSTNAME                           (default: quotazone)
set -euo pipefail
B() { printf '\n\033[1m%s\033[0m\n' "$*"; }
die() { printf '\n\033[31mERRORE: %s\033[0m\n' "$*"; exit 1; }
[ "$(id -u)" -eq 0 ] || die "esegui come root sul nodo Proxmox"
command -v pct >/dev/null || die "pct non trovato: questo script va lanciato sul nodo Proxmox, non dentro un container"

REPO=${REPO:-https://github.com/makphree/quotazone.git}
CTID=${CTID:-$(pvesh get /cluster/nextid)}
BRIDGE=${BRIDGE:-vmbr0}
CT_HOSTNAME=${CT_HOSTNAME:-quotazone}
if [ -z "${STORAGE:-}" ]; then
  if pvesm status -content rootdir 2>/dev/null | awk 'NR>1{print $1}' | grep -qx local-lvm; then STORAGE=local-lvm
  else STORAGE=$(pvesm status -content rootdir | awk 'NR>1 && $3=="active"{print $1; exit}'); fi
fi
[ -n "$STORAGE" ] || die "nessuno storage per container trovato: indica STORAGE=nome"
TSTORE=${TSTORE:-$(pvesm status -content vztmpl | awk 'NR>1 && $3=="active"{print $1; exit}')}
[ -n "$TSTORE" ] || die "nessuno storage per i template (vztmpl): abilitalo su 'local' in Datacenter → Storage"
pct status "$CTID" >/dev/null 2>&1 && die "il container $CTID esiste già: scegli un altro CTID"

B "1/5  Template Debian 12"
pveam update >/dev/null
TMPL=$(pveam available --section system | awk '{print $2}' | grep -E '^debian-12-standard_.*_amd64\.tar\.zst$' | sort -V | tail -1)
[ -n "$TMPL" ] || die "template Debian 12 non trovato"
pveam list "$TSTORE" | grep -q "$TMPL" || pveam download "$TSTORE" "$TMPL"

B "2/5  Container $CTID ($CT_HOSTNAME) su $STORAGE, rete $BRIDGE"
pct create "$CTID" "$TSTORE:vztmpl/$TMPL" \
  --hostname "$CT_HOSTNAME" --cores 1 --memory 1536 --swap 512 \
  --rootfs "$STORAGE:8" --net0 "name=eth0,bridge=$BRIDGE,ip=dhcp" \
  --unprivileged 1 --features nesting=1 --onboot 1 --ostype debian \
  --description "QuotaZone: zone UAS ricostruite 2 volte al giorno"
pct start "$CTID"

B "3/5  Attendo la rete"
for i in $(seq 1 30); do
  pct exec "$CTID" -- bash -c 'getent hosts github.com >/dev/null' 2>/dev/null && break
  sleep 2; [ "$i" -eq 30 ] && die "il container non raggiunge Internet (DHCP su $BRIDGE?)"
done

B "4/5  Pacchetti e codice"
pct exec "$CTID" -- bash -c "
  set -e
  export DEBIAN_FRONTEND=noninteractive
  ln -sf /usr/share/zoneinfo/Europe/Rome /etc/localtime; echo Europe/Rome > /etc/timezone
  apt-get update -qq && apt-get install -y -qq git curl ca-certificates openssh-client python3 python3-venv gzip >/dev/null
  git clone -q '$REPO' /opt/quotazone
"

B "5/5  Installazione del ciclo zone"
pct exec "$CTID" -- bash /opt/quotazone/generatore/container/installa_zone.sh

IP=$(pct exec "$CTID" -- hostname -I 2>/dev/null | awk '{print $1}')
cat <<FINE

$(printf '\033[1;32m')Container $CTID pronto$(printf '\033[0m') (IP $IP). Prossimi passi:

  1. Entra nel container:            pct enter $CTID
  2. Primo giro di prova (10-20 min): systemctl start quotazone-zone.service; journalctl -u quotazone-zone -f
  3. Per la pubblicazione automatica sulla repo segui le istruzioni stampate sopra (deploy key).
FINE
