#!/usr/bin/env python3
"""Zone geografiche UAS intorno agli aerodromi, ricostruite in modo indipendente.

Fonti (libere):
  - OurAirports (pubblico dominio): posizione aerodromi/eliporti/aviosuperfici, piste, orientamento
  - Criteri geometrici della Circolare ENAC ATM-09A, par. 6.8–6.11 (testo normativo pubblico)

Uscita: file ED-269 (JSON) leggibile da QuotaZone.
Limiti noti (vedi LEGGIMI): manca il ritaglio sui CTR/ATZ e la fascia "oltre" (60 m nei CTR),
la classificazione strumentale/militare è approssimata, OurAirports non contiene tutte le avio/elisuperfici.
"""
import csv, json, math, re, sys, datetime
from shapely.geometry import Polygon, Point, mapping
from shapely.ops import unary_union

SRC = sys.argv[1] if len(sys.argv) > 1 else 'fonti'
OUT = sys.argv[2] if len(sys.argv) > 2 else 'zone_aerodromi_ed269.json'
DECL = 3.5  # declinazione magnetica media Italia (°E), per ricavare la direzione vera dal numero pista

# aeroporti militari (inclusi quelli aperti al traffico civile, contrassegnati (*) nell'Allegato B ATM-09A)
# aeroporti militari (da completare): elenco minimo, Allegato B ATM-09A segna con (*) quelli aperti al traffico civile
MILITARY_SURE = {'LIPA','LIPL','LIBA','LICZ','LIRS','LIRL','LIRG','LIRV','LIRE','LIRM','LIBV','LIBG','LIEE','LIPI','LIPS','LIMN','LIPC','LIMS','LIRP'}

M_PER_DEG_LAT = 111320.0
def to_xy(lat0, lon0):
    k = math.cos(math.radians(lat0))
    f = lambda lat, lon: ((lon - lon0) * M_PER_DEG_LAT * k, (lat - lat0) * M_PER_DEG_LAT)
    g = lambda x, y: (lat0 + y / M_PER_DEG_LAT, lon0 + x / (M_PER_DEG_LAT * k))
    return f, g

def rect(cx, cy, hdg, half_len, half_wid):
    a = math.radians(hdg)
    ux, uy = math.sin(a), math.cos(a)       # asse pista (nord = 0°)
    vx, vy = uy, -ux                        # perpendicolare
    pts = []
    for s, t in ((1, 1), (1, -1), (-1, -1), (-1, 1)):
        pts.append((cx + s * half_len * ux + t * half_wid * vx, cy + s * half_len * uy + t * half_wid * vy))
    return Polygon(pts)

def heading_of(r):
    for k in ('le_heading_degT', 'he_heading_degT'):
        if r.get(k):
            try: return float(r[k]) % 180
            except ValueError: pass
    try:
        if r['le_latitude_deg'] and r['he_latitude_deg']:
            la1, lo1, la2, lo2 = map(float, (r['le_latitude_deg'], r['le_longitude_deg'], r['he_latitude_deg'], r['he_longitude_deg']))
            dx = (lo2 - lo1) * math.cos(math.radians(la1)); dy = la2 - la1
            return math.degrees(math.atan2(dx, dy)) % 180
    except ValueError:
        pass
    m = re.match(r'^(\d{1,2})', r.get('le_ident') or '')
    if m and 1 <= int(m.group(1)) <= 36:
        return (int(m.group(1)) * 10 + DECL) % 180
    return None

def to_ll(poly, g):
    if poly.geom_type == 'MultiPolygon':
        poly = max(poly.geoms, key=lambda p: p.area)
    ring = [list(reversed(g(x, y))) for x, y in poly.exterior.coords]  # [lon, lat]
    return [[ [round(c[0], 6), round(c[1], 6)] for c in ring ]]

import os
HELI_MODE = os.environ.get('QZ_HELI', 'tutte')   # tutte | nominate (solo elisuperfici con nome o di soccorso)

def osm_points(airports):
    """Elisuperfici e aviosuperfici da OpenStreetMap (ODbL) che OurAirports non contiene."""
    p = f'{SRC}/osm_aerodromi_elisuperfici_IT.tsv'
    if not os.path.exists(p): return []
    known = [(float(a['latitude_deg']), float(a['longitude_deg'])) for a in airports]
    def near(lat, lon, r_m):
        k = math.cos(math.radians(lat))
        return any(((la - lat) * 111320) ** 2 + ((lo - lon) * 111320 * k) ** 2 < r_m ** 2 for la, lo in known)
    out = []
    for r in csv.DictReader(open(p, encoding='utf-8'), delimiter='\t'):
        if r.get('disused') == '1': continue
        lat, lon = float(r['lat']), float(r['lon']); aw = r['aeroway']
        if aw in ('helipad', 'heliport'):
            if HELI_MODE == 'nominate' and not (r['name'] or r['emergency'] or r['icao']): continue
            if near(lat, lon, 400): continue
            t = 'heliport'
        else:
            if near(lat, lon, 1500): continue
            t = 'small_airport'
        out.append({'ident': 'OSM-' + r['id'], 'name': r['name'] or ('Elisuperficie' if t == 'heliport' else 'Aviosuperficie') + ' (OSM)',
                    'type': t, 'latitude_deg': r['lat'], 'longitude_deg': r['lon'], 'icao_code': r['icao'], 'gps_code': '', 'src': 'OpenStreetMap'})
        known.append((lat, lon))
    return out

