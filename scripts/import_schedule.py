"""Read each year's KMC schedule (CSV exported from the published Google Sheet) and write data/trips.json.

- Drops phone/email columns: they are never written to the site.
- Works out a status for each row: held / postponed / cancelled (from words in the destination or notes, or "X" in # on trip).
- Merges multi-day trips entered once per day (same destination + organizer on consecutive days) into one trip.
- Cleans the destination ("Monica Meadows POSTPONED to Sept. 6" -> "Monica Meadows") and gives it a place key
  that data/places.json maps to coordinates.

Run from the repository root:  python scripts/import_schedule.py
Each year is listed in data/schedules.json: {"2026": {"csv": "https://...pub?output=csv"}, "2025": {"file": "raw/s2025.csv"}, ...}
"""
import csv, datetime as dt, io, json, os, re, sys, unicodedata, urllib.request

DATA = 'data'


def slug(s):
    s = unicodedata.normalize('NFKD', s).encode('ascii', 'ignore').decode().lower()
    return re.sub(r'[^a-z0-9]+', '-', s).strip('-')


STATUS_WORDS = [
    (re.compile(r'\bCANCELL?ED\b.*', re.I), 'cancelled'),
    (re.compile(r'\bPOSTPONED\b.*', re.I), 'postponed'),
]
CLEAN = [
    r'\bRESCHEDULED\b', r'\breschedule\b', r'\brescheduled\b', r'\(reschedule\)',
    r'\band a repeat on June \d+\b', r'\band return\.?', r'\bsnip ?(/|and) ?saw\.?', r'^\s*Paddle-\s*', r'\s+-\s*$',
]
PT = re.compile(r'\(?\s*parents?\s*(and|&)\s*tots?\s*\)?\s*-?', re.I)


def clean_dest(d):
    d = d.replace('’', "'").replace('–', '-').strip()
    status = None
    for rx, st in STATUS_WORDS:
        if rx.search(d):
            status = status or st
            d = rx.sub('', d)
    pt = bool(PT.search(d))
    d = PT.sub(' ', d)
    for c in CLEAN:
        d = re.sub(c, ' ', d, flags=re.I)
    d = re.sub(r"\((Mother|Father)'s Day\)", '', d)
    d = re.sub(r'\s+', ' ', d).strip(' ,.-')
    return d, status, pt


TYPES = [('snowshoe', 'Snowshoe'), ('scramble', 'Scramble'), ('crag', 'Climb'), ('climb', 'Climb'), ('kayak', 'Paddle'),
         ('paddle', 'Paddle'), ('canoe', 'Paddle'), ('bike', 'Bike'), ('cycl', 'Bike'), ('ski', 'Ski'), ('meeting', 'Meeting'),
         ('hike', 'Hike')]


def norm_type(t, dest):
    s = (t or '').lower()
    for k, v in TYPES:
        if k in s:
            return v
    s = dest.lower()
    for k, v in TYPES:
        if k in s:
            return v
    return 'Other'


def parse_grade(g):
    g = (g or '').strip().upper().replace(' ', '')
    if not g:
        return None
    letters = ''.join(sorted(set(re.findall(r'[A-E]', g)), key='ABCDE'.index))
    digits = sorted(set(re.findall(r'[1-5]', g)))
    return {'raw': g, 'physical': letters or None, 'technical': '/'.join(digits) or None}


def read_rows(spec):
    if spec.get('file'):
        text = open(spec['file'], encoding='utf-8').read()
    else:
        req = urllib.request.Request(spec['csv'], headers={'User-Agent': 'kmc-trips/1.0'})
        text = urllib.request.urlopen(req, timeout=60).read().decode('utf-8')
    R = list(csv.reader(io.StringIO(text)))
    h = next(i for i, r in enumerate(R) if r and r[0].strip() == 'Date')
    cols = [c.strip().lower() for c in R[h]]
    def col(r, *names):
        for n in names:
            for i, c in enumerate(cols):
                if c.startswith(n) and i < len(r):
                    return r[i].strip()
        return ''
    out = []
    for r in R[h + 1:]:
        if not r or not r[0].strip():
            continue
        try:
            d = dt.datetime.strptime(r[0].strip(), '%A, %B %d, %Y').date()
        except ValueError:
            continue
        dest = col(r, 'destination')
        if not dest or dest == '0':
            continue
        out.append({'date': d, 'dest_raw': dest, 'type_raw': col(r, 'type'), 'grade_raw': col(r, 'grade'),
                    'organizer': col(r, 'organizer'), 'notes': col(r, 'notes'), 'n': col(r, '# on trip', '#'),
                    'nm': col(r, 'nm', 'non member')})
    return out


