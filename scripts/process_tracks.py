"""Turn the files copied into inbox/ (GPS tracks and photos) into data the website shows.

GPS tracks (.gpx)
  - Each track is matched to a trip: a trip held that day whose map point is within MATCH_KM of the track.
    If no placed trip fits but exactly one trip that day has no map point yet, the track is matched to it (and the
    trip is then placed from the track's high point). Anything else is listed in data/tracks_unmatched.json for an
    admin; data/track_overrides.json  {"<track id>": "<trip id>"} assigns a track by hand ("" hides it).
  - For privacy the first and last few hundred metres (config.json "trim_track_m", default 300) are cut off, so
    tracks don't show where someone parked at home or met for a carpool.
  - Saved to data/tracks/<id>.json (simplified) with distance / elevation gain / time in data/tracks_index.json.
Photos (.jpg .png .heic .webp)
  - Date taken and GPS are read from the photo. A photo taken during a matched track (30 min slack) belongs to that
    trip; it's placed by its own GPS, or along the track by the time it was taken. Unmatched photos aren't shown.
  - Web-size copy + thumbnail in photos/<year>/ with all metadata stripped.
All stored tracks are re-matched on every run, so schedule or map-point changes are picked up.
Run from the repository root:  python scripts/process_tracks.py
"""
import datetime as dt, hashlib, io, json, math, os, sys
import xml.etree.ElementTree as ET
from zoneinfo import ZoneInfo
import numpy as np
from PIL import Image, ImageOps

try:
    import pillow_heif
    pillow_heif.register_heif_opener()
except ImportError:
    pillow_heif = None

D, INBOX, PHOTOS = 'data', 'inbox', 'photos'
TZ = ZoneInfo('America/Vancouver')
MATCH_KM = 3.0
SLACK = dt.timedelta(minutes=30)


def load(p, d):
    return json.load(open(p)) if os.path.exists(p) else d


def save(p, o, pretty=True):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    json.dump(o, open(p, 'w'), indent=1 if pretty else None, separators=None if pretty else (',', ':'), ensure_ascii=False)


# ------------------------------------------------------------------ geometry
def xy(lon, lat, lat0=49.5):
    k = 111320.0
    return np.c_[np.asarray(lon, float) * k * math.cos(math.radians(lat0)), np.asarray(lat, float) * k]


def rdp(p, tol):
    keep = np.zeros(len(p), bool); keep[0] = keep[-1] = True
    st = [(0, len(p) - 1)]
    while st:
        a, b = st.pop()
        if b <= a + 1:
            continue
        s, e = p[a], p[b]; v = e - s; L = math.hypot(*v); q = p[a + 1:b] - s
        d = np.hypot(*q.T) if L == 0 else np.abs(v[0] * q[:, 1] - v[1] * q[:, 0]) / L
        i = int(np.argmax(d))
        if d[i] > tol:
            keep[a + 1 + i] = True; st += [(a, a + 1 + i), (a + 1 + i, b)]
    return np.where(keep)[0]


# ------------------------------------------------------------------ GPX
def parse_time(s):
    if not s:
        return None
    s = s.strip().replace('Z', '+00:00')
    try:
        t = dt.datetime.fromisoformat(s)
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=dt.timezone.utc)


def read_gpx(raw):
    root = ET.fromstring(raw)
    ns = root.tag.split('}')[0] + '}' if root.tag.startswith('{') else ''
    name = root.findtext(f'.//{ns}trk/{ns}name') or root.findtext(f'.//{ns}metadata/{ns}name') or ''
    pts = []
    for tag in ('trkpt', 'rtept'):
        for p in root.iter(f'{ns}{tag}'):
            ele = p.findtext(f'{ns}ele')
            pts.append((float(p.get('lon')), float(p.get('lat')), float(ele) if ele else None, parse_time(p.findtext(f'{ns}time'))))
        if pts:
            break
    return name.strip(), pts


