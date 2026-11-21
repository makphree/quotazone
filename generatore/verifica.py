#!/usr/bin/env python3
"""QuotaZone · verifica delle zone ricostruite contro un file D-Flight (solo confronto, uso personale).

Non copia nulla dal file D-Flight: calcola, su una griglia regolare che copre tutta l'Italia,
la quota massima di volo libero secondo i due file e misura dove differiscono.

Uso:
  python3 verifica.py zone_proprie.json[.gz] dflight_geozones_*.json.gz [--passo 1000] [--uscita rapporto]

Produce:
  rapporto.html      rapporto leggibile (riassunto, per causa, peggiori zone)
  rapporto.json      gli stessi numeri, per altri programmi
  storico.csv        una riga per esecuzione (per vedere il miglioramento nel tempo)
"""
import argparse, csv, datetime, gzip, html, json, math, os, re, sys, collections
from shapely.geometry import shape, Point, box
from shapely.strtree import STRtree
from shapely.prepared import prep

FT = 0.3048
QUI = os.path.dirname(os.path.abspath(__file__))


def open_any(p):
    return gzip.open(p, 'rt', encoding='utf-8') if p.endswith('.gz') else open(p, encoding='utf-8')


def active_now(f, now):
    """Zone temporanee: conta solo se attive adesso (permanenti sempre)."""
    for a in f.get('applicability') or []:
        if str(a.get('permanent', '')).upper() == 'YES':
            return True
        s, e = a.get('startDateTime'), a.get('endDateTime')
        try:
            if s and datetime.datetime.fromisoformat(s.replace('Z', '+00:00')) > now: continue
            if e and datetime.datetime.fromisoformat(e.replace('Z', '+00:00')) < now: continue
            return True
        except ValueError:
            return True
    return not f.get('applicability')


def limit_of(f, g):
    """Quota fino alla quale si vola senza autorizzazione dentro questo volume (m AGL)."""
    lo = g.get('lowerLimit') or 0
    if str(g.get('uomDimensions', 'M')).upper().startswith('F'):
        lo *= FT
    if str(f.get('restriction', '')).upper() == 'NO_RESTRICTION':
        return 120
    return lo


def category(f):
    n = str(f.get('name', ''))
    o = str(f.get('otherReasonInfo', '')).upper()
    if n.upper().startswith('NOTAM'): return 'NOTAM'
    if re.match(r'^LIPROT|^QZ-PROT', n) or 'NATURE' in (f.get('reason') or []) and o != 'ATM09': return 'aree protette'
    if re.match(r'^LI ?[PRD] ?\d|^QZ-ASP-[PRD]', n): return 'aree P/R/D'
    if re.search(r'\bCTR\b|\bATZ\b', n): return 'CTR/ATZ'
    if o == 'NFZ' and 'EMERGENCY' in (f.get('reason') or []): return 'NFZ regionali (parchi, emergenze)'
    if re.match(r'^QZ-ASP-S', n): return 'aree ULM/sportive'
    if o == 'NFZ' or 'SENSITIVE' in (f.get('reason') or []): return 'sicurezza (carceri, siti militari…)'
    if n.lower().startswith('avio') or 'elisuperf' in n.lower() or 'heli' in n.lower(): return 'avio/elisuperfici'
    return 'aerodromi'


def load(path, now):
    d = json.load(open_any(path))
    G, L, C, N = [], [], [], []
    for f in d['features']:
        if not active_now(f, now):
            continue
        for g in f.get('geometry') or []:
            hp = g.get('horizontalProjection') or {}
            c = hp.get('coordinates')
            if hp.get('type') == 'Circle':
                continue  # non usati né da D-Flight né dal nostro file
            if not c or not c[0]:
                continue
            try:
                geo = shape({'type': hp.get('type', 'Polygon'), 'coordinates': c})
                if not geo.is_valid: geo = geo.buffer(0)
            except Exception:
                continue
            lim = limit_of(f, g)
            if lim >= 120:
                continue
            G.append(geo); L.append(lim); C.append(category(f)); N.append(str(f.get('name', '')))
    return {'title': d.get('title', os.path.basename(path)), 'tree': STRtree(G), 'G': G, 'L': L, 'C': C, 'N': N}


def query(ds, p):
    best = None
    for i in ds['tree'].query(p):
        if ds['G'][i].contains(p):
            if best is None or ds['L'][i] < ds['L'][best]:
                best = i
    return (120, None, None) if best is None else (ds['L'][best], ds['C'][best], ds['N'][best])