def num(s):
    m = re.match(r'\s*(\d+)', s or '')
    return int(m.group(1)) if m else None


def build(year, rows):
    trips = []
    for r in rows:
        dest, st, pt = clean_dest(r['dest_raw'])
        notes = r['notes']
        st2 = None
        for rx, s in STATUS_WORDS:
            if rx.search(notes):
                st2 = st2 or s
        if re.search(r'postponed to', notes, re.I):
            st2 = 'postponed'
        status = st or st2 or ('not held' if r['n'].strip().upper() == 'X' else 'held')
        days = re.search(r'\((\d) days?\)', dest)
        dest = re.sub(r'\s*\(\d days?\)', '', dest)
        typ = norm_type(r['type_raw'], dest)
        if typ == 'Meeting' or re.search(r'\b(social|pub|agm)\b', dest, re.I):
            continue
        if re.search(r'parent', r['type_raw'] + notes, re.I):
            pt = True
        trips.append({'year': year, 'date': r['date'], 'end': r['date'] + dt.timedelta(days=int(days.group(1)) - 1 if days else 0), 'name': dest, 'name_raw': r['dest_raw'],
                      'type': typ, 'type_raw': r['type_raw'], 'grade': parse_grade(r['grade_raw']),
                      'organizer': r['organizer'] or None, 'notes': re.sub(r'(?i)\s*(cancell?ed|postponed)\b.*', '', notes).strip() or None,
                      'participants_count': num(r['n']), 'non_members': num(r['nm']), 'status': status, 'parent_tot': pt})
    # merge multi-day trips: same place + organizer on consecutive days ("not held" continuation days included)
    trips.sort(key=lambda t: (t['date'], t['name']))
    merged = []
    for t in trips:
        key = (slug(t['name']), t['organizer'])
        prev = next((m for m in reversed(merged) if (slug(m['name']), m['organizer']) == key
                     and (t['date'] - m['end']).days == 1 and m['status'] == 'held'), None)
        if prev and t['status'] in ('held', 'not held'):
            prev['end'] = t['date']
            if t['participants_count'] and prev['participants_count'] and slug(t['name']).startswith('haiseldean'):
                prev['participants_count'] += t['participants_count']   # "repeat on June 22": two groups
            continue
        merged.append(t)
    # postponed/cancelled rows that were then held under the same place later in the year link to that trip
    for t in merged:
        if t['status'] in ('postponed', 'not held'):
            later = [m for m in merged if m is not t and m['status'] == 'held' and slug(m['name'])[:12] == slug(t['name'])[:12] and m['date'] > t['date']]
            if later:
                t['status'] = 'postponed'; t['moved_to'] = later[0]['date'].isoformat()
    out = []
    for t in merged:
        t['id'] = f"{year}-{t['date'].strftime('%m%d')}-{slug(t['name'])[:40]}"
        t['place'] = slug(t['name'])
        t['date'] = t['date'].isoformat(); t['end'] = t['end'].isoformat()
        if t['end'] == t['date']:
            del t['end']
        out.append(t)
    return out


def main():
    specs = json.load(open(f'{DATA}/schedules.json'))
    allt = []
    for year, spec in sorted(specs.items()):
        rows = read_rows(spec)
        t = build(int(year), rows)
        print(year, len(rows), 'rows ->', len(t), 'trips,', sum(x['status'] == 'held' for x in t), 'held', file=sys.stderr)
        allt += t
    try:                                  # trips that aren't schedule rows (hiking camps etc.)
        for e in json.load(open(f'{DATA}/extra_trips.json'))['trips']:
            t = {'year': e['year'], 'date': e['date'], 'end': e.get('end'), 'name': e['name'], 'name_raw': e['name'], 'type': e.get('type', 'Other'),
                 'type_raw': e.get('type'), 'grade': parse_grade(e.get('grade')), 'organizer': e.get('organizer'), 'notes': e.get('notes'),
                 'participants_count': e.get('participants_count'), 'non_members': None, 'status': e.get('status', 'held'), 'parent_tot': False}
            t['id'] = f"{t['year']}-{t['date'][5:7]}{t['date'][8:10]}-{slug(t['name'])[:40]}"
            t['place'] = slug(e.get('place_name', t['name']))
            allt.append(t)
    except FileNotFoundError:
        pass
    ids = {}
    for t in allt:                       # make ids unique
        n = ids.get(t['id'], 0); ids[t['id']] = n + 1
        if n: t['id'] += f'-{n + 1}'
    json.dump(allt, open(f'{DATA}/trips.json', 'w'), indent=0, ensure_ascii=False)


if __name__ == '__main__':
    main()