def osm_runways():
    """Piste da OpenStreetMap (aeroway=runway): [(lat, lon, direzione vera 0-179)]."""
    p = f'{SRC}/osm_piste_IT.json'
    if not os.path.exists(p): return []
    out = []
    for e in json.load(open(p))['elements']:
        g = e.get('geometry') or []
        if len(g) < 2: continue
        a, b = g[0], g[-1]
        k = math.cos(math.radians(a['lat']))
        dx, dy = (b['lon'] - a['lon']) * k, b['lat'] - a['lat']
        if math.hypot(dx, dy) * 111320 < 150: continue      # troppo corta per essere una pista
        out.append(((a['lat'] + b['lat']) / 2, (a['lon'] + b['lon']) / 2, round(math.degrees(math.atan2(dx, dy))) % 180))
    return out

def openaip_index():
    """Classificazione e piste da openAIP (CC BY-NC 4.0), se il file c'è: ICAO -> (tipo, [direzioni vere])."""
    p = f'{SRC}/it_apt.geojson'
    idx, pts = {}, []
    if not os.path.exists(p): return idx, pts
    for f in json.load(open(p))['features']:
        q = f['properties']; t = q.get('type')
        kind = {3: 'strumentale', 5: 'militare', 4: 'eliporto', 7: 'eliporto'}.get(t)   # tipi 0/2/9 di openAIP poco affidabili per IFR
        hd = sorted({round(r['trueHeading']) % 180 for r in q.get('runways') or [] if r.get('trueHeading') is not None})
        lon, lat = f['geometry']['coordinates'][:2]
        rec = (kind, hd, q.get('name'), lat, lon, t)
        if q.get('icaoCode'): idx[q['icaoCode']] = rec
        pts.append(rec)
    return idx, pts

