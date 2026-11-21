#!/usr/bin/env python3
"""QuotaZone · genera il file completo di zone UAS ricostruite da fonti indipendenti (formato ED-269).

Strati:
  1. Aerodromi, avio ed elisuperfici  (OurAirports PD, OpenStreetMap ODbL, openAIP CC BY-NC) + regole ENAC ATM-09A
  2. Fascia 60 m in CTR / ATZ / MATZ    (openAIP)                                   ATM-09A par. 6.8d–6.11d
  3. Aree P / R / D dell'AIP           (openAIP)                                   ATM-09A par. 5.1b / 5.3
  4. Parchi con limitazione di sorvolo (openAIP "low altitude overflight restriction")
  5. Carceri e aree militari           (OpenStreetMap)
  5b. Parchi nazionali e regionali     (OpenStreetMap)                             L. 394/1991 art. 11
  6. NOTAM temporanei                  (FAA NOTAM Search)

  python3 genera_zone.py [cartella_fonti] [uscita.json]
"""
import datetime, json, math, os, re, sys
from shapely.geometry import shape, mapping, Polygon, MultiPolygon
from shapely.ops import unary_union

SRC = sys.argv[1] if len(sys.argv) > 1 else 'fonti'
OUT = sys.argv[2] if len(sys.argv) > 2 else 'zone_proprie_ed269.json'
os.environ.setdefault('QZ_SRC', SRC)
sys.argv = [sys.argv[0], SRC]                       # genera_aerodromi legge SRC da argv
import genera_aerodromi as ga
import notam as nt

FT = 0.3048
PRISON_BUFFER_M = float(os.environ.get('QZ_CARCERI_M', '500'))
MILITARY_BUFFER_M = float(os.environ.get('QZ_MILITARI_M', '150'))
ASP_AMSL_MAX = float(os.environ.get('QZ_ASP_AMSL_MAX', '600'))   # P/R/D con base AMSL oltre questa quota: ignorate
INCLUDE_D = os.environ.get('QZ_AREE_D', '1') == '1'
LAYERS = set((os.environ.get('QZ_STRATI') or 'aerodromi,spazi,sicurezza,parchi,notam').split(','))


def lim_m(l):
    """openAIP: unit 0=m 1=ft 6=FL; referenceDatum 0=GND 1=MSL 2=STD. Ritorna (metri, 'AGL'|'AMSL')."""
    v, u, r = l.get('value', 0), l.get('unit', 1), l.get('referenceDatum', 0)
    m = v * (FT * 100 if u == 6 else FT if u == 1 else 1)
    return m, ('AGL' if r == 0 else 'AMSL')


def ring_coords(geom):
    """Shapely -> lista di poligoni ED-269 (solo anello esterno + buchi)."""
    polys = [geom] if geom.geom_type == 'Polygon' else list(getattr(geom, 'geoms', []))
    out = []
    for p in polys:
        if p.is_empty or p.geom_type != 'Polygon': continue
        rings = [[[round(x, 6), round(y, 6)] for x, y in p.exterior.coords]]
        rings += [[[round(x, 6), round(y, 6)] for x, y in i.coords] for i in p.interiors]
        out.append(rings)
    return out


def feature(ident, name, restriction, reasons, info, lower, message, geom, applic=None):
    return [{
        'identifier': f'{ident}#{i}' if len(geom) > 1 else ident, 'country': 'ITA', 'name': name, 'type': 'COMMON',
        'restriction': restriction, 'reason': reasons, 'otherReasonInfo': info, 'message': message,
        'applicability': applic or [{'permanent': 'YES'}],
        'geometry': [{'uomDimensions': 'M', 'lowerLimit': round(lower), 'lowerVerticalReference': 'AGL',
                      'upperLimit': 120, 'upperVerticalReference': 'AGL',
                      'horizontalProjection': {'type': 'Polygon', 'coordinates': g}}]} for i, g in enumerate(geom)]


