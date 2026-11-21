#!/usr/bin/env python3
"""QuotaZone · scarica le fonti indipendenti per ricostruire le zone UAS.

Ogni fonte viene scaricata in un file temporaneo, controllata e solo allora sostituisce la copia precedente:
se un download fallisce resta valida l'ultima versione buona (e lo si segnala nel riepilogo).

  python3 scarica_fonti.py fonti            # tutte le fonti
  python3 scarica_fonti.py fonti notam      # solo alcune: ourairports openaip osm_aerodromi osm_sicurezza osm_parchi osm_piste notam

Variabili d'ambiente (facoltative):
  OPENAIP_API_KEY   chiave gratuita openAIP (consigliata: https://www.openaip.net → profilo → API clients)
  OPENAIP_ASP_URL   in alternativa: link diretto all'export it_asp.geojson
  OPENAIP_APT_URL   in alternativa: link diretto all'export it_apt.geojson
  OVERPASS_URL      server Overpass (default https://overpass-api.de/api/interpreter)
"""
import json, os, sys, time, urllib.parse, urllib.request

UA = 'QuotaZone/1.0 (uso personale; zone droni)'
OVERPASS = os.environ.get('OVERPASS_URL', 'https://overpass-api.de/api/interpreter')
AREA_IT = 'area["ISO3166-1"="IT"][admin_level=2]->.it;'


def get(url, data=None, headers=None, timeout=300):
    h = {'User-Agent': UA}; h.update(headers or {})
    req = urllib.request.Request(url, data=data, headers=h)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def retry(fn, tries=4, wait=60):
    for i in range(tries):
        try:
            return fn()
        except Exception as e:
            if i == tries - 1: raise
            print(f'   tentativo {i + 1} fallito ({e}); riprovo tra {wait * (i + 1)} s', flush=True)
            time.sleep(wait * (i + 1))


def save(path, data, check):
    tmp = path + '.nuovo'
    open(tmp, 'wb').write(data)
    msg = check(tmp)                    # solleva eccezione se il file non va bene; ritorna una descrizione
    os.replace(tmp, path)
    return msg


def overpass(query):
    return retry(lambda: get(OVERPASS, urllib.parse.urlencode({'data': query}).encode(), timeout=900), tries=4, wait=90)


def n_elements(min_n):
    def chk(p):
        n = len(json.load(open(p))['elements'])
        if n < min_n: raise ValueError(f'solo {n} elementi (attesi almeno {min_n})')
        return f'{n} elementi'
    return chk


def n_features(min_n):
    def chk(p):
        n = len(json.load(open(p))['features'])
        if n < min_n: raise ValueError(f'solo {n} oggetti (attesi almeno {min_n})')
        return f'{n} oggetti'
    return chk


# ------------------------------------------------------------------ fonti

def ourairports(src):
    out = []
    for f, min_lines in (('airports.csv', 50000), ('runways.csv', 30000)):
        def dl(f=f):
            for base in ('https://davidmegginson.github.io/ourairports-data/', 'https://raw.githubusercontent.com/davidmegginson/ourairports-data/main/'):
                try: return get(base + f)
                except Exception as e: err = e
            raise err
        data = retry(dl)
        def chk(p, m=min_lines):
            n = sum(1 for _ in open(p, encoding='utf-8'))
            if n < m: raise ValueError(f'{n} righe')
            return f'{f} {n} righe'
        out.append(save(os.path.join(src, f), data, chk))
    return ', '.join(out)


def openaip(src):
    key = os.environ.get('OPENAIP_API_KEY', '').strip()
    out = []
    for kind, fname, min_n in (('airspaces', 'it_asp.geojson', 800), ('airports', 'it_apt.geojson', 300)):
        if key:
            items, page = [], 1
            while True:
                url = f'https://api.core.openaip.net/api/{kind}?country=IT&limit=1000&page={page}'
                j = json.loads(retry(lambda: get(url, headers={'x-openaip-api-key': key, 'Accept': 'application/json'})))
                items += j.get('items') or []
                if page >= (j.get('totalPages') or 1): break
                page += 1
            fc = {'type': 'FeatureCollection', 'features': [
                {'type': 'Feature', 'geometry': it.get('geometry'), 'properties': {k: v for k, v in it.items() if k != 'geometry'}} for it in items]}
            data = json.dumps(fc).encode()
        else:
            url = os.environ.get('OPENAIP_ASP_URL' if kind == 'airspaces' else 'OPENAIP_APT_URL') or \
                  f'https://storage.googleapis.com/29f98e10-a489-4c82-ae5e-489dbcd4912f/{fname}'
            data = retry(lambda: get(url))
        out.append(fname + ' ' + save(os.path.join(src, fname), data, n_features(min_n)))
    return ', '.join(out)


