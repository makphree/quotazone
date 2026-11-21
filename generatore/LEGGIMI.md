# QuotaZone · zone UAS ricostruite da fonti indipendenti

File di zone geografiche in formato ED-269 (lo stesso di D-Flight, importabile in QuotaZone) costruito **senza dati D-Flight**: solo fonti libere e regole pubbliche ENAC. Il file D-Flight scaricato col tuo account serve solo a **misurare** quanto la ricostruzione ci assomiglia; nulla viene copiato.

## Strati e fonti

| Strato | Fonte | Regola | Licenza |
|---|---|---|---|
| Aeroporti, aviosuperfici, eliporti, elisuperfici | OurAirports, OpenStreetMap, openAIP | ENAC ATM-09A par. 6.8–6.11 | Pubblico dominio · ODbL · CC BY-NC 4.0 |
| Fascia 60 m in CTR / ATZ / MATZ | openAIP | ATM-09A | CC BY-NC 4.0 |
| Aree P / R / D dell'AIP (base sotto 120 m AGL o 600 m AMSL) | openAIP | ATM-09A par. 5.3 | CC BY-NC 4.0 |
| Aree ULM / acrobazia / attività sportive fino a terra | openAIP | AIP ENR 5.5 | CC BY-NC 4.0 |
| Parchi con limite di sorvolo | openAIP + OpenStreetMap | L. 394/1991 art. 11 (parchi nazionali) | CC BY-NC · ODbL |
| Carceri (+500 m) e aree militari (+150 m) | OpenStreetMap | — | ODbL |
| NOTAM temporanei sotto 120 m (aree, UAS, paracadutisti, esercitazioni) | FAA NOTAM Search | — | dati pubblici |

CC BY-NC (openAIP) e Open-Meteo vietano l'uso commerciale: va bene per l'uso personale che hai scelto.

## Quanto coincide con D-Flight (10/10/2026, griglia 1 km su tutta l'Italia, 301.343 punti)

| Versione | Uguale | Più prudente | **Meno prudente** | di cui critico* |
|---|---|---|---|---|
| Solo aerodromi (fase 2) | 51,3% | 29,0% | 19,7% | 10,5% |
| Tutti gli strati, prima della taratura | 17,8% | 82,2% | 0,0% | 0 |
| **Tarato (file attuale)** | **71,4%** | **23,8%** | **4,9%** | **1,7%** |

\* critico = D-Flight dice 0 m, il file ricostruito permette 45 m o più.

Il "più prudente" del 82% era dovuto a due NOTAM militari sugli ostacoli con raggio 999 NM, cioè tutta l'Italia: ora i NOTAM-ostacolo sono esclusi e i cerchi generici più grandi di 25 NM ignorati. Le altre correzioni della taratura sono state la classificazione IFR (i tipi openAIP 0/2/9 classificavano come strumentali campi come Legnago, Asiago e Thiene), i cerchi 1,5/2,5/3,5 km per le aviosuperfici senza pista nota (come fa D-Flight) e l'aggiunta delle aree ULM.

**Cosa resta scoperto (4,9%)**: avio/elisuperfici che le fonti libere non conoscono o di cui manca la direzione della pista (2,4%), NFZ regionali nei parchi alpini (1,1%), CTR/ATZ con confini diversi da openAIP (0,4%, soprattutto Albenga), NOTAM (0,4%). Il download completo dei parchi e delle piste da OpenStreetMap, fatto dal ciclo automatico, ne riduce una parte.

**Dove è più prudente (23,8%)**: elisuperfici OSM in montagna che non sono zone ufficiali (10%), aerodromi (8%), aree D militari (Basilicata, Chianti) che D-Flight non riporta (3,5%). Con `QZ_HELI=nominate` (griglia 2 km) l'uguale sale al 77% ma il meno prudente al 6,4%: per sicurezza resta `tutte`.

Il rapporto completo, con le zone peggiori e i link alla mappa, è in `rapporto/rapporto.html`.

## Ciclo automatico due volte al giorno (container Proxmox)

Alle **06:45** e alle **18:45** (timer `quotazone-zone.timer`):

1. `scarica_fonti.py` aggiorna le fonti: NOTAM sempre; openAIP ogni giorno; aerodromi OSM ogni 3 giorni; OurAirports, sicurezza OSM ogni settimana; parchi e piste OSM ogni 2 settimane. Ogni file è controllato prima di sostituire il vecchio: se un download fallisce resta l'ultima copia buona.
2. `genera_zone.py` crea `qz_zone_AAAAMMGG_HHMM.json(.gz)` e il link `qz_zone_ultimo.json.gz` (ne tiene 14).
3. Se nel container c'è un file D-Flight (`/var/lib/quotazone/download/`, quello scaricato dal ciclo D-Flight delle 06:30), `verifica.py` fa il confronto e aggiunge una riga a `storico.csv`.
4. Avviso **ntfy**: urgente se il "critico" supera la soglia (3% di default) o il file è anomalo; normale se una fonte non si aggiorna; riepilogo a ogni ciclo con `NOTIFY_OK=1`.

### Installazione nel container

```bash
# copia questa cartella nel container in /opt/quotazone/zone-proprie, poi come root:
bash /opt/quotazone/zone-proprie/container/installa_zone.sh
nano /etc/quotazone/config.env         # NTFY_URL e, consigliata, OPENAIP_API_KEY (gratuita)
systemctl start quotazone-zone.service; journalctl -u quotazone-zone -f
```

Funziona nello stesso container del ciclo D-Flight (usa lo stesso utente, venv e config) oppure da solo; senza D-Flight genera il file ma non fa il confronto.

| Cosa | Dove |
|---|---|
| File ricostruito | `/var/lib/quotazone/zone-proprie/uscita/qz_zone_ultimo.json.gz` |
| Ultimo rapporto | `/var/lib/quotazone/zone-proprie/rapporti/rapporto_ultimo.html` |
| Andamento nel tempo | `/var/lib/quotazone/zone-proprie/rapporti/storico.csv` |
| Registro | `/var/lib/quotazone/zone-proprie/zone.log` |
| Esito ultimo download fonti | `/var/lib/quotazone/zone-proprie/fonti/ultimo_scarico.json` |

## Uso a mano

```bash
python3 scarica_fonti.py fonti                     # o solo alcune: … fonti notam openaip
python3 genera_zone.py fonti zone_proprie_ed269.json && gzip -k zone_proprie_ed269.json
python3 verifica.py zone_proprie_ed269.json dflight_geozones_….json.gz --passo 1000
QZ_STRATI=aerodromi,spazi python3 genera_zone.py …  # solo alcuni strati (aerodromi,spazi,sicurezza,parchi,notam)
```

Regolazioni: `QZ_HELI` (tutte|nominate), `QZ_CARCERI_M` (500), `QZ_MILITARI_M` (150), `QZ_AREE_D` (1 = aree D incluse), `QZ_ASP_AMSL_MAX` (600).

## Avvertenze

- **Non ufficiale:** ricostruzione personale. Prima di ogni volo la verifica ufficiale resta D-Flight, come chiede l'ENAC.
- **Orari ignorati:** zone di aerodromi e aree R sono trattate come sempre attive (più prudente).
- **openAIP** è curato da volontari: confini CTR/ATZ possono essere vecchi (es. Albenga).
- **Regole in revisione:** l'ENAC ha in consultazione un nuovo regolamento "Zone geografiche UAS"; le geometrie potrebbero cambiare.
