"""Copy new GPS tracks and photos from the club's shared Google Drive folder into inbox/ for processing.

Members just drop files (GPX from Gaia/Strava/Garmin..., photos) into the shared folder or its subfolders
(a Google Form with a file-upload question saves into a subfolder, which is fine).

Access is through a Google *service account*: share the folder with the service account's email (Viewer is enough).
Settings come from environment variables (GitHub Actions secrets):
  GDRIVE_SERVICE_ACCOUNT  the service account's JSON key (the whole file's text)
  GDRIVE_FOLDER_ID        the folder id: the last part of the folder's address, drive.google.com/drive/folders/<id>
Files already copied are remembered in data/drive_seen.json (by Drive file id + checksum), so each file is fetched once;
a file that is replaced in Drive with a new version is fetched again.

For testing without Google:   python scripts/sync_drive.py --local path/to/folder
Run from the repository root.
"""
import argparse, hashlib, json, os, shutil, sys

DATA, INBOX = 'data', 'inbox'
WANT = ('.gpx', '.jpg', '.jpeg', '.png', '.heic', '.heif', '.webp')
API = os.environ.get('DRIVE_API_BASE', 'https://www.googleapis.com/drive/v3')


def session():
    if os.environ.get('DRIVE_NO_AUTH'):                 # only for tests against a local mock server
        import requests
        return requests.Session()
    from google.oauth2 import service_account
    from google.auth.transport.requests import AuthorizedSession
    info = json.loads(os.environ['GDRIVE_SERVICE_ACCOUNT'])
    creds = service_account.Credentials.from_service_account_info(info, scopes=['https://www.googleapis.com/auth/drive.readonly'])
    return AuthorizedSession(creds)


def list_folder(s, folder, path=''):
    """All files under the folder, including subfolders."""
    out, token = [], None
    while True:
        params = {'q': f"'{folder}' in parents and trashed = false", 'pageSize': 1000, 'supportsAllDrives': 'true',
                  'includeItemsFromAllDrives': 'true', 'fields': 'nextPageToken, files(id, name, mimeType, md5Checksum, size, createdTime, modifiedTime)'}
        if token:
            params['pageToken'] = token
        r = s.get(f'{API}/files', params=params, timeout=60)
        r.raise_for_status()
        j = r.json()
        for f in j.get('files', []):
            if f['mimeType'] == 'application/vnd.google-apps.folder':
                out += list_folder(s, f['id'], path + f['name'] + '/')
            else:
                f['path'] = path + f['name']
                out.append(f)
        token = j.get('nextPageToken')
        if not token:
            return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--local', help='copy from a local folder instead of Google Drive (testing)')
    a = ap.parse_args()
    seen_path = f'{DATA}/drive_seen.json'
    seen = json.load(open(seen_path)) if os.path.exists(seen_path) else {}
    os.makedirs(INBOX, exist_ok=True)
    retry = json.load(open(f'{DATA}/drive_retry.json')) if os.path.exists(f'{DATA}/drive_retry.json') else {}
    man_path = os.path.join(INBOX, '_manifest.json')
    manifest = json.load(open(man_path)) if os.path.exists(man_path) else {}
    new = []
    if a.local:
        for dp, _, fs in os.walk(a.local):
            for n in sorted(fs):
                p = os.path.join(dp, n)
                if not n.lower().endswith(WANT):
                    continue
                key = 'local:' + os.path.relpath(p, a.local)
                md5 = hashlib.md5(open(p, 'rb').read()).hexdigest()
                if seen.get(key, {}).get('md5') == md5 and key not in retry:
                    continue
                shutil.copy(p, os.path.join(INBOX, f'{md5[:8]}_{n}')); manifest[f'{md5[:8]}_{n}'] = key
                seen[key] = {'md5': md5, 'name': n}; new.append(n)
    else:
        if not os.environ.get('GDRIVE_FOLDER_ID') or not (os.environ.get('GDRIVE_SERVICE_ACCOUNT') or os.environ.get('DRIVE_NO_AUTH')):
            print('Drive not set up (GDRIVE_FOLDER_ID / GDRIVE_SERVICE_ACCOUNT secrets missing): skipping.', file=sys.stderr)
            return
        s = session()
        files = list_folder(s, os.environ['GDRIVE_FOLDER_ID'])
        for f in files:
            if not f['name'].lower().endswith(WANT):
                continue
            tag = f.get('md5Checksum') or f.get('modifiedTime')
            if seen.get(f['id'], {}).get('md5') == tag and f['id'] not in retry:    # photos waiting for their track are re-checked
                continue
            r = s.get(f"{API}/files/{f['id']}", params={'alt': 'media', 'supportsAllDrives': 'true'}, timeout=300)
            r.raise_for_status()
            safe = ''.join(c if c.isalnum() or c in '._-' else '_' for c in f['name'])
            with open(os.path.join(INBOX, f"{f['id'][:8]}_{safe}"), 'wb') as fh:
                fh.write(r.content)
            manifest[f"{f['id'][:8]}_{safe}"] = f['id']
            seen[f['id']] = {'md5': tag, 'name': f['path'], 'created': f.get('createdTime')}
            new.append(f['path'])
    json.dump(seen, open(seen_path, 'w'), indent=1)
    json.dump(manifest, open(os.path.join(INBOX, '_manifest.json'), 'w'))
    print(f'{len(new)} new file(s) from the shared folder', *(['  ' + n for n in new]), sep='\n', file=sys.stderr)


if __name__ == '__main__':
    main()