def aerodrome_features(now=None):
    now = now or datetime.datetime.now()
    oa_idx, oa_pts = openaip_index()
    airports = [r for r in csv.DictReader(open(f'{SRC}/airports.csv', encoding='utf-8')) if r['iso_country'] == 'IT' and r['type'] != 'closed']
    extra = osm_points(airports)
    print('punti aggiunti da OSM:', len(extra), '(modalità elisuperfici:', HELI_MODE + ')')
    airports += extra
    # aerodromi presenti solo in openAIP (aviosuperfici, campi volo)
    known = [(float(a['latitude_deg']), float(a['longitude_deg'])) for a in airports]
    for kind_, hd, name, lat, lon, t in oa_pts:
        if t == 8: continue  # chiuso
        k = math.cos(math.radians(lat))
        if any(((la - lat) * 111320) ** 2 + ((lo - lon) * 111320 * k) ** 2 < 1500 ** 2 for la, lo in known): continue
        airports.append({'ident': 'OAIP-%.4f-%.4f' % (lat, lon), 'name': (name or 'Aviosuperficie').title(), 'type': 'heliport' if kind_ == 'eliporto' else 'small_airport',
                         'latitude_deg': str(lat), 'longitude_deg': str(lon), 'icao_code': '', 'gps_code': '', 'src': 'openAIP', '_hd': hd})
        known.append((lat, lon))
    runways = {}
    for r in csv.DictReader(open(f'{SRC}/runways.csv', encoding='utf-8')):
        if r.get('closed') == '1': continue
        runways.setdefault(r['airport_ident'], []).append(r)

    osm_rw = osm_runways()
    print('piste OSM:', len(osm_rw))
    def near_runways(lat, lon, r_m=1200):
        k = math.cos(math.radians(lat))
        return sorted({h for la, lo, h in osm_rw if ((la - lat) * 111320) ** 2 + ((lo - lon) * 111320 * k) ** 2 < r_m ** 2})

    feats, stats = [], {}
    for a in airports:
        lat, lon = float(a['latitude_deg']), float(a['longitude_deg'])
        f, g = to_xy(lat, lon)
        icao = a.get('icao_code') or a.get('gps_code') or ''
        t = a['type']
        oa = oa_idx.get(icao)
        if icao in MILITARY_SURE or (oa and oa[0] == 'militare'): kind = 'militare'
        elif t == 'heliport': kind = 'eliporto'
        elif (oa and oa[0] == 'strumentale') or t in ('large_airport', 'medium_airport'): kind = 'strumentale'
        elif icao.startswith('LI') and len(icao) == 4: kind = 'non_strumentale'
        else: kind = 'aviosuperficie'
        stats[kind] = stats.get(kind, 0) + 1

        hdgs = []
        for r in runways.get(a['ident'], []):
            h = heading_of(r)
            if h is not None: hdgs.append(h)
        hdgs = sorted(set(round(h) for h in hdgs))
        if oa and oa[1]: hdgs = oa[1]            # piste openAIP (direzione vera)
        if a.get('_hd'): hdgs = a['_hd']
        if not hdgs and t != 'heliport' and osm_rw: hdgs = near_runways(lat, lon)

        def runway_shape(L, W):
            if not hdgs:  # senza orientamento: cerchio prudenziale
                return Point(0, 0).buffer(L, 64), False
            return unary_union([rect(0, 0, h, L, W) for h in hdgs]), True

        if kind == 'aviosuperficie' and hdgs: kind = 'non_strumentale'   # pista nota: rettangoli ATM-09A par. 6.9
        layers = []  # (nome, colore, quota inferiore m, poligono)
        if kind == 'strumentale':
            red, ok = runway_shape(6000, 2500); org, _ = runway_shape(10000, 4000); yel, _ = runway_shape(15000, 8000)
            layers = [('area rossa', 0, red), ('area arancione', 25, org), ('area gialla', 45, yel)]
            rule = 'ATM-09A par. 6.8 (aeroporto civile con procedure strumentali)'
        elif kind == 'non_strumentale':
            red, ok = runway_shape(3000, 1000); org, _ = runway_shape(6000, 2500); yel, _ = runway_shape(10000, 4000)
            layers = [('area rossa', 0, red), ('area arancione', 25, org), ('area gialla', 45, yel)]
            rule = 'ATM-09A par. 6.9 (aeroporto senza procedure strumentali)'
        elif kind in ('eliporto', 'aviosuperficie'):
            ok = True
            layers = [('area rossa', 0, Point(0, 0).buffer(1500, 64)), ('area arancione', 25, Point(0, 0).buffer(2500, 64)), ('area gialla', 45, Point(0, 0).buffer(3500, 64))]
            rule = 'ATM-09A par. 6.10 (eliporto / elisuperficie)' if kind == 'eliporto' else 'aviosuperficie / campo di volo: cerchi 1,5 / 2,5 / 3,5 km come le avio-elisuperfici'
        else:  # militare
            yel_r, ok = runway_shape(15000, 8000)
            layers = [('area rossa', 0, Point(0, 0).buffer(6000, 64)), ('area arancione', 25, Point(0, 0).buffer(10000, 64)),
                      ('area gialla', 45, unary_union([yel_r, Point(0, 0).buffer(10000, 64)]))]
            rule = 'ATM-09A par. 6.11 (aeroporto militare)'

        label = a['name'] + (f' ({icao})' if icao else '')
        for nm, lower, poly in layers:
            feats.append({
                'identifier': f"QZ-{a['ident']}-{nm.split()[1][:1].upper()}",
                'country': 'ITA',
                'name': f'{label} · {nm}',
                'type': 'COMMON',
                'restriction': 'REQ_AUTHORISATION',
                'reason': ['AIR_TRAFFIC'],
                'otherReasonInfo': 'ATM09',
                'message': f'Ricostruita da QuotaZone: {rule}. Posizione da ' + a.get('src', 'OurAirports')
                           + ('' if ok else '; orientamento pista sconosciuto, area circolare prudenziale')
                           + '. Attiva negli orari di apertura dello scalo. Senza ritaglio sui limiti CTR/ATZ.',
                'applicability': [{'permanent': 'YES'}],
                'geometry': [{'uomDimensions': 'M', 'lowerLimit': lower, 'lowerVerticalReference': 'AGL',
                              'upperLimit': 120, 'upperVerticalReference': 'AGL',
                              'horizontalProjection': {'type': 'Polygon', 'coordinates': to_ll(poly, g)}}]
            })
    print('aerodromi', len(airports), stats, '-> zone', len(feats))
    return feats

def main():
    now = datetime.datetime.now()
    feats = aerodrome_features(now)
    out = {'title': 'QZ zone aerodromi ' + now.strftime('%d/%m/%Y %H:%M'),
           'description': 'Zone ricostruite da QuotaZone con i criteri ENAC ATM-09A, posizioni OurAirports (pubblico dominio) e © OpenStreetMap contributors (ODbL). '
                          'Non ufficiali: verifica sempre su D-Flight prima del volo.',
           'features': feats}
    json.dump(out, open(OUT, 'w'), ensure_ascii=False)
    print('->', OUT)

if __name__ == '__main__':
    main()