BANDS = [0, 25, 45, 60, 120]
def band(v):
    for b in BANDS:
        if v <= b + 0.5: return b
    return 120


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('mine'); ap.add_argument('ref')
    ap.add_argument('--passo', type=float, default=1000, help='lato della griglia in metri (default 1000)')
    ap.add_argument('--uscita', default=os.path.join(QUI, 'rapporto'))
    ap.add_argument('--confine', default=os.path.join(QUI, 'fonti', 'italia.geojson'))
    a = ap.parse_args()
    now = datetime.datetime.now(datetime.timezone.utc)

    mine, ref = load(a.mine, now), load(a.ref, now)
    italia = shape(json.load(open(a.confine))['features'][0]['geometry'])
    pit = prep(italia)
    minx, miny, maxx, maxy = italia.bounds
    dlat = a.passo / 111320.0

    tot = 0
    res = collections.Counter()            # uguale / piu_prudente / meno_prudente
    sev = collections.Counter()            # gravità degli errori per difetto
    by_cause = collections.Counter()       # categoria della zona D-Flight non coperta
    worst = collections.defaultdict(lambda: [0, 0.0, 0.0, None])  # nome zona D-Flight -> [punti, lat, lon, causa]
    mat = collections.Counter()
    by_mine = collections.Counter()        # categoria della nostra zona quando siamo più prudenti
    worst_mine = collections.Counter()

    lat = miny
    while lat <= maxy:
        dlon = a.passo / (111320.0 * math.cos(math.radians(lat)))
        lon = minx
        row = []
        while lon <= maxx:
            row.append(Point(lon, lat)); lon += dlon
        for p in row:
            if not pit.contains(p): continue
            tot += 1
            m, mc, mn = query(mine, p)
            r, rc, rn = query(ref, p)
            bm, br = band(m), band(r)
            mat[(bm, br)] += 1
            if bm == br: res['uguale'] += 1
            elif bm < br:
                res['piu_prudente'] += 1; by_mine[mc] += 1; worst_mine[mn] += 1
            else:
                res['meno_prudente'] += 1
                diff = bm - br
                sev['critico (D-Flight 0 m, noi ≥ 45 m)' if br == 0 and bm >= 45 else 'grave (≥ 45 m di differenza)' if diff >= 45 else 'lieve (< 45 m)'] += 1
                by_cause[rc] += 1
                w = worst[rn]; w[0] += 1; w[1], w[2], w[3] = p.y, p.x, rc
        lat += dlat

    km2 = (a.passo / 1000) ** 2
    pct = lambda n: round(100.0 * n / tot, 2) if tot else 0
    rep = {
        'data': datetime.datetime.now().astimezone().isoformat(timespec='minutes'),
        'file_ricostruito': mine['title'], 'file_dflight': ref['title'], 'passo_m': a.passo, 'punti': tot,
        'uguale_pct': pct(res['uguale']), 'piu_prudente_pct': pct(res['piu_prudente']), 'meno_prudente_pct': pct(res['meno_prudente']),
        'meno_prudente_km2': round(res['meno_prudente'] * km2),
        'gravita': {k: {'punti': v, 'pct': pct(v), 'km2': round(v * km2)} for k, v in sev.most_common()},
        'cause': {k: {'pct': pct(v), 'km2': round(v * km2)} for k, v in by_cause.most_common()},
        'peggiori': [{'zona': n, 'km2': round(v[0] * km2), 'causa': v[3], 'lat': round(v[1], 4), 'lon': round(v[2], 4)}
                     for n, v in sorted(worst.items(), key=lambda x: -x[1][0])[:40]],
        'piu_prudente_per_causa': {k: {'pct': pct(v), 'km2': round(v * km2)} for k, v in by_mine.most_common()},
        'piu_prudente_zone': [{'zona': n, 'km2': round(v * km2)} for n, v in worst_mine.most_common(40)],
        'matrice': {f'{k[0]}->{k[1]}': v for k, v in mat.items()},
    }
    os.makedirs(os.path.dirname(a.uscita) or '.', exist_ok=True)
    json.dump(rep, open(a.uscita + '.json', 'w'), ensure_ascii=False, indent=1)
    write_html(rep, a.uscita + '.html')
    hist = os.path.join(os.path.dirname(a.uscita) or '.', 'storico.csv')
    new = not os.path.exists(hist)
    with open(hist, 'a', newline='') as fh:
        w = csv.writer(fh)
        if new: w.writerow(['data', 'file_dflight', 'punti', 'uguale_pct', 'piu_prudente_pct', 'meno_prudente_pct', 'critico_pct'])
        crit = next((v['pct'] for k, v in rep['gravita'].items() if k.startswith('critico')), 0)
        w.writerow([rep['data'], rep['file_dflight'], tot, rep['uguale_pct'], rep['piu_prudente_pct'], rep['meno_prudente_pct'], crit])
    print(f"punti {tot} · uguale {rep['uguale_pct']}% · più prudente {rep['piu_prudente_pct']}% · meno prudente {rep['meno_prudente_pct']}% ({rep['meno_prudente_km2']} km²)")
    for k, v in rep['gravita'].items(): print(f'  {k}: {v["pct"]}% ({v["km2"]} km²)')
    print('  per causa:', ', '.join(f'{k} {v["pct"]}%' for k, v in rep['cause'].items()))
    print('  più prudente per causa:', ', '.join(f'{k} {v["pct"]}%' for k, v in rep['piu_prudente_per_causa'].items()))
    print('  più prudente, zone principali:', '; '.join(f'{w["zona"]} {w["km2"]}' for w in rep['piu_prudente_zone'][:12]))
    return rep


