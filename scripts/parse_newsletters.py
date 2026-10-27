"""Find the trip reports in each newsletter PDF listed in data/newsletters.json and write data/reports.json.

A report starts with a heading like  "June 24 - Grays Peak (Steve Miros)"  (date - title (writer)), usually followed
by a participant line ("We were:", "Hike participants:", "The group was:", "Cyclists:" ...). Distance / elevation /
time figures in the text are picked up when they are written plainly ("Elev. Gain: 1,150m", "7.2km").
Needs pdftotext (poppler-utils).   Run from the repository root:  python scripts/parse_newsletters.py
"""
import json, re, subprocess, datetime as dt

M = 'January|February|March|April|May|June|July|August|September|October|November|December'
MFIX = {'Sepember': 'September'}
HEAD = re.compile(rf'^\s*((?:{M}|Sepember))\s+(\d{{1,2}})(?:\s*-\s*((?:{M}|Sepember))?\s*(\d{{1,2}}))?\s*-\s*(.+?)\s*$')
CAMP = re.compile(r'^\s*Camp Report for KMC (First|Second|Third|Fourth) Camp (\d{4})', re.I)
CAMPNO = {'first': 1, 'second': 2, 'third': 3, 'fourth': 4}
PART = re.compile(r'^\s*(?:We were|The group was|Cyclists|Thank you to my accomplices|(?:[A-Za-z]+ )?participants)\s*:\s*(.*)', re.I)


def pages(pdf):
    n = int(re.search(r'Pages:\s+(\d+)', subprocess.run(['pdfinfo', pdf], capture_output=True, text=True).stdout).group(1))
    return [subprocess.run(['pdftotext', '-f', str(p), '-l', str(p), '-layout', pdf, '-'], capture_output=True, text=True).stdout for p in range(1, n + 1)]


def split_names(s):
    s = re.sub(r'\s+', ' ', s).strip().rstrip('.')
    s = re.sub(r'\bfor a great day\b.*', '', s)
    out = []
    for part in re.split(r',\s*|\s+&\s+', s):
        part = part.strip()
        if not part:
            continue
        m = re.match(r'^(\w+) and (\w+) (\w[\w\-]+)$', part)            # "Linda and Paul Cooney"
        if m:
            out += [f'{m.group(1)} {m.group(3)}', f'{m.group(2)} {m.group(3)}']; continue
        for p in re.split(r'\s+and\s+', part):
            p = re.sub(r'^(his|her) (son|daughter|wife|husband|partner|friend) ', '', p.strip())
            p = re.sub(r'\s*\(.*?\)', '', p).strip()
            if p and len(p) < 40:
                out.append(p)
    return out


def num_stats(text):
    st = {}
    m = re.search(r'(?:elev(?:ation)?\.?\s*gain(?:/loss)?|vertical|climbed)\D{0,15}([\d,]{3,5})\s*m\b', text, re.I) or \
        re.search(r'\+?([\d,]{3,5})\s*m\s*(?:of\s*)?(?:climb|vertical|elevation)', text, re.I)
    if m: st['gain_m'] = int(m.group(1).replace(',', ''))
    m = re.search(r'(?:return distance|total distance|distance)\D{0,25}?(\d+(?:\.\d+)?)\s*(?:km|kilomet)', text, re.I)
    m = m or re.search(r'(?:approx\.?\s*|\.\s)(\d+(?:\.\d+)?)\s*km\b', text, re.I)
    if m: st['km'] = float(m.group(1))
    m = re.search(r'(?:total (?:trip )?time)\D{0,5}(\d+(?:\.\d+)?\s*(?:½)?)\s*h', text, re.I)
    if m: st['hours'] = m.group(1).replace(' ', '')
    return st


def main():
    issues = json.load(open('data/newsletters.json'))
    reports = []
    for key, iss in issues.items():
        P = pages(iss['pdf'])
        lines = [(pi + 1, l) for pi, t in enumerate(P) for l in t.split('\n')]
        heads = [i for i, (_, l) in enumerate(lines) if HEAD.match(l) or CAMP.match(l)]
        for k, i in enumerate(heads):
            pg, l = lines[i]
            cm = CAMP.match(l)
            if cm:                       # hiking camp report: participants are listed at the end
                stop = heads[k + 1] if k + 1 < len(heads) else min(len(lines), i + 600)
                body = '\n'.join(x for _, x in lines[i + 1:stop])
                pm = re.search(r'Camp\s+participants:\s*(.+?)(?:\.\s*$|\n\s*\n)', body, re.S | re.M)
                raw = re.sub(r'\s+', ' ', pm.group(1)) if pm else None
                reports.append({'issue': key, 'page': pg, 'date': None, 'end': None, 'camp_no': CAMPNO[cm.group(1).lower()], 'camp_year': int(cm.group(2)),
                                'title': f'KMC {cm.group(1).title()} Camp {cm.group(2)}', 'writer': None,
                                'participants': split_names(raw) if raw else [], 'participants_raw': raw, 'stats': {}, 'words': len(body.split())})
                continue
            m = HEAD.match(l)
            mon, day, mon2, day2, rest = m.groups()
            title = rest; writer = None
            # heading may wrap onto the next line: "... via the Summit Trail at" / "Whitewater (Alison Etter)"
            if '(' not in rest and i + 1 < len(lines) and re.search(r'\)\s*$', lines[i + 1][1]) and not PART.match(lines[i + 1][1]):
                rest = rest + ' ' + lines[i + 1][1].strip()
            mw = re.match(r'^(.*?)\s*\(([^()]*)\)\s*$', rest)
            if mw:
                title, writer = mw.group(1).strip(' -'), mw.group(2).strip()
            mon = MFIX.get(mon, mon); mon2 = MFIX.get(mon2, mon2) if mon2 else mon
            start = dt.datetime.strptime(f'{mon} {day} {iss["year"]}', '%B %d %Y').date()
            end = dt.datetime.strptime(f'{mon2} {day2} {iss["year"]}', '%B %d %Y').date() if day2 else None
            stop = heads[k + 1] if k + 1 < len(heads) else min(len(lines), i + 400)
            body = '\n'.join(x for _, x in lines[i + 1:stop])
            body = re.split(r'\n\s*Camp Report for', body)[0]
            people, raw = [], None
            for j in range(i + 1, min(i + 6, stop)):
                pm = PART.match(lines[j][1])
                if pm:
                    raw = pm.group(1)
                    nxt = lines[j + 1][1].strip() if j + 1 < stop else ''
                    if raw.rstrip().endswith(',') or (nxt and re.match(r'^[A-Z][a-z]+( [A-Z][\w-]+)?[,.]', nxt) and len(nxt) < 90) \
                            or (nxt and re.match(r'^[A-Z][\w-]+\.?$', nxt)):
                        raw += ' ' + nxt
                    raw = re.split(r'\s{3,}|\s\d', raw)[0]
                    people = split_names(raw)
                    break
            reports.append({'issue': key, 'page': pg, 'date': start.isoformat(), 'end': end.isoformat() if end else None,
                            'title': title, 'writer': writer, 'participants': people, 'participants_raw': raw,
                            'stats': num_stats(body), 'words': len(body.split())})
    json.dump(reports, open('data/reports.json', 'w'), indent=1, ensure_ascii=False)
    for r in reports:
        print(r['date'] or 'camp', r['page'], r['title'][:45], '|', r['writer'], '|', len(r['participants']), r['stats'])


if __name__ == '__main__':
    main()
