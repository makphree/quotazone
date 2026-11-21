#!/bin/bash
# QuotaZone · ciclo "zone proprie" (2 volte al giorno, timer quotazone-zone.timer):
#   1. scarica le fonti indipendenti (OurAirports, openAIP, OpenStreetMap, NOTAM)
#   2. ricostruisce il file ED-269 tuo
#   3. se c'è un file D-Flight scaricato col tuo account, lo confronta (solo statistica, uso personale)
#   4. ti avvisa con ntfy: riepilogo, e priorità alta se l'errore "critico" supera la soglia
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
CODE="$(dirname "$HERE")"                                  # cartella zone-proprie
STATE="${QZ_STATE_DIR:-/var/lib/quotazone}"
Z="$STATE/zone-proprie"; FONTI="$Z/fonti"; OUT="$Z/uscita"; RAP="$Z/rapporti"
PY="${QZ_PYTHON:-$STATE/venv/bin/python}"
SOGLIA="${QZ_SOGLIA_CRITICO:-3}"                           # % di territorio "critico" oltre cui allarmare
TIENI="${QZ_KEEP_ZONE:-14}"                                # file ricostruiti da conservare
mkdir -p "$FONTI" "$OUT" "$RAP"
LOG="$Z/zone.log"
log()    { echo "$(date '+%Y-%m-%d %H:%M:%S')  $*" | tee -a "$LOG"; }
notify() { [ -n "${NTFY_URL:-}" ] && curl -fsS -m 20 -H "Title: QuotaZone zone proprie" -H "Priority: ${2:-3}" -d "$1" "$NTFY_URL" >/dev/null 2>&1; return 0; }

# fonti di base (confine Italia) incluse nel codice: copiate se mancano
[ -f "$FONTI/italia.geojson" ] || cp "$CODE/fonti/italia.geojson" "$FONTI/"

log "— inizio ciclo"
# codice aggiornato dalla repo (pubblica, nessuna credenziale)
git -C /opt/quotazone pull -q --ff-only 2>>"$LOG" || log "Avviso: git pull non riuscito, uso il codice locale"
if [ "${QZ_SENZA_DOWNLOAD:-0}" != "1" ]; then
  "$PY" "$CODE/scarica_fonti.py" "$FONTI" 2>&1 | tee -a "$LOG"
fi
errori_fonti=$("$PY" -c "import json;e=json.load(open('$FONTI/ultimo_scarico.json'))['esito'];print('; '.join(k+': '+v for k,v in e.items() if v.startswith('ERRORE')))" 2>/dev/null)

# senza queste fonti il file sarebbe meno prudente del dovuto: meglio non generarlo
for f in airports.csv runways.csv it_asp.geojson it_apt.geojson osm_aerodromi_elisuperfici_IT.tsv; do
  if [ ! -s "$FONTI/$f" ]; then
    log "manca la fonte $f: file non generato"
    notify "Manca la fonte $f, file zone NON generato. Per openAIP metti OPENAIP_API_KEY in /etc/quotazone/config.env. Dettagli: $LOG" 5
    exit 1
  fi
done

STAMP=$(date +%Y%m%d_%H%M)
NEW="$OUT/qz_zone_${STAMP}.json"
if ! (cd "$CODE" && "$PY" genera_zone.py "$FONTI" "$NEW") 2>&1 | tee -a "$LOG" | tail -1 | grep -q 'totale zone'; then
  notify "Generazione del file NON riuscita. Resta valido l'ultimo file. Dettagli: $LOG" 5; exit 1
fi
NZ=$("$PY" -c "import json;print(len(json.load(open('$NEW'))['features']))")
if [ "$NZ" -lt 3000 ]; then
  notify "File generato sospetto: solo $NZ zone. Non lo uso. Dettagli: $LOG" 5; mv "$NEW" "$NEW.scartato"; exit 1
fi
gzip -kf "$NEW"
ln -sf "$(basename "$NEW")" "$OUT/qz_zone_ultimo.json"; ln -sf "$(basename "$NEW").gz" "$OUT/qz_zone_ultimo.json.gz"
ls -1t "$OUT"/qz_zone_2*.json 2>/dev/null | tail -n +$((TIENI+1)) | while read f; do rm -f "$f" "$f.gz"; done
log "file ricostruito: $NEW ($NZ zone)"

# confronto col file D-Flight più recente (se il servizio quotazone-aggiorna lo scarica nel container)
REF=$(ls -1t "$STATE"/download/dflight_geozones_*.json* 2>/dev/null | head -1)
if [ -n "$REF" ]; then
  "$PY" "$CODE/verifica.py" "$NEW" "$REF" --passo "${QZ_PASSO_M:-1000}" --confine "$FONTI/italia.geojson" --uscita "$RAP/rapporto_$STAMP" 2>&1 | tee -a "$LOG"
  ln -sf "rapporto_$STAMP.html" "$RAP/rapporto_ultimo.html"
  RIASS=$("$PY" - "$RAP/rapporto_$STAMP.json" "$SOGLIA" <<'PYEOF'
import json, sys
r = json.load(open(sys.argv[1])); s = float(sys.argv[2])
crit = next((v['pct'] for k, v in r['gravita'].items() if k.startswith('critico')), 0)
print(('ALLARME ' if crit > s else '') + f"uguale {r['uguale_pct']}% · più prudente {r['piu_prudente_pct']}% · meno prudente {r['meno_prudente_pct']}% · critico {crit}%")
PYEOF
)
  PRIO=3; case "$RIASS" in ALLARME*) PRIO=5;; esac
  MSG="$NZ zone ricostruite. Confronto con D-Flight: $RIASS"
else
  PRIO=3; MSG="$NZ zone ricostruite (nessun file D-Flight per il confronto)."
fi
[ -n "$errori_fonti" ] && { MSG="$MSG
Fonti non aggiornate: $errori_fonti"; [ $PRIO -lt 4 ] && PRIO=4; }
log "$MSG"
if [ $PRIO -ge 4 ] || [ "${NOTIFY_OK:-0}" = "1" ]; then notify "$MSG" $PRIO; fi

# pubblicazione sul sito (ramo gh-pages), se attivata e se la deploy key è stata aggiunta su GitHub
if [ "${QZ_PUBBLICA:-0}" = "1" ]; then
  if bash "$HERE/pubblica_zone.sh" "$NEW.gz" 2>&1 | tee -a "$LOG" | grep -q pubblicato; then log "pubblicato sul sito"
  else notify "Pubblicazione sul sito NON riuscita (deploy key?). Dettagli: $LOG" 4; fi
fi
# copia facoltativa in un'altra cartella
if [ -n "${QZ_ZONE_COPIA_IN:-}" ]; then cp "$NEW.gz" "$QZ_ZONE_COPIA_IN/qz_zone_${STAMP}.json.gz" && log "copiato in $QZ_ZONE_COPIA_IN"; fi
log "— fine ciclo"
