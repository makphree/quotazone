# QuotaZone

Mappa personale delle zone geografiche UAS sulla posizione del telefono, con meteo per il volo. App: https://makphree.github.io/quotazone/ (installabile dal browser del telefono).

## Le zone

Il file in `data/` (`qz_zone_AAAAMMGG_hhmm.json.gz`, formato ED-269) è una **ricostruzione da fonti libere**, non il file D-Flight:

- regole ENAC Circolare ATM-09A per aeroporti, aviosuperfici, eliporti ed elisuperfici, CTR/ATZ;
- posizioni da OurAirports (pubblico dominio) e © OpenStreetMap contributors (ODbL);
- spazi aerei, aree P/R/D, aree ULM e parchi da openAIP (CC BY-NC 4.0, uso non commerciale);
- NOTAM tramite FAA NOTAM Search.

In un confronto su tutta l'Italia coincide con D-Flight nel 71% dei punti, è più prudente nel 24% e meno prudente nel 5%. **Non è ufficiale: prima di ogni volo verifica su D-Flight.**

Per aggiornare: carica in `data/` un nuovo `qz_zone_….json.gz` (Add file → Upload files) e cancella il vecchio. L'app prende il file con la data più recente nel nome. Il file D-Flight scaricato col tuo account non va messo qui: si importa a mano sul telefono (scheda Dati) e resta solo lì.

## Meteo

Per la posizione GPS o il punto toccato: giudizio di volo, vento e raffiche anche a 120 m, temperatura, pioggia, visibilità, pressione con tendenza sulle 3 ore, indice Kp, alba e tramonto, prossime 12 ore. La banda in alto è divisa: 2/3 stato di volo, 1/3 meteo (verde, giallo, arancio, rosso). Fonti: Open-Meteo e NOAA SWPC.

## Senza rete

App, zone e ultimo meteo restano sul telefono; della mappa sono disponibili le parti già viste.

## Licenze

Codice: MIT. Mappa © OpenStreetMap contributors · Leaflet 1.9.4 (BSD-2) · Turf 6.5.0 (MIT). Il file delle zone deriva da dati ODbL e CC BY-NC: uso personale, non commerciale, con queste attribuzioni.
