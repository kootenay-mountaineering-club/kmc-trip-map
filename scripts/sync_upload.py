"""Collect files members uploaded through the website (Cloudflare upload Worker) into inbox/ for processing.

  python scripts/sync_upload.py            download everything waiting in the upload bucket
  python scripts/sync_upload.py --done     after the results are published: delete those files from the bucket
Settings (GitHub secrets):  UPLOAD_WORKER_URL (e.g. https://kmc-upload.<account>.workers.dev), PICKUP_KEY.
Each file keeps what the member chose on the form (trip, name, note) in inbox/_manifest.json.
"""
import json, os, sys, urllib.parse, urllib.request

INBOX = 'inbox'
URL, KEY = os.environ.get('UPLOAD_WORKER_URL', '').rstrip('/'), os.environ.get('PICKUP_KEY', '')


def call(path, method='GET'):
    req = urllib.request.Request(URL + path, method=method, headers={'Authorization': f'Bearer {KEY}', 'User-Agent': 'kmc-trips'})
    return urllib.request.urlopen(req, timeout=300).read()


def main():
    if not URL or not KEY:
        print('Upload Worker not set up (UPLOAD_WORKER_URL / PICKUP_KEY secrets missing): skipping.', file=sys.stderr); return
    os.makedirs(INBOX, exist_ok=True)
    done_path = os.path.join(INBOX, '_uploaded_keys.json')
    if '--done' in sys.argv:
        keys = json.load(open(done_path)) if os.path.exists(done_path) else []
        for k in keys:
            call('/inbox/file?key=' + urllib.parse.quote(k), 'DELETE')
        print(f'removed {len(keys)} processed upload(s) from the bucket', file=sys.stderr)
        os.remove(done_path) if os.path.exists(done_path) else None
        return
    files = json.loads(call('/inbox'))['files']
    man_path = os.path.join(INBOX, '_manifest.json')
    manifest = json.load(open(man_path)) if os.path.exists(man_path) else {}
    keys = []
    for f in files:
        name = f['key'].split('/')[-1]; batch = f['key'].split('/')[1][-8:]
        local = f'up{batch}_{name}'
        open(os.path.join(INBOX, local), 'wb').write(call('/inbox/file?key=' + urllib.parse.quote(f['key'])))
        m = f.get('meta') or {}
        manifest[local] = {'source': 'upload', 'key': f['key'], 'trip': m.get('trip') or None, 'by': m.get('by') or None, 'note': m.get('note') or None}
        keys.append(f['key'])
    json.dump(manifest, open(man_path, 'w'))
    json.dump(keys, open(done_path, 'w'))
    print(f'{len(files)} uploaded file(s) collected', *(['  ' + f['key'] for f in files]), sep='\n', file=sys.stderr)


if __name__ == '__main__':
    main()
