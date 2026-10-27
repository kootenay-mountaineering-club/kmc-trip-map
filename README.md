# KMC Trip Map (prototype)

Kootenay Mountaineering Club trips on a map, year by year. This is a free static site for GitHub Pages: no server and no database.

## What it shows

- Every trip from the club's schedules, placed on a topographic map:
  - 2015–2024 from the summer-trips archive workbook (`raw/s2015-2024_archive.csv`);
  - 2024 from the public web version;
  - 2025 and 2026 summer planners;
  - the 2025–26 winter planner;
  - all hiking camps since 1974.

  Trips listed in two sources are merged.
- Places visited more than once get a single marker showing the number of trips.
- **Year selector:** All years, 2026, 2025 or 2024.
- **Filters:** trip type, effort (A–E), Parent & Tot, and search. A checkbox shows postponed and cancelled trips as well.
- **Statistics:** trips, places, sign-ups (from the "# on trip" column) and newsletter reports, for the selected year or filter.
- **Newsletter reports:** each report is linked to its trip, citing the issue and page, with the distance, elevation and time when the report gives them. Participant names from reports are parsed but **hidden** (`show_participants: false` in `data/config.json`) until the club decides.
- **Kept off the site:** phone numbers and emails from the schedule are never read into the site's data.

## How the data is built

| Step | Script | Input → output |
|---|---|---|
| 1 | `scripts/import_schedule.py` | The schedules listed in `data/schedules.json` → `data/trips.json`. It works out each trip's status (held / postponed / cancelled), merges multi-day trips that are entered once per day, and cleans up destination names. |
| 2 | `scripts/build_places.py` | `data/place_list.txt` → `data/places.json`. It looks up coordinates in BC Geographical Names (official peaks, lakes, parks, communities) and OpenStreetMap, and caches them in `data/geocache.json`. Anything it can't find goes to `data/places_todo.txt`. |
| 3 | `scripts/parse_newsletters.py` | Newsletter PDFs listed in `data/newsletters.json` → `data/reports.json`. Run this locally, because the PDFs are not stored in the repository. |
| 4 | `scripts/link.py` | Steps 1–3 → `data/site_trips.json`, which is what the website reads. It matches reports to trips by date, plus name or organizer when several trips share a date. Any trips without a place, or reports without a trip, go to `data/link_report.json`. |

The GitHub Action (`.github/workflows/build.yml`) runs steps 1, 2 and 4 on every push and every Monday, so changes to the 2026 published sheet show up on their own. It then publishes the site.

## Yearly upkeep