def track_stats(pts):
    lon = [p[0] for p in pts]; lat = [p[1] for p in pts]
    P = xy(lon, lat)
    seg = np.hypot(*np.diff(P, axis=0).T)
    km = float(seg.sum() / 1000)
    ele = [p[2] for p in pts]
    gain, hi = None, None
    if all(e is not None for e in ele):
        e = np.array(ele); sm = np.convolve(np.pad(e, 2, mode='edge'), np.ones(5) / 5, mode='valid') if len(e) > 10 else e
        gain = 0.0; ref = sm[0]
        for v in sm[1:]:                       # count climbs only once they exceed 5 m (GPS noise)
            if v - ref > 5:
                gain += v - ref; ref = v
            elif v < ref:
                ref = v
        i = int(np.argmax(e)); hi = [round(lat[i], 5), round(lon[i], 5), round(float(e[i]))]
    else:                                     # no elevation: use the point farthest from the start
        i = int(np.argmax(np.hypot(*(P - P[0]).T))); hi = [round(lat[i], 5), round(lon[i], 5), None]
    times = [p[3] for p in pts if p[3]]
    start, end = (min(times), max(times)) if times else (None, None)
    return {'km': round(km, 2), 'gain_m': round(gain) if gain is not None else None, 'high': hi,
            'start': start.isoformat() if start else None, 'end': end.isoformat() if end else None,
            'hours': round((end - start).total_seconds() / 3600, 1) if start else None,
            'date': start.astimezone(TZ).date().isoformat() if start else None}


def trimmed(pts, trim_m):
    P = xy([p[0] for p in pts], [p[1] for p in pts])
    cum = np.r_[0, np.cumsum(np.hypot(*np.diff(P, axis=0).T))]
    if cum[-1] < 3 * trim_m:                   # very short track: trim less
        trim_m = cum[-1] / 6
    keep = np.where((cum >= trim_m) & (cum <= cum[-1] - trim_m))[0]
    return [pts[i] for i in keep] if len(keep) >= 2 else pts


# ------------------------------------------------------------------ photos
def ratio(v):
    try:
        return float(v)
    except TypeError:
        return v[0] / v[1]


def photo_meta(img):
    ex = img.getexif()
    when = None
    sub = ex.get_ifd(0x8769) if ex else {}
    s = sub.get(36867) or sub.get(36868) or ex.get(306)
    if s:
        try:
            when = dt.datetime.strptime(str(s).strip()[:19], '%Y:%m:%d %H:%M:%S')
            off = sub.get(36881) or sub.get(36880)
            if off and len(str(off)) >= 6:
                sign = -1 if str(off)[0] == '-' else 1
                hh, mm = str(off)[1:].split(':')[:2]
                when = when.replace(tzinfo=dt.timezone(sign * dt.timedelta(hours=int(hh), minutes=int(mm))))
            else:
                when = when.replace(tzinfo=TZ)
        except ValueError:
            when = None
    pos = None
    gps = ex.get_ifd(0x8825) if ex else {}
    if gps and 2 in gps and 4 in gps:
        try:
            la = sum(ratio(x) / 60 ** i for i, x in enumerate(gps[2])) * (-1 if gps.get(1) == 'S' else 1)
            lo = sum(ratio(x) / 60 ** i for i, x in enumerate(gps[4])) * (-1 if gps.get(3) == 'W' else 1)
            if abs(la) > 0.01 and abs(lo) > 0.01:
                pos = (round(lo, 6), round(la, 6))
        except Exception:
            pos = None
    return when, pos


def web_copies(img, folder, stem):
    os.makedirs(folder, exist_ok=True)
    img = ImageOps.exif_transpose(img).convert('RGB')
    full = img.copy(); full.thumbnail((1600, 1600)); fp = f'{folder}/{stem}.jpg'; full.save(fp, 'JPEG', quality=82, optimize=True)
    th = img.copy(); th.thumbnail((360, 360)); tp = f'{folder}/{stem}_t.jpg'; th.save(tp, 'JPEG', quality=78, optimize=True)
    return fp, tp, full.size


# ------------------------------------------------------------------ matching
def match_track(tr, trips, overrides):
    if tr['id'] in overrides:
        return (overrides[tr['id']] or None), 'set by an admin', None
    if tr.get('hint') and any(t['id'] == tr['hint'] for t in trips):
        return tr['hint'], 'chosen by the member who uploaded it', None
    if not tr.get('date'):
        return None, 'no timestamps in the track', None
    c = np.array(load(f"{D}/tracks/{tr['id']}.json", {}).get('coords') or [[0, 0]])
    T = xy(c[:, 0], c[:, 1])
    day = [t for t in trips if t['status'] == 'held' and t['date'] <= tr['date'] <= (t.get('end') or t['date'])]
    if not day:
        return None, 'no trip that day', None
    best = None
    for t in day:
        p = t.get('place')
        if p and p.get('lat') is not None:
            d = float(np.hypot(*(T - xy([p['lon']], [p['lat']])[0]).T).min()) / 1000
            if best is None or d < best[0]:
                best = (d, t)
    if best and best[0] <= MATCH_KM:
        return best[1]['id'], 'date and place', round(best[0], 2)
    unplaced = [t for t in day if not (t.get('place') and t['place'].get('lat') is not None)]
    if len(unplaced) == 1:
        return unplaced[0]['id'], 'date (trip had no map point)', None
    near = f'nearest trip that day is {best[0]:.1f} km away' if best else 'trips that day have no map point'
    return None, near, None


