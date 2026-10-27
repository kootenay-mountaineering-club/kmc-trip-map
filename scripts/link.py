"""Put it all together for the website: data/trips.json + places.json + reports.json -> data/site_trips.json.

- Each trip gets its place (coordinates) from the place list's names/aliases.
- Each newsletter report is matched to the trip held that day (or the multi-day trip covering it), choosing the
  best name / organizer match when several trips share a date.
- Participant names are cleaned with data/people_aliases.json (spelling variants -> one spelling).
Run from the repository root:  python scripts/link.py
"""
import json, re, sys, datetime as dt

D = 'data'


def norm(s):
    s = s.lower().replace("'", '')
    s = re.sub(r'\bmount\b|\bmt\b\.?', 'mt', s)
    return re.sub(r'[^a-z0-9]+', ' ', s).strip()


STOP = {'mt', 'the', 'and', 'to', 'of', 'via', 'loop', 'trail', 'trails', 'peak', 'peaks', 'mountain', 'mountains', 'mts', 'hike', 'a', 'in', 'day', 'pleasant'}


def toks(s):
    return {t[:5] for t in norm(s).split() if t not in STOP and len(t) > 2}


def main():
    trips = json.load(open(f'{D}/trips.json'))
    places = json.load(open(f'{D}/places.json'))
    reports = json.load(open(f'{D}/reports.json'))
    issues = json.load(open(f'{D}/newsletters.json'))
    try:
        people = json.load(open(f'{D}/people_aliases.json'))
    except FileNotFoundError:
        people = {}
    alias = {}
    for pid, p in places.items():
        for a in p['aliases'] + [norm(p['name'])]:
            alias[norm(a)] = pid
    missing = set()
    out = []
    for t in trips:
        pid = alias.get(norm(t['name']))
        p = places.get(pid) if pid else None
        if not p:
            missing.add(t['name'])
        rec = {k: t.get(k) for k in ('id', 'year', 'date', 'end', 'name', 'type', 'grade', 'organizer', 'notes', 'participants_count',
                                     'non_members', 'status', 'moved_to', 'parent_tot')}
        rec['place'] = {'id': pid, 'name': p['name'], 'lat': p.get('lat'), 'lon': p.get('lon'), 'precision': p.get('precision'),
                        'source': p.get('source'), 'official': p.get('official'), 'point': p.get('point')} if p else None
        rec['reports'] = []
        out.append(rec)
    # newsletter reports -> trips
    unmatched = []
    for r in reports:
        d0 = dt.date.fromisoformat(r['date'])
        cands = []
        for t in out:
            if t['status'] != 'held':
                continue
            a, b = dt.date.fromisoformat(t['date']), dt.date.fromisoformat(t['end'] or t['date'])
            if a <= d0 <= b or (r['end'] and a <= dt.date.fromisoformat(r['end']) and d0 <= b):
                sc = len(toks(r['title']) & toks(t['name'] + ' ' + (t['place']['name'] if t['place'] else '')))
                if r['writer'] and t['organizer'] and toks(r['writer']) & toks(t['organizer']):
                    sc += 0.5
                cands.append((sc, t))
        cands.sort(key=lambda x: -x[0])
        if not cands or (len(cands) > 1 and cands[0][0] == cands[1][0]) or (cands[0][0] == 0 and len(cands) > 1):
            unmatched.append(r); continue
        t = cands[0][1]
        names = [people.get(n, n) for n in r['participants']]
        t['reports'].append({'issue': r['issue'], 'issue_title': issues[r['issue']]['title'], 'url': issues[r['issue']].get('url'),
                             'page': r['page'], 'title': r['title'], 'writer': r['writer'], 'participants': names, 'stats': r['stats'],
                             'match_score': cands[0][0]})
    # GPS tracks and photos (from scripts/process_tracks.py) -> trips; trips without a map point get one from their track
    try:
        tracks = json.load(open(f'{D}/tracks_index.json'))
        photos = json.load(open(f'{D}/photos_index.json'))
    except FileNotFoundError:
        tracks, photos = [], []
    byid = {t['id']: t for t in out}
    for t in out:
        t['tracks'], t['photos'] = [], []
    for tr in tracks:
        t = byid.get(tr.get('trip'))
        if not t:
            continue
        t['tracks'].append({k: tr.get(k) for k in ('id', 'date', 'km', 'gain_m', 'hours', 'by')})
        if not (t['place'] and t['place'].get('lat') is not None) and tr.get('high'):
            pid = (t['place'] or {}).get('id') or re.sub(r'[^a-z0-9]+', '-', norm(t['name'])).strip('-')
            t['place'] = {'id': pid, 'name': (t['place'] or {}).get('name') or t['name'], 'lat': tr['high'][0], 'lon': tr['high'][1],
                          'precision': 'place', 'source': 'GPS track (high point)', 'official': None, 'point': 'destination'}
    for t in out:                                   # sort longest track first (shown as the main route)
        t['tracks'].sort(key=lambda x: -(x['km'] or 0))
    for ph in photos:
        t = byid.get(ph.get('trip'))
        if t:                                       # photos without a map position still show in the trip's gallery
            t['photos'].append({k: ph.get(k) for k in ('file', 'thumb', 'w', 'h', 'taken', 'lat', 'lon')})
    for t in out:
        t['photos'].sort(key=lambda x: x['taken'] or '')
    # other trips at a place that got its point from a track share that point
    tp = {t['place']['id']: t['place'] for t in out if t['place'] and t['place'].get('source') == 'GPS track (high point)'}
    for t in out:
        if t['place'] and t['place'].get('lat') is None and t['place']['id'] in tp:
            t['place'] = dict(tp[t['place']['id']])
    json.dump(out, open(f'{D}/site_trips.json', 'w'), separators=(',', ':'), ensure_ascii=False)
    json.dump({'unmatched_reports': [{k: r[k] for k in ('issue', 'page', 'date', 'title')} for r in unmatched],
               'trips_without_place': sorted(missing)}, open(f'{D}/link_report.json', 'w'), indent=1)
    held = [t for t in out if t['status'] == 'held']
    print(f"{len(out)} trips ({len(held)} held); placed {sum(1 for t in held if t['place'] and t['place']['lat'])}/{len(held)} held; "
          f"reports linked {sum(len(t['reports']) for t in out)}/{len(reports)}; unmatched: {[r['title'] for r in unmatched]}", file=sys.stderr)
    if missing:
        print('no place entry for:', sorted(missing), file=sys.stderr)


if __name__ == '__main__':
    main()