def airspaces():
    p = os.path.join(SRC, 'it_asp.geojson')
    if not os.path.exists(p): print('manca it_asp.geojson: salto CTR, ATZ, P/R/D, parchi'); return []
    feats, stats = [], {}
    for f in json.load(open(p))['features']:
        q = f['properties']; t = q.get('type'); name = q.get('name', '')
        lo, ref = lim_m(q.get('lowerLimit') or {})
        try:
            g = shape(f['geometry']); g = g if g.is_valid else g.buffer(0)
        except Exception:
            continue
        geo = ring_coords(g)
        if not geo: continue
        src = 'Fonte: openAIP (CC BY-NC 4.0).'
        if t in (4, 13, 14):                          # CTR, ATZ, MATZ
            if not (ref == 'AGL' and lo < 120): continue
            kind = {4: 'CTR', 13: 'ATZ', 14: 'MATZ'}[t]
            feats += feature(f'QZ-ASP-{kind}-{q["_id"]}', f'{name} · {kind} (fascia 60 m)' if kind not in name else f'{name} (fascia 60 m)',
                             'REQ_AUTHORISATION', ['AIR_TRAFFIC'], 'ATM09', 60,
                             f'Dentro {kind}: oltre 60 m AGL serve autorizzazione (ATM-09A par. 6.8d–6.11d). {src}', geo)
        elif t in (1, 2, 3):                          # Restricted, Danger, Prohibited
            if ref == 'AMSL' and lo > ASP_AMSL_MAX: continue   # parte molto in alto: non riguarda un drone
            if t == 2 and not INCLUDE_D: continue
            if ref == 'AGL' and lo >= 120: continue
            letter = {1: 'R', 2: 'D', 3: 'P'}[t]
            feats += feature(f'QZ-ASP-{letter}-{q["_id"]}', f'QZ-ASP-{letter} {name}', 'PROHIBITED', ['AIR_TRAFFIC'], 'ENR5',
                             lo if ref == 'AGL' else 0,
                             f'Area {letter} dell\'AIP Italia ENR 5: vietata agli UAS' + (' quando attiva' if letter == 'R' else '') +
                             f' (ATM-09A par. 5.3). Limite inferiore indicato: {round(lo)} m {ref}. {src}', geo)
        elif t == 29:                                 # parchi: limitazione di sorvolo a bassa quota
            if not (ref == 'AGL' and lo < 120): continue
            feats += feature(f'QZ-PROT-{q["_id"]}', f'QZ-PROT {name}', 'REQ_AUTHORISATION', ['NATURE'], 'PARCO', 0,
                             f'Area protetta con limitazione di sorvolo: verifica il regolamento del parco prima di volare. {src}', geo)
        elif t == 28:                                 # aree ULM / acrobazia / attività sportive fino a terra
            if not (ref == 'AGL' and lo < 120): continue
            feats += feature(f'QZ-ASP-S-{q["_id"]}', f'QZ-ASP-S {name}', 'REQ_AUTHORISATION', ['AIR_TRAFFIC'], 'ATM09', lo,
                             f'Area di attività aerea sportiva/ULM pubblicata in AIP: serve coordinamento/autorizzazione. {src}', geo)
        elif t in (8, 9) and ref == 'AGL' and lo < 120:   # TRA / TSA fino a terra
            feats += feature(f'QZ-ASP-T-{q["_id"]}', f'QZ-ASP-R {name}', 'PROHIBITED', ['AIR_TRAFFIC'], 'ENR5', lo,
                             f'Area riservata temporanea (TRA/TSA), vietata quando attiva. {src}', geo)
        else:
            continue
        stats[t] = stats.get(t, 0) + 1
    print('spazi aerei openAIP usati per tipo:', stats)
    return feats


def security():
    p = os.path.join(SRC, 'osm_sicurezza_IT.json')
    if not os.path.exists(p): print('manca osm_sicurezza_IT.json'); return []
    feats, n = [], {'carceri': 0, 'militari': 0}
    for e in json.load(open(p))['elements']:
        tags = e.get('tags') or {}
        prison = tags.get('amenity') == 'prison'
        if not prison and not (tags.get('landuse') == 'military' or tags.get('military')): continue
        if tags.get('military') in ('bunker', 'checkpoint', 'trench', 'office'): continue
        geom = None
        if e['type'] == 'way' and e.get('geometry'):
            pts = [(c['lon'], c['lat']) for c in e['geometry']]
            if len(pts) >= 4 and pts[0] == pts[-1]: geom = Polygon(pts)
        elif e['type'] == 'relation' and e.get('members'):
            rings = [[(c['lon'], c['lat']) for c in m['geometry']] for m in e['members'] if m.get('role') == 'outer' and m.get('geometry')]
            polys = [Polygon(r) for r in rings if len(r) >= 4 and r[0] == r[-1]]
            if polys: geom = unary_union(polys)
        elif e['type'] == 'node':
            geom = shape({'type': 'Point', 'coordinates': [e['lon'], e['lat']]}).buffer(0.0015)
        if geom is None or geom.is_empty: continue
        if not geom.is_valid: geom = geom.buffer(0)
        lat = geom.centroid.y
        buf = (PRISON_BUFFER_M if prison else MILITARY_BUFFER_M) / 111320.0
        geom = geom.buffer(buf, 12) if buf > 0 else geom
        geom = geom.simplify(0.00005)
        name = tags.get('name') or ('Istituto penitenziario' if prison else 'Area militare')
        kind = 'carceri' if prison else 'militari'; n[kind] += 1
        feats += feature(f'QZ-SEC-{e["type"][0]}{e["id"]}', f'{name} ({"carcere" if prison else "area militare"})', 'PROHIBITED',
                         ['SENSITIVE'], 'NFZ', 0,
                         ('Zona di sicurezza ricostruita: perimetro OpenStreetMap più %d m. ' % (PRISON_BUFFER_M if prison else MILITARY_BUFFER_M)) +
                         'Il divieto ufficiale e la sua estensione possono essere diversi. © OpenStreetMap contributors (ODbL).',
                         ring_coords(geom))
    print('siti di sicurezza:', n)
    return feats


