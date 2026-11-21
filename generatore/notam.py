#!/usr/bin/env python3
"""NOTAM italiani (FIR LIMM, LIRR, LIBB) -> zone temporanee per droni.

Fonte: servizio pubblico FAA NOTAM Search (notams.aim.faa.gov), che ripubblica i NOTAM internazionali ICAO.
Si tengono solo i NOTAM con un'area geografica (poligono o cerchio) che scende sotto i 120 m dal suolo.

  python3 notam.py scarica fonti/notam_it.json      # scarica (da usare nel container, 2 volte al giorno)
  python3 notam.py zone fonti/notam_it.json         # stampa quante zone si ottengono
"""
import json, math, re, sys, time, datetime, urllib.request, urllib.parse

FIRS = ('LIMM', 'LIRR', 'LIBB')
URL = 'https://notams.aim.faa.gov/notamSearch/search'
UA = 'QuotaZone/1.0 (uso personale; zone droni)'


def scarica(out):
    rows = []
    for fir in FIRS:
        off, total = 0, 1
        while off < total:
            data = urllib.parse.urlencode({'searchType': 0, 'designatorsForLocation': fir, 'notamsOnly': 'false', 'offset': off}).encode()
            req = urllib.request.Request(URL, data=data, headers={'User-Agent': UA, 'Content-Type': 'application/x-www-form-urlencoded'})
            j = json.load(urllib.request.urlopen(req, timeout=60))
            total = j.get('totalNotamCount', 0)
            for x in j.get('notamList') or []:
                rows.append({'fir': fir, 'num': x.get('notamNumber'), 'icao': x.get('icaoMessage') or ''})
            off += 30
            time.sleep(1.5)  # gentile con il servizio
    json.dump({'scaricato': datetime.datetime.utcnow().isoformat() + 'Z', 'notam': rows}, open(out, 'w'))
    print('NOTAM scaricati:', len(rows))


COORD = r'(\d{2})(\d{2})(\d{2}(?:\.\d+)?)?([NS])\s?(\d{3})(\d{2})(\d{2}(?:\.\d+)?)?([EW])'


def dms(m):
    d1, m1, s1, h1, d2, m2, s2, h2 = m
    lat = int(d1) + int(m1) / 60 + (float(s1) if s1 else 0) / 3600
    lon = int(d2) + int(m2) / 60 + (float(s2) if s2 else 0) / 3600
    return (-lat if h1 == 'S' else lat, -lon if h2 == 'W' else lon)


def circle(lat, lon, r_m, n=48):
    k = math.cos(math.radians(lat))
    ring = [[round(lon + (r_m * math.sin(2 * math.pi * i / n)) / (111320 * k), 6),
             round(lat + (r_m * math.cos(2 * math.pi * i / n)) / 111320, 6)] for i in range(n)]
    return [ring + [ring[0]]]


def height_m(s):
    """F)/G): restituisce (metri, riferimento) oppure (None, None) se non interpretabile."""
    s = (s or '').strip().upper().rstrip(')')
    if s in ('GND', 'SFC', '0'): return 0.0, 'AGL'
    m = re.match(r'(\d+)\s*(FT|M)\s*(AGL|AMSL|MSL)?', s)
    if m:
        v = float(m.group(1)) * (0.3048 if m.group(2) == 'FT' else 1)
        return v, 'AGL' if (m.group(3) or 'AGL') == 'AGL' else 'AMSL'
    m = re.match(r'FL\s*(\d+)', s)
    if m: return float(m.group(1)) * 100 * 0.3048, 'AMSL'
    return None, None


def ts(s):
    s = (s or '').strip()
    m = re.match(r'(\d{10})', s)
    if not m: return None
    return datetime.datetime.strptime(m.group(1), '%y%m%d%H%M').strftime('%Y-%m-%dT%H:%M:00Z')


RELEVANT_Q = re.compile(r'^Q(R[TRPDA]|W[UPALM])')  # aree temporanee, pericoli, attività UAS/paracadutisti/acrobazia
MAX_QLINE_NM = 25   # cerchi della riga Q più grandi: area di riferimento generica, non una zona


