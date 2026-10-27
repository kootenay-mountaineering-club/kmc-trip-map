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
    (re.compile(r'\bPO\w{0,2}STPONED\b.*', re.I), 'postponed'),
]
CLEAN = [
    r'\bRESCHEDULED\b', r'\breschedule\b', r'\brescheduled\b', r'\(reschedule\)',
    r'\band a repeat on June \d+\b', r'\band return\.?', r'\bsnip ?(/|and) ?saw\.?', r'^\s*Paddle-\s*', r'\s+-\s*$',
]
PT = re.compile(r'\(?\s*parents?\s*(and|&)\s*tots?\s*\)?\s*-?', re.I)


def clean_dest(d):
    d = d.replace('’', "'").replace('–', '-').strip()
    status = None
    m = re.match(r'(?i)^\s*(cancell?ed|po\w{0,2}stponed)\b[\s:-]*', d)          # "CANCELLED Rossland Range"
    if m:
        status = 'cancelled' if m.group(1).lower().startswith('cancel') else 'postponed'
        d = d[m.end():]
    for rx, st in STATUS_WORDS:
        if rx.search(d):
            status = status or st
            d = rx.sub('', d)
    pt = bool(PT.search(d))
    d = PT.sub(' ', d)
    for c in CLEAN:
        d = re.sub(c, ' ', d, flags=re.I)
    d = re.sub(r"\((Mother|Father)'s Day\)", '', d)
    d = re.sub(r'^\d{1,2}[-/]\d{1,2}(?:[-/]\d{1,2})?\s*-?\s+', '', d)          # "09/7-8 West Bonnington Range"
    d = re.sub(r'^(?:[A-Z][a-z]{2,8}\.? \d{1,2}(?:/\d{1,2})?|Victoria Day|Canada Day|Thanksgiving)\s*:\s*', '', d)   # "Sept 24/25: ...", "Victoria Day: .."
    d = re.sub(r'(?i)\s*-?\s*(art & adventure series|plein air art hike)\s*$', '', d)
    d = re.sub(r'\s+', ' ', d).strip(' ,.-')
    return d, status, pt


TYPES = [('snowshoe', 'Snowshoe'), ('scramble', 'Scramble'), ('crag', 'Climb'), ('climb', 'Climb'), ('kayak', 'Paddle'),
         ('paddle', 'Paddle'), ('canoe', 'Paddle'), ('bike', 'Bike'), ('cycl', 'Bike'), ('ski', 'Ski'), ('meeting', 'Meeting'),
         ('hike', 'Hike'), ('backpack', 'Hike'), ('run', 'Hike'), ('walk', 'Hike')]


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


STOPW = {'mt', 'the', 'and', 'to', 'of', 'via', 'loop', 'trail', 'trails', 'peak', 'peaks', 'mountain', 'mount', 'hike', 'a', 'in', 'lake', 'lakes', 'creek'}


def toks(s):
    return {t[:5] for t in re.sub(r'[^a-z0-9]+', ' ', s.lower()).split() if t not in STOPW and len(t) > 2}


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
        d, end = parse_dates(r[0])
        if not d:
            continue
        if col(r, 'end date'):
            end = parse_dates(col(r, 'end date'))[0] or end
        dest = col(r, 'destination')
        if not dest or dest == '0':
            continue
        ates, org = col(r, 'ates'), col(r, 'organizer')
        if ates and ates.strip().lower() not in ATES and not org:      # a name typed into the ATES column
            org, ates = ates, ''
        out.append({'date': d, 'end': end, 'dest_raw': dest, 'type_raw': col(r, 'type'), 'grade_raw': col(r, 'grade'),
                    'organizer': org, 'notes': col(r, 'notes'), 'n': col(r, '# on trip', '#'),
                    'nm': col(r, 'nm', 'non member'), 'ates': ATES.get(ates.strip().lower())})
    return out


ATES = {'simple': 'Simple', 'challenging': 'Challenging', 'complex': 'Complex', 'n/a': None, 'na': None, '': None}


def parse_dates(s):
    s = s.strip()
    try:
        return dt.datetime.strptime(s, '%A, %B %d, %Y').date(), None
    except ValueError:
        pass
    m = re.match(r'^(\d{1,2})/(\d{1,2})/(\d{2,4})\s*(?:-\s*(\d{1,2})/(\d{1,2})/(\d{2,4}))?$', s)   # 1/10/2026-1/13/26
    if not m:
        return None, None
    y = lambda v: int(v) + (2000 if int(v) < 100 else 0)
    a = dt.date(y(m.group(3)), int(m.group(1)), int(m.group(2)))
    b = dt.date(y(m.group(6)), int(m.group(4)), int(m.group(5))) if m.group(4) else None
    return a, b


def num(s):
    m = re.match(r'\s*(\d+)', s or '')
    return int(m.group(1)) if m else None