def osm_geom(e):
    if e['type'] == 'way' and e.get('geometry'):
        pts = [(c['lon'], c['lat']) for c in e['geometry']]
        return Polygon(pts) if len(pts) >= 4 and pts[0] == pts[-1] else None
    if e['type'] == 'relation' and e.get('members'):
        # anelli esterni: unisce i tratti aperti per formare anelli chiusi
        from shapely.ops import linemerge, polygonize
        from shapely.geometry import LineString
        lines = [LineString([(c['lon'], c['lat']) for c in m['geometry']]) for m in e['members']
                 if m.get('role') in ('outer', '') and m.get('geometry') and len(m['geometry']) > 1]
        if not lines: return None
        polys = list(polygonize(linemerge(lines)))
        return unary_union(polys) if polys else None
    return None


def parks():
    """Parchi nazionali e regionali da OpenStreetMap: L. 394/1991 art. 11 vieta il sorvolo non autorizzato nei parchi nazionali."""
    p = next((os.path.join(SRC, n) for n in ('osm_aree_protette_IT.json', 'osm_aree_protette_IT_parziale.json') if os.path.exists(os.path.join(SRC, n))), None)
    if not p: print('manca osm_aree_protette_IT.json'); return []
    feats, n, seen = [], {'nazionali': 0, 'regionali': 0}, set()
    for e in json.load(open(p))['elements']:
        if (e['type'], e['id']) in seen: continue
        seen.add((e['type'], e['id']))
        t = e.get('tags') or {}
        title = (t.get('protection_title') or '').lower(); name = t.get('name') or ''
        if 'marin' in title or 'marin' in name.lower() or t.get('protected_area') == 'marine': continue
        national = t.get('boundary') == 'national_park' or (t.get('protect_class') == '2' and 'nazionale' in (title + name.lower()))
        regional = not national and (t.get('protect_class') == '5' or 'parco' in title or name.lower().startswith('parco'))
        if not (national or regional): continue
        g = osm_geom(e)
        if g is None or g.is_empty: continue
        if not g.is_valid: g = g.buffer(0)
        g = g.simplify(0.0003)
        kind = 'nazionali' if national else 'regionali'; n[kind] += 1
        msg = ('Parco nazionale: la L. 394/1991 (art. 11) vieta il sorvolo non autorizzato. Serve il nulla osta dell\'Ente Parco.'
               if national else 'Parco regionale: molti regolamenti vietano o limitano il volo dei droni. Verifica con l\'Ente gestore.')
        feats += feature(f'QZ-PROT-OSM-{e["type"][0]}{e["id"]}', f'QZ-PROT {name or "Parco"}', 'REQ_AUTHORISATION', ['NATURE'], 'PARCO', 0,
                         msg + ' Confine © OpenStreetMap contributors (ODbL).', ring_coords(g))
    print('parchi OSM:', n, '(file', os.path.basename(p) + ')')
    return feats


def notams():
    p = os.path.join(SRC, 'notam_IT.json')
    if not os.path.exists(p): print('manca notam_IT.json'); return []
    z = nt.zones(p)
    for f in z: f['message'] = (f.get('message') or '') + ' Fonte: NOTAM via FAA NOTAM Search.'
    print('NOTAM con area sotto i 120 m:', len(z))
    return z


def main():
    now = datetime.datetime.now()
    feats = ((ga.aerodrome_features(now) if 'aerodromi' in LAYERS else []) + (airspaces() if 'spazi' in LAYERS else []) +
             (security() if 'sicurezza' in LAYERS else []) + (parks() if 'parchi' in LAYERS else []) + (notams() if 'notam' in LAYERS else []))
    out = {'title': 'QZ zone ricostruite ' + now.strftime('%d/%m/%Y %H:%M'),
           'description': 'Zone UAS ricostruite da QuotaZone con fonti indipendenti da D-Flight: regole ENAC ATM-09A; '
                          'OurAirports (pubblico dominio); © OpenStreetMap contributors (ODbL); openAIP (CC BY-NC 4.0); NOTAM via FAA. '
                          'Non ufficiale: verifica sempre su D-Flight prima del volo.',
           'features': feats}
    json.dump(out, open(OUT, 'w'), ensure_ascii=False)
    print('totale zone', len(feats), '->', OUT)


if __name__ == '__main__':
    main()