def zones(path):
    d = json.load(open(path))
    seen, out = set(), []
    for x in d['notam']:
        t = x['icao'].replace('\r', '')
        if 'CHECKLIST' in t: continue
        num = (re.search(r'([A-Z]\d{4}/\d{2})', t) or [None, x['num']])[1]
        if num in seen: continue
        seen.add(num)
        q = re.search(r'Q\)\s*\w+/(Q\w{4})/', t)
        qcode = q.group(1) if q else ''
        if not RELEVANT_Q.match(qcode): continue
        e = re.search(r'E\)(.*?)(?:\nF\)|$)', t, re.S)
        etext = e.group(1) if e else t
        f = re.search(r'F\)\s*([^\n]*?)\s*G\)', t); g = re.search(r'G\)\s*([^\n)]*)', t)
        lo, lref = height_m(f.group(1) if f else 'GND'); hi, href = height_m(g.group(1) if g else '')
        if lo is None: lo, lref = 0.0, 'AGL'
        if lref == 'AMSL' and lo > 300: continue          # parte troppo in alto per interessare un drone
        if lref == 'AGL' and lo >= 120: continue
        b = re.search(r'B\)\s*(\d{10})', t); c = re.search(r'C\)\s*(\d{10}|PERM)', t)
        start = ts(b.group(1)) if b else None
        end = None if not c or c.group(1) == 'PERM' else ts(c.group(1))
        # geometria: poligono di coordinate collegate da trattini, oppure cerchio "RADIUS ... OF coord"
        coords = [dms(m) for m in re.findall(COORD, etext)]
        geom = None
        rad = re.search(r'(\d+(?:\.\d+)?)\s*(NM|KM|M)\s+RADIUS', etext) or re.search(r'RADIUS\s+(?:OF\s+)?(\d+(?:\.\d+)?)\s*(NM|KM|M)\b', etext)
        if rad and coords:
            r = float(rad.group(1)) * {'NM': 1852, 'KM': 1000, 'M': 1}[rad.group(2)]
            geom = circle(coords[0][0], coords[0][1], r)
        elif len(coords) >= 3:
            ring = [[round(lon, 6), round(lat, 6)] for lat, lon in coords]
            if ring[0] != ring[-1]: ring.append(ring[0])
            geom = [ring]
        else:
            qq = re.search(r'/(\d{4})([NS])(\d{5})([EW])(\d{3})\s*$', t.split('\n')[1] if '\n' in t else '')
            qm = re.search(r'Q\)[^\n]*/(\d{2})(\d{2})([NS])(\d{3})(\d{2})([EW])(\d{3})', t)
            if qm:
                lat = int(qm.group(1)) + int(qm.group(2)) / 60; lon = int(qm.group(4)) + int(qm.group(5)) / 60
                if int(qm.group(7)) > MAX_QLINE_NM: continue
                geom = circle(lat, lon, max(int(qm.group(7)), 1) * 1852)
        if not geom: continue
        restr = 'PROHIBITED' if qcode.startswith(('QRT', 'QRP', 'QRD', 'QRR', 'QWU', 'QWP', 'QWA', 'QWL', 'QWM')) else 'REQ_AUTHORISATION'
        out.append({
            'identifier': 'QZ-NOTAM-' + num.replace('/', '-'), 'country': 'ITA', 'name': 'NOTAM ' + num,
            'type': 'COMMON', 'restriction': restr, 'reason': ['AIR_TRAFFIC'], 'otherReasonInfo': 'NOTAM',
            'message': re.sub(r'\s+', ' ', etext.strip())[:600],
            'applicability': [{'permanent': 'NO', 'startDateTime': start, 'endDateTime': end}] if end or start else [{'permanent': 'YES'}],
            'geometry': [{'uomDimensions': 'M', 'lowerLimit': round(lo if lref == 'AGL' else 0), 'lowerVerticalReference': 'AGL',
                          'upperLimit': 120, 'upperVerticalReference': 'AGL',
                          'horizontalProjection': {'type': 'Polygon', 'coordinates': geom}}]})
    return out


if __name__ == '__main__':
    if sys.argv[1] == 'scarica': scarica(sys.argv[2])
    else:
        z = zones(sys.argv[2]); print('zone NOTAM:', len(z))
