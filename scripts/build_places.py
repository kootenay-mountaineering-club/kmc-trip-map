"""Turn data/place_list.txt into data/places.json (place -> coordinates), and list anything unresolved in data/places_todo.txt.

Sources (results cached in data/geocache.json so re-runs are instant and don't hit the services again):
  bc:   BC Geographical Names web service (official names: peaks, lakes, creeks, parks, communities)
  town: BC Geographical Names, populated places only
  osm:  OpenStreetMap Nominatim (trails, viewpoints, crags); max 1 request/second as their policy asks
  ll:   coordinates typed in by hand  (e.g.  ll:49.512,-117.301)
Places placed by hand on the site's "place it" tool are kept in data/places_manual.json and always win.

Run from the repository root:  python scripts/build_places.py
"""
import json, os, re, sys, time, urllib.parse, urllib.request

DATA = 'data'
BBOX = (48.9, 50.9, -119.2, -115.9)       # lat min/max, lon min/max: West Kootenay and a margin
TOWNS = {'nelson': (49.49, -117.29), 'castlegar': (49.32, -117.66), 'grand forks': (49.03, -118.44), 'trail': (49.10, -117.71),
         'rossland': (49.08, -117.80), 'kaslo': (49.91, -116.91), 'new denver': (49.99, -117.37), 'salmo': (49.19, -117.28),
         'christina lake': (49.04, -118.21), 'creston': (49.10, -116.51), 'crawford bay': (49.68, -116.83)}
UA = {'User-Agent': 'kmc-trips/1.0 (Kootenay Mountaineering Club trip map)'}


def norm(s):
    s = s.lower().replace("'", '')
    s = re.sub(r'\bmount\b|\bmt\b\.?', 'mt', s)
    return re.sub(r'[^a-z0-9]+', ' ', s).strip()


def get(url):
    req = urllib.request.Request(url, headers=UA)
    return json.loads(urllib.request.urlopen(req, timeout=40).read().decode())


def inbox(lat, lon):
    return BBOX[0] <= lat <= BBOX[1] and BBOX[2] <= lon <= BBOX[3]


def bc(name, town=False):
    q = urllib.parse.urlencode({'name': name, 'outputFormat': 'json', 'outputSRS': 4326, 'itemsPerPage': 50})
    feats = get('https://apps.gov.bc.ca/pub/bcgnws/names/search?' + q).get('features', [])
    best = []
    for f in feats:
        p = f['properties']; lon, lat = f['geometry']['coordinates'][:2]
        if norm(p['name']) != norm(name) or not inbox(lat, lon):
            continue
        if town and p.get('featureCategory') not in (1, 2):
            continue
        best.append({'lat': round(lat, 5), 'lon': round(lon, 5), 'source': 'BC Geographical Names',
                     'feature': p.get('featureType'), 'official': p['name']})
    return best


def osm(text):
    bounded = 'idaho' not in text.lower()
    q = {'q': text, 'format': 'json', 'limit': 5}
    if bounded:
        q.update({'viewbox': f'{BBOX[2]},{BBOX[1]},{BBOX[3]},{BBOX[0]}', 'bounded': 1})
    time.sleep(1.1)
    res = get('https://nominatim.openstreetmap.org/search?' + urllib.parse.urlencode(q))
    return [{'lat': round(float(r['lat']), 5), 'lon': round(float(r['lon']), 5), 'source': 'OpenStreetMap',
             'feature': f"{r.get('class')}/{r.get('type')}", 'official': r.get('display_name', '').split(',')[0]} for r in res]


def main():
    cache = json.load(open(f'{DATA}/geocache.json')) if os.path.exists(f'{DATA}/geocache.json') else {}
    manual = json.load(open(f'{DATA}/places_manual.json')) if os.path.exists(f'{DATA}/places_manual.json') else {}
    places, todo = {}, []
    for line in open(f'{DATA}/place_list.txt', encoding='utf-8'):
        if not line.strip() or line.startswith('#'):
            continue
        name, how, aliases = [x.strip() for x in (line.rstrip('\n') + ' | | ').split(' | ')[:3]]
        pid = re.sub(r'[^a-z0-9]+', '-', norm(name)).strip('-')
        rec = {'name': name, 'aliases': [a.strip() for a in aliases.split(';') if a.strip()], 'how': how}
        hits, kind = [], None
        for opt in [o.strip() for o in how.split('||')]:
            kind, _, arg = opt.partition(':')
            arg, _, near = arg.partition('~')
            if pid in manual or kind not in ('bc', 'town', 'osm'):
                break
            if opt not in cache:
                try:
                    cache[opt] = bc(arg, town=kind == 'town') if kind != 'osm' else osm(arg)
                except Exception as e:
                    print('lookup failed', opt, e, file=sys.stderr); cache[opt] = None
            hits = list(cache[opt] or [])
            if hits:
                ref = TOWNS.get(near.strip().lower(), TOWNS['nelson'])
                hits.sort(key=lambda h: (h['lat'] - ref[0]) ** 2 + ((h['lon'] - ref[1]) * 0.65) ** 2)
                break
        if pid in manual:
            hits = [dict(manual[pid], source='placed by hand')]
            rec['point'] = manual[pid].get('point')
            rec['aliases'] += [a for a in manual[pid].get('aliases', []) if a not in rec['aliases']]
        elif kind == 'll':
            lat, lon = map(float, arg.split(','))
            hits = [{'lat': lat, 'lon': lon, 'source': 'coordinates supplied by the club'}]
        if hits:
            h = hits[0]
            rec.update(lat=h['lat'], lon=h['lon'], source=h['source'], feature=h.get('feature'), official=h.get('official'),
                       precision='town' if kind == 'town' else 'place', alternatives=len(hits) - 1)
        else:
            todo.append(f'{name}  ({how})')
        places[pid] = rec
    for pid, m in manual.items():          # places first placed on the website (no line in place_list.txt yet)
        if pid.startswith('_') or pid in places:
            continue
        places[pid] = {'name': m.get('name', pid), 'aliases': m.get('aliases', []), 'how': 'placed on the website', 'lat': m['lat'], 'lon': m['lon'],
                       'source': 'placed by hand', 'precision': 'place', 'point': m.get('point'), 'alternatives': 0}
    json.dump(cache, open(f'{DATA}/geocache.json', 'w'), indent=0)
    json.dump(places, open(f'{DATA}/places.json', 'w'), indent=0, ensure_ascii=False)
    todo = [f"{v['name']}  ({v['how']})" for v in places.values() if v.get('lat') is None]
    open(f'{DATA}/places_todo.txt', 'w').write('Places that still need to be placed by hand:\n' + '\n'.join(todo) + '\n')
    print(len(places), 'places,', len(todo), 'to place by hand', file=sys.stderr)


if __name__ == '__main__':
    main()