def build(season, rows, default_type=None):
    trips = []
    for r in rows:
        dest, st, pt = clean_dest(r['dest_raw'])
        notes = re.sub(r'(?i)^\s*completed\.?\s*$', '', r['notes'])     # archive sheet marks held trips "Completed"
        if season == 'auto':
            season_r = 'winter' if r['date'].month in (11, 12, 1, 2, 3) else 'summer'
        else:
            season_r = season
        if not r['type_raw'] and default_type:
            r['type_raw'] = default_type
        st2 = None                                   # notes like "Cancelled", "POSTPONED", "Tenting overnight (Canceled)", "Rescheduled due to fire"
        if re.search(r'(?i)^\W*cancell?ed|\(cancell?ed\)|for cancell?ed\b', notes) or re.search(r'(?i)^\W*cancel', notes):
            st2 = 'cancelled'
        elif re.search(r'(?i)^\W*(postponed|rescheduled(?! from))|postponed to|postponed due', notes):
            st2 = 'postponed'
        status = st or st2 or ('not held' if r['n'].strip().upper() == 'X' or r['n'].strip() == '0' else 'held')
        days = re.search(r'\((\d) days?\)', dest)
        dest = re.sub(r'\s*\(\d days?\)', '', dest)
        typ = norm_type(r['type_raw'], dest)
        if typ == 'Meeting' or re.search(r'\b(social|pub|agm)\b|end of (summer|winter) schedule|^to be determined$', dest, re.I):
            continue
        if re.search(r'parent', r['type_raw'] + notes, re.I):
            pt = True
        end = r.get('end') or r['date'] + dt.timedelta(days=int(days.group(1)) - 1 if days else 0)
        trips.append({'year': r['date'].year, 'season': season_r, 'ates': r.get('ates'), 'date': r['date'], 'end': end, 'name': dest, 'name_raw': r['dest_raw'],
                      'type': typ, 'type_raw': r['type_raw'], 'grade': parse_grade(r['grade_raw']),
                      'organizer': r['organizer'] or None, 'notes': re.sub(r'(?i)\s*(cancell?ed|postponed)\b.*', '', notes).strip() or None,
                      'participants_count': num(r['n']), 'non_members': num(r['nm']), 'status': status, 'parent_tot': pt})
    # the same trip listed twice in one sheet (same day, same name): keep one, preferring the held entry
    uniq = {}
    for t in trips:
        k = (t['date'], slug(t['name']))
        if k not in uniq or (uniq[k]['status'] != 'held' and t['status'] == 'held'):
            uniq[k] = t
    trips = list(uniq.values())
    # merge multi-day trips: same place + organizer on consecutive days ("not held" continuation days included)
    trips.sort(key=lambda t: (t['date'], t['name']))
    merged = []
    for t in trips:
        if re.match(r'(?i)^day \d+ of\b', t['name']):         # "Day 2 of Intro to Winter Camping" continues the day before
            prev = next((m for m in reversed(merged) if (t['date'] - m['end']).days == 1), None)
            if prev:
                prev['end'] = t['date']; continue
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
        t['id'] = f"{t['date'].year}-{t['date'].strftime('%m%d')}-{slug(t['name'])[:40]}"
        t['place'] = slug(t['name'])
        t['date'] = t['date'].isoformat(); t['end'] = t['end'].isoformat()
        if t['end'] == t['date']:
            del t['end']
        out.append(t)
    return out


def main():
    specs = json.load(open(f'{DATA}/schedules.json'))
    allt = []
    # sources with higher "priority" first; a trip already listed by a higher-priority sheet (same date, similar name)
    # is not added again, but fills in details the other sheet lacked (e.g. organizer)
    for key, spec in sorted(((k, v) for k, v in specs.items() if not k.startswith('_')), key=lambda kv: (-kv[1].get('priority', 1), kv[0])):
        rows = read_rows(spec)
        t = build(spec.get('season', 'summer'), rows, spec.get('default_type'))
        dup = 0
        for x in t:
            same = [y for y in allt if y.get('_src') != key and y['date'] == x['date'] and (toks(x['name']) & toks(y['name']) or slug(x['name'])[:10] == slug(y['name'])[:10])]
            # (only against other sheets: two similar trips on one day in the same sheet are both kept)
            if same:
                dup += 1
                for k in ('organizer', 'notes', 'grade', 'participants_count'):
                    if not same[0].get(k) and x.get(k):
                        same[0][k] = x[k]
                continue
            x['_src'] = key; allt.append(x)
        print(key, len(rows), 'rows ->', len(t), 'trips,', sum(x['status'] == 'held' for x in t), 'held,', dup, 'already listed', file=sys.stderr)
    try:                                  # trips that aren't schedule rows (hiking camps etc.)
        for e in json.load(open(f'{DATA}/extra_trips.json'))['trips']:
            t = {'year': e['year'], 'season': e.get('season', 'camp' if e.get('type') == 'Camp' else 'summer'), 'when_text': e.get('when_text'),
                 'range': e.get('range'), 'date': e['date'], 'end': e.get('end'), 'name': e['name'], 'name_raw': e['name'], 'type': e.get('type', 'Other'),
                 'type_raw': e.get('type'), 'grade': parse_grade(e.get('grade')), 'organizer': e.get('organizer'), 'notes': e.get('notes'),
                 'participants_count': e.get('participants_count'), 'non_members': None, 'status': e.get('status', 'held'), 'parent_tot': False}
            t['id'] = f"{t['year']}-{t['date'][5:7]}{t['date'][8:10]}-{slug(t['name'])[:40]}"
            t['place'] = slug(e.get('place_name', t['name'])); t['place_name'] = e.get('place_name')
            allt.append(t)
    except FileNotFoundError:
        pass
    for t in allt:
        t.pop('_src', None)
    ids = {}
    for t in allt:                       # make ids unique
        n = ids.get(t['id'], 0); ids[t['id']] = n + 1
        if n: t['id'] += f'-{n + 1}'
    json.dump(allt, open(f'{DATA}/trips.json', 'w'), indent=0, ensure_ascii=False)


if __name__ == '__main__':
    main()