def write_html(r, path):
    e = html.escape
    rows = lambda d: ''.join(f'<tr><td>{e(str(k))}</td><td class="n">{v["pct"]}%</td><td class="n">{v["km2"]:,} km²</td></tr>'.replace(',', '.') for k, v in d.items())
    worst = ''.join(f'<tr><td>{e(w["zona"] or "")}</td><td>{e(w["causa"] or "")}</td><td class="n">{w["km2"]}</td>'
                    f'<td><a href="https://www.openstreetmap.org/?mlat={w["lat"]}&mlon={w["lon"]}#map=12/{w["lat"]}/{w["lon"]}">{w["lat"]}, {w["lon"]}</a></td></tr>' for w in r['peggiori'])
    doc = f"""<!doctype html><html lang="it"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Verifica zone QuotaZone</title><style>
:root{{--bg:#f4f6f7;--fg:#14222c;--mut:#5a6b77;--line:#d3dbe0;--ok:#2c7a4b;--warn:#c47a00;--bad:#c42b2b;color-scheme:light}}
@media (prefers-color-scheme:dark){{:root{{--bg:#0f171d;--fg:#e2e9ed;--mut:#93a3ae;--line:#2a3a45;--ok:#45a86c;--warn:#f0a03a;--bad:#e45a5a;color-scheme:dark}}}}
body{{margin:0;padding:24px 16px;background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,sans-serif}} main{{max-width:880px;margin:auto}}
h1{{margin:0 0 4px;font-size:1.5rem}} h2{{font-size:1rem;text-transform:uppercase;letter-spacing:.08em;color:var(--mut);margin:28px 0 8px}}
.k{{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:10px}} .k div{{border:1px solid var(--line);border-radius:8px;padding:10px 12px}}
.k b{{display:block;font-size:1.6rem;font-variant-numeric:tabular-nums}} .ok b{{color:var(--ok)}} .warn b{{color:var(--warn)}} .bad b{{color:var(--bad)}}
table{{width:100%;border-collapse:collapse;font-size:.9rem}} td,th{{padding:6px 8px;border-bottom:1px solid var(--line);text-align:left}} .n{{text-align:right;font-variant-numeric:tabular-nums}}
.wrap{{overflow-x:auto}} p.m{{color:var(--mut);font-size:.85rem}} a{{color:inherit}}</style></head><body><main>
<h1>Verifica zone ricostruite</h1><p class="m">{e(r['data'])} · griglia {int(r['passo_m'])} m su tutta l'Italia ({r['punti']:,} punti) · ricostruito: {e(r['file_ricostruito'])} · riferimento: {e(r['file_dflight'])}</p>
<div class="k"><div class="ok"><b>{r['uguale_pct']}%</b>stessa quota massima</div><div class="warn"><b>{r['piu_prudente_pct']}%</b>più prudente</div>
<div class="bad"><b>{r['meno_prudente_pct']}%</b>meno prudente ({r['meno_prudente_km2']:,} km²)</div></div>
<h2>Gravità degli errori per difetto</h2><table>{rows(r['gravita'])}</table>
<h2>Cause (tipo di zona D-Flight non coperta)</h2><table>{rows(r['cause'])}</table>
<h2>Zone con la superficie scoperta più grande</h2><div class="wrap"><table><tr><th>Zona</th><th>Causa</th><th class="n">km²</th><th>Dove</th></tr>{worst}</table></div>
<h2>Dove siamo più prudenti (per strato del file ricostruito)</h2><table>{rows(r.get('piu_prudente_per_causa', {}))}</table>
<h2>Zone ricostruite che restringono di più rispetto a D-Flight</h2><div class="wrap"><table><tr><th>Zona</th><th class="n">km²</th></tr>{''.join(f'<tr><td>{e(w["zona"] or "")}</td><td class="n">{w["km2"]}</td></tr>' for w in r.get('piu_prudente_zone', [])[:20])}</table></div>
<p class="m">Confronto per uso personale: nessun dato D-Flight viene copiato nel file ricostruito. "Meno prudente" = punto in cui il file ricostruito permette una quota più alta di D-Flight.</p>
</main></body></html>""".replace(f"{r['punti']:,}", f"{r['punti']:,}".replace(',', '.'))
    open(path, 'w').write(doc)


if __name__ == '__main__':
    main()