1. **New season:** add an entry to `data/schedules.json`, one per schedule sheet, with `"season": "summer"` or `"winter"`. The `csv` address can be the sheet's "Publish to web → CSV" link, or, for a sheet shared as "anyone with the link", `https://docs.google.com/spreadsheets/d/<sheet id>/export?format=csv&gid=<tab id>`. Each trip's year comes from its own date, so a winter planner (Nov–Mar) fills two calendar years.
   - The winter planner's extra **ATES** column is shown as "Avalanche terrain: Simple / Challenging / Complex". Winter grades use the winter scale (C = average, D = strenuous; 1 = track skiing … 4 = advanced touring).
   - **Hiking camps** go in `data/extra_trips.json`, with their location in `data/place_list.txt` as `ll:lat,lon`. The camp archive (1974–2022, from the club website's map sheet + grid references) is already in. Year buttons start at `first_year` in `config.json` (2015); older camps show under **All years** with **Hiking camps** (or the Camp chip) selected.
   Hiking camps (not rows in the sheet) go in `data/extra_trips.json`, and their location goes in `data/place_list.txt` as `ll:lat,lon`.
2. **New destinations** show up in `data/places_todo.txt`, or in the Action log as "no place entry for". For each one, add a line to `data/place_list.txt`:
   `Place name | bc:Official Name  (or osm:search text, town:Community, ll:lat,lon) | names used in the schedule`
3. **New newsletter:** add it to `data/newsletters.json`, run `python scripts/parse_newsletters.py` then `python scripts/link.py`, and commit `data/`. Put the issue's link in `url` if members can read it online.

## Placing and moving markers on the website

**Admins** do a one-time sign-in on each device. Click **Admin** at the bottom right of the map, or open the site with `#admin` at the end of the address. Then paste:

- the repository name, e.g. `kmc-org/kmc-trip-map`;
- a GitHub *fine-grained token* for that repository only, with **Contents: Read and write**.

The token stays in that browser only. After that:

- each place panel has **Move this marker**;
- unplaced trips (marked ○ in the List) have **Place it on the map**.

Drag the red pin (or click the map) to the spot, say whether it's the trailhead/parking or the summit/destination, and press **Save**. The point is written to `data/places_manual.json`, which always overrides automatic lookups. The site rebuilds and everyone sees it a minute or two later.

**Members** see **Suggest a better location**, or **Suggest the spot** for unplaced trips. They drop the pin, add an optional note and press **Email suggestion**. Their email app opens with a message to `suggest_email` (set it in `data/config.json`). The message includes a link that opens the site with the suggested pin. An admin who is signed in on that device can check it there and press **Save**. Nothing changes on the map until an admin saves.

## GPS tracks and photos from members (shared Google Drive folder)

Members drop GPX files (from Gaia, Strava, Garmin, CalTopo…) and trip photos into the club's shared Drive folder. No naming rules, and subfolders are fine; a Google Form with a file-upload question that saves into the folder also works. Every night, or when an admin runs the Action by hand, the site:

1. **Copies new files** (`scripts/sync_drive.py`). It remembers what it has already fetched in `data/drive_seen.json`.
2. **Matches each track to a trip** (`scripts/process_tracks.py`):
   - A track matches a trip held that day whose map point is within 3 km of the track.
   - If no placed trip fits, but exactly one trip that day has no map point yet, the track is matched to that trip. The trip then gets its map point from the track's highest point.
   - Tracks that don't match are listed in `data/tracks_unmatched.json`, with the reason (no trip that day, too far from any trip). An admin can assign one in `data/track_overrides.json`.
3. **Trims each track for privacy.** The first and last 300 m are cut off (`trim_track_m` in `config.json`), so tracks don't show anyone's home or carpool spot.
4. **Shows the trip's route** on the map, with distance, elevation gain and time.
5. **Places photos** taken during a matched track on that trip. A photo goes at its own GPS position, or along the track by the time it was taken. Only web-size copies with **all metadata removed** are published.
   - Photos that don't belong to a matched track are **not stored**.
   - They are re-checked nightly for 30 days, in case the trip's GPX is added later.

The original files stay in Drive; only the trimmed tracks and small photo copies go on the site.

### One-time Google setup (about 15 minutes, free)

1. Go to <https://console.cloud.google.com> with the club's Google account. Create a project (e.g. "KMC trip map") and enable the **Google Drive API** for it.
2. Under **IAM & Admin → Service accounts**, create a service account (e.g. `kmc-trip-map`). On its **Keys** tab, choose **Add key → JSON**; a key file downloads.
3. In Google Drive, **share the members' folder with the service account's email** (`…@….iam.gserviceaccount.com`) as **Viewer**.
4. In the GitHub repository, go to **Settings → Secrets and variables → Actions → New repository secret**:
   - `GDRIVE_SERVICE_ACCOUNT`: paste the **whole contents** of the JSON key file.
   - `GDRIVE_FOLDER_ID`: the last part of the folder's web address (`drive.google.com/drive/folders/<this part>`).
5. Put the folder's (or Form's) link in `data/config.json` as `drive_folder_url`. Each place panel then shows "Add your GPS track and photos to the club's shared folder".
6. Go to **Actions → Update trips and publish site → Run workflow** to try it straight away.

Keep the JSON key file private: anyone with it can read that folder. If it leaks, delete the key in Google Cloud and make a new one.

To test without Google: `python scripts/sync_drive.py --local path/to/folder`, then `python scripts/process_tracks.py` and `python scripts/link.py`.

## Uploads from the website (Cloudflare upload Worker)