def main():
    cfg = load(f'{D}/config.json', {})
    trim_m = cfg.get('trim_track_m', 300)
    trips = load(f'{D}/site_trips.json', [])          # from link.py (has map points)
    index = load(f'{D}/tracks_index.json', [])
    photos = load(f'{D}/photos_index.json', [])
    overrides = {k: v for k, v in load(f'{D}/track_overrides.json', {}).items() if not k.startswith('_')}
    have = {t['id'] for t in index}; have_ph = {p['id'] for p in photos}
    log, new_photos = [], []
    manifest = load(f'{INBOX}/_manifest.json', {})
    retry = load(f'{D}/drive_retry.json', {})
    files = sorted(os.listdir(INBOX)) if os.path.isdir(INBOX) else []
    up = lambda f: manifest.get(f) if isinstance(manifest.get(f), dict) else {}      # what the member chose on the upload form
    drive_key = lambda f: manifest.get(f) if isinstance(manifest.get(f), str) else None
    for f in files:
        if f.startswith('_') or f == 'failed':
            continue
        path = os.path.join(INBOX, f); raw = open(path, 'rb').read(); h = hashlib.sha1(raw).hexdigest()[:10]
        ext = os.path.splitext(f)[1].lower()
        try:
            if ext == '.gpx':
                if h in have:
                    log.append(f'{f}: already have this track'); os.remove(path); continue
                name, pts = read_gpx(raw)
                if len(pts) < 2:
                    log.append(f'{f}: no track points'); os.remove(path); continue
                stt = track_stats(pts)
                kept = trimmed(pts, trim_m)
                P = xy([p[0] for p in kept], [p[1] for p in kept]); k = rdp(P, 4.0)
                rec = {'id': h, 'coords': [[round(kept[i][0], 5), round(kept[i][1], 5)] for i in k]}
                if all(kept[i][3] for i in k):
                    rec['t'] = [int(kept[i][3].timestamp()) for i in k]
                save(f'{D}/tracks/{h}.json', rec, pretty=False)
                index.append({'id': h, 'name': name, 'file': f.split('_', 1)[-1], **stt, 'hint': up(f).get('trip'), 'by': up(f).get('by')}); have.add(h)
                log.append(f'{f}: track {stt["date"]} {stt["km"]} km')
            elif ext in ('.jpg', '.jpeg', '.png', '.heic', '.heif', '.webp'):
                if h in have_ph:
                    os.remove(path)
                else:
                    new_photos.append((f, path, raw, h))      # handled after the tracks are matched
                continue
            else:
                log.append(f'{f}: not a GPX file or photo (ignored)')
            os.remove(path)
        except Exception as e:
            log.append(f'{f}: could not read ({e})')
            os.makedirs(f'{INBOX}/failed', exist_ok=True); os.replace(path, f'{INBOX}/failed/{f}') if os.path.exists(path) else None
    # ---- (re)match every track to a trip
    unmatched = []
    for tr in index:
        tid, how, dist = match_track(tr, trips, overrides)
        tr['trip'], tr['matched_by'], tr['dist_km'] = tid, how, dist
        if not tid:
            unmatched.append({'track': tr['id'], 'file': tr.get('file'), 'date': tr.get('date'), 'km': tr.get('km'), 'why': how,
                              'high_point': tr.get('high')})
    # ---- photos -> tracks (by time), placed by own GPS or along the track
    spans = []
    for tr in index:
        if tr['trip'] and tr.get('start'):
            spans.append((dt.datetime.fromisoformat(tr['start']) - SLACK, dt.datetime.fromisoformat(tr['end']) + SLACK, tr))
    def span_of(taken):
        w = dt.datetime.fromisoformat(taken)
        return next((tr for a, b, tr in spans if a <= w <= b), None)
    # new photos: only photos taken during a matched track are kept (web copies, metadata stripped). Others are not
    # stored at all; they are fetched again on later runs for 30 days in case their trip's track arrives later.
    for f, path, raw, h in new_photos:
        try:
            img = Image.open(io.BytesIO(raw)); img.load()
            when, pos = photo_meta(img)
        except Exception as e:
            log.append(f'{f}: could not read photo ({e})'); os.remove(path); continue
        hint = up(f).get('trip') if any(t['id'] == up(f).get('trip') for t in trips) else None
        if hint and when:                                # a photo dated well away from the chosen trip is probably a mix-up
            tt = next(t for t in trips if t['id'] == hint); d0 = when.astimezone(TZ).date()
            if not (dt.date.fromisoformat(tt['date']) - dt.timedelta(days=1) <= d0 <= dt.date.fromisoformat(tt.get('end') or tt['date']) + dt.timedelta(days=1)):
                log.append(f'{f}: photo not used (taken {d0}, not on the date of the trip it was uploaded to)'); os.remove(path); continue
        if hint or (when and span_of(when.isoformat())):
            fp, tp, size = web_copies(img, f'{PHOTOS}/{when.year if when else (hint or "x")[:4]}', h)
            photos.append({'id': h, 'file': fp, 'thumb': tp, 'w': size[0], 'h': size[1], 'taken': when.isoformat() if when else None,
                           'gps': [pos[1], pos[0]] if pos else None, 'hint': hint, 'by': up(f).get('by')}); have_ph.add(h)
            log.append(f'{f}: photo {when.date() if when else "(no date)"} added'); retry.pop(drive_key(f) or '', None)
        else:
            why = 'no date in the photo' if not when else f'no matched GPS track at {when:%Y-%m-%d %H:%M}'
            log.append(f'{f}: photo not used yet ({why})')
            key = drive_key(f)
            if key and when:
                retry.setdefault(key, {'first': dt.date.today().isoformat(), 'file': f.split('_', 1)[-1]})
        os.remove(path)
    tripmap = {t['id']: t for t in trips}
    def near_trip(lat, lon, tid):                      # a photo's own GPS is trusted only near the trip (not a phone at home)
        t = tripmap.get(tid); pts = []
        if t and t.get('place') and t['place'].get('lat') is not None:
            pts.append((t['place']['lat'], t['place']['lon']))
        for tr in index:
            if tr.get('trip') == tid and tr.get('high'):
                pts.append(tuple(tr['high'][:2]))
        return any(math.hypot((lat - a) * 111, (lon - b) * 72) < 15 for a, b in pts)
    for p in photos:
        p['trip'] = p['track'] = None; p['lat'] = p['lon'] = None; p.pop('placed_by', None)
        hit = span_of(p['taken']) if p.get('taken') else None
        if p.get('hint') and not (hit and hit['trip'] == p['hint']):
            p['trip'] = p['hint']                      # member chose the trip; shown in its gallery, on the map only if its GPS fits
            if p.get('gps') and near_trip(p['gps'][0], p['gps'][1], p['hint']):
                p['lat'], p['lon'], p['placed_by'] = p['gps'][0], p['gps'][1], 'gps'
            continue
        if not hit:
            continue
        w = dt.datetime.fromisoformat(p['taken'])
        p['trip'], p['track'] = hit['trip'], hit['id']
        if p.get('gps'):
            p['lat'], p['lon'], p['placed_by'] = p['gps'][0], p['gps'][1], 'gps'
        else:
            rec = load(f"{D}/tracks/{hit['id']}.json", {})
            if rec.get('t'):
                ts = np.array(rec['t']); c = np.array(rec['coords']); x = min(max(w.timestamp(), ts[0]), ts[-1])
                p['lon'] = round(float(np.interp(x, ts, c[:, 0])), 6); p['lat'] = round(float(np.interp(x, ts, c[:, 1])), 6); p['placed_by'] = 'time'
    retry = {k: v for k, v in retry.items() if (dt.date.today() - dt.date.fromisoformat(v['first'])).days <= 30}
    save(f'{D}/drive_retry.json', retry)
    if os.path.exists(f'{INBOX}/_manifest.json'):
        os.remove(f'{INBOX}/_manifest.json')
    save(f'{D}/tracks_index.json', index); save(f'{D}/photos_index.json', photos)
    save(f'{D}/tracks_unmatched.json', unmatched)
    print('\n'.join(log) or 'no new files', file=sys.stderr)
    print(f"{len(index)} tracks ({len(unmatched)} unmatched), {len(photos)} photos ({sum(1 for p in photos if p['trip'])} on trips)", file=sys.stderr)


if __name__ == '__main__':
    main()