def osm_aerodromi(src):
    q = f'[out:json][timeout:600];{AREA_IT}nwr["aeroway"~"^(aerodrome|airstrip|helipad|heliport)$"](area.it);out center tags;'
    j = json.loads(overpass(q))
    cols = ['id', 'lat', 'lon', 'aeroway', 'name', 'icao', 'emergency', 'heliport', 'operator', 'disused', 'access', 'surface', 'aerodrome_type', 'military_landuse']
    rows = ['\t'.join(cols)]
    for e in j['elements']:
        t = e.get('tags') or {}
        c = e.get('center') or e
        if 'lat' not in c: continue
        disused = '1' if any(k.startswith(('disused', 'abandoned')) for k in t) else ''
        vals = [e['type'][0] + str(e['id']), f"{c['lat']:.6f}", f"{c['lon']:.6f}", t.get('aeroway', ''), t.get('name', ''), t.get('icao', ''),
                t.get('emergency', ''), t.get('heliport', ''), t.get('operator', ''), disused, t.get('access', ''), t.get('surface', ''),
                t.get('aerodrome:type', ''), t.get('landuse', '') if t.get('landuse') == 'military' else '']
        rows.append('\t'.join(v.replace('\t', ' ').replace('\n', ' ') for v in vals))
    def chk(p):
        n = sum(1 for _ in open(p, encoding='utf-8')) - 1
        if n < 1000: raise ValueError(f'{n} righe')
        return f'{n} punti'
    return save(os.path.join(src, 'osm_aerodromi_elisuperfici_IT.tsv'), ('\n'.join(rows) + '\n').encode(), chk)


def osm_sicurezza(src):
    q = (f'[out:json][timeout:600];{AREA_IT}(nwr["amenity"="prison"](area.it);way["landuse"="military"](area.it);'
         f'relation["landuse"="military"](area.it);way["military"](area.it);relation["military"](area.it););out geom;')
    return save(os.path.join(src, 'osm_sicurezza_IT.json'), overpass(q), n_elements(1000))


def osm_parchi(src):
    q = (f'[out:json][timeout:900];{AREA_IT}('
         f'relation["boundary"="national_park"](area.it);way["boundary"="national_park"](area.it);'
         f'relation["boundary"="protected_area"]["protect_class"~"^(2|5)$"](area.it);way["boundary"="protected_area"]["protect_class"~"^(2|5)$"](area.it);'
         f'relation["boundary"="protected_area"]["protection_title"~"[Pp]arco"](area.it);way["boundary"="protected_area"]["protection_title"~"[Pp]arco"](area.it);'
         f');out geom;')
    return save(os.path.join(src, 'osm_aree_protette_IT.json'), overpass(q), n_elements(50))


def osm_piste(src):
    q = f'[out:json][timeout:600];{AREA_IT}way["aeroway"="runway"](area.it);out geom;'
    return save(os.path.join(src, 'osm_piste_IT.json'), overpass(q), n_elements(200))


def notam(src):
    import notam as nt
    tmp = os.path.join(src, 'notam_IT.json.nuovo')
    retry(lambda: nt.scarica(tmp), tries=3, wait=120)
    n = len(json.load(open(tmp))['notam'])
    if n < 100: raise ValueError(f'solo {n} NOTAM')
    os.replace(tmp, os.path.join(src, 'notam_IT.json'))
    return f'{n} NOTAM'


FONTI = {'ourairports': ourairports, 'openaip': openaip, 'osm_aerodromi': osm_aerodromi, 'osm_sicurezza': osm_sicurezza,
         'osm_parchi': osm_parchi, 'osm_piste': osm_piste, 'notam': notam}
# fonti che cambiano poco: scaricate solo se la copia locale ha più di N ore
ETA_MAX_ORE = {'ourairports': 24 * 7, 'openaip': 24, 'osm_aerodromi': 24 * 3, 'osm_sicurezza': 24 * 7, 'osm_parchi': 24 * 14, 'osm_piste': 24 * 14, 'notam': 0}
FILE = {'ourairports': 'airports.csv', 'openaip': 'it_asp.geojson', 'osm_aerodromi': 'osm_aerodromi_elisuperfici_IT.tsv',
        'osm_sicurezza': 'osm_sicurezza_IT.json', 'osm_parchi': 'osm_aree_protette_IT.json', 'osm_piste': 'osm_piste_IT.json', 'notam': 'notam_IT.json'}


def main():
    src = sys.argv[1] if len(sys.argv) > 1 else 'fonti'
    which = sys.argv[2:] or list(FONTI)
    forza = os.environ.get('QZ_FORZA') == '1'
    os.makedirs(src, exist_ok=True)
    esito, errori = {}, []
    for k in which:
        p = os.path.join(src, FILE[k])
        if not forza and os.path.exists(p) and (time.time() - os.path.getmtime(p)) < ETA_MAX_ORE[k] * 3600:
            esito[k] = 'recente, non riscaricato'; continue
        print('→', k, flush=True)
        try:
            esito[k] = 'ok: ' + FONTI[k](src)
        except Exception as e:
            esito[k] = f'ERRORE: {e} (resta la copia precedente)' if os.path.exists(p) else f'ERRORE: {e} (nessuna copia)'
            errori.append(k)
        print('  ', esito[k], flush=True)
        if k.startswith('osm_'): time.sleep(30)          # gentile con Overpass
    json.dump({'data': time.strftime('%Y-%m-%dT%H:%M:%S%z'), 'esito': esito}, open(os.path.join(src, 'ultimo_scarico.json'), 'w'), ensure_ascii=False, indent=1)
    sys.exit(1 if errori else 0)


if __name__ == '__main__':
    main()