When `upload_url` is set in `data/config.json`, every past trip shows **＋ Add GPS track / photos**. A member:

1. picks their GPX file and/or photos;
2. optionally adds their name and a note;
3. types the **club upload password**, which their browser remembers.

The files go to a small Cloudflare Worker (`worker/upload-worker.js`). The Worker:

- checks the password and the files: GPX or photos only, up to 30 MB each and 25 files at once;
- puts them in a Cloudflare R2 bucket;
- starts the site's GitHub Action straight away.

The Action collects the files (`scripts/sync_upload.py`), processes them exactly like files from the Drive folder (trimming, metadata removal), publishes, and then deletes the originals from the bucket. The member chose the trip, so there's no guessing. Photos dated more than a day away from that trip are skipped as probable mix-ups. Updates show on the site **a few minutes** after an upload. The GitHub token lives only in Cloudflare and is never sent to a browser.

**Admins** can also sign in with an **admin password** (Admin → Admin password) instead of a GitHub token. Marker moves are then saved through the Worker.

### One-time Cloudflare setup (about 20 minutes, free)

1. Create a free account at <https://dash.cloudflare.com>.
2. **R2 → Create bucket**, named `kmc-uploads`. R2 asks for a card, but stays free within 10 GB, and uploads are deleted after processing.
3. **Workers & Pages → Create → Worker**, named e.g. `kmc-upload`. Choose **Edit code**, replace everything with the contents of `worker/upload-worker.js`, and press **Deploy**. Its address will be like `https://kmc-upload.<your-account>.workers.dev`.
4. In the Worker's **Settings**:
   - **Bindings → Add → R2 bucket**: variable name `INBOX`, bucket `kmc-uploads`.
   - **Variables and Secrets**:
     - `GITHUB_REPO` (text): e.g. `kmc-org/kmc-trip-map`
     - `ALLOWED_ORIGIN` (text): the site's address, e.g. `https://kmc-org.github.io`
     - `UPLOAD_PASSWORD` (secret): the password members will use
     - `ADMIN_PASSWORD` (secret): the password for admins
     - `PICKUP_KEY` (secret): a long random string, e.g. from a password manager
     - `GITHUB_TOKEN` (secret): a GitHub fine-grained token for this repository only, with **Contents: Read and write**
5. In the GitHub repository, go to **Settings → Secrets and variables → Actions** and add:
   - `UPLOAD_WORKER_URL`: the Worker's address;
   - `PICKUP_KEY`: the same random string as in step 4.
6. Put the Worker's address in `data/config.json` as `upload_url`.

**Changing a password** (for example, once a year, or if it leaks) means editing that one secret in Cloudflare; nothing on the site changes. If the GitHub token expires, make a new one and replace `GITHUB_TOKEN`. Uploads keep waiting safely in the bucket until it works again.

`worker/wrangler.toml` is included for anyone who prefers deploying from the command line (`npx wrangler deploy`).

## Places still to place or check (prototype)

- **Not found automatically (10):** Glade Tarn, Lost Lake cabin, The Monks, College Creek peaks, Elephant Mountain, Emerald Lake, Fort Sheppard (bike), Cedar trail to Eagles Nest cabin, Twin Peaks.
- **Found, but worth checking:**
  - Faith/Hope/Charity is placed at Mount Faith, near Paulson.
  - Oasis Lookout is at the hamlet of Oasis.
  - Lyle Lakes is at the Lyle Creek trailhead.
  - Monica Meadows is at the Monica Meadows trail.
  - Davis Creek old growth is at Davis Creek, near Lardeau.
  - Crawford Peninsula and the Castlegar crags are shown at the town (approximate).
- **Map points are the named feature** (a summit or lake), not the trailhead. When a GPS track is uploaded, the point can come from the track instead (planned next).

## Planned next

- **Admin view of unmatched tracks:** an admin page to assign them to trips by clicking, instead of editing `data/track_overrides.json`.
- **Participants:** a decision on names (none, first names, or members-only). Then a "who went" field, filled in from newsletters and organizers.
- **Earlier years:** back-filled from older schedules and newsletters.
- **Winter schedules.**
