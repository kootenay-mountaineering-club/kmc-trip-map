/**
 * KMC Trip Map: upload Worker (Cloudflare Workers, free plan).
 *
 * Members upload GPS tracks and photos from the website with the club upload password; nobody needs a GitHub or
 * Google account. Files wait in a Cloudflare R2 bucket until the site's GitHub Action collects them (it is started
 * straight away), processes them, publishes the result and deletes the originals from the bucket.
 * Admins can also save marker positions with the admin password (instead of each having a GitHub token).
 *
 * Settings (Cloudflare dashboard -> the Worker -> Settings -> Variables and Secrets, and Bindings):
 *   INBOX            R2 bucket binding (e.g. bucket "kmc-uploads")
 *   UPLOAD_PASSWORD  secret: the club upload password members type
 *   ADMIN_PASSWORD   secret: password for admins (moving markers); leave unset to turn that off
 *   GITHUB_TOKEN     secret: fine-grained token for the site's repository only, Contents: Read and write
 *   PICKUP_KEY       secret: long random string, also stored as a GitHub secret, so only the Action can collect files
 *   GITHUB_REPO      variable: owner/name of the site's repository, e.g. kmc-org/kmc-trip-map
 *   ALLOWED_ORIGIN   variable: the site's address, e.g. https://kmc-org.github.io  (comma-separate several)
 */
const MAX_FILE_MB = 30, MAX_FILES = 25, MAX_TOTAL_MB = 120;
const OK_EXT = ['gpx', 'jpg', 'jpeg', 'png', 'heic', 'heif', 'webp'];

function cors(env, req) {
  const origin = req.headers.get('Origin') || '';
  const allowed = (env.ALLOWED_ORIGIN || '').split(',').map(s => s.trim()).filter(Boolean);
  const ok = allowed.includes(origin) || allowed.includes('*');
  return { 'Access-Control-Allow-Origin': ok ? origin : (allowed[0] || ''), 'Access-Control-Allow-Methods': 'POST, GET, DELETE, OPTIONS',
           'Access-Control-Allow-Headers': 'Content-Type, Authorization', 'Vary': 'Origin' };
}
const json = (obj, status, h) => new Response(JSON.stringify(obj), { status: status || 200, headers: { 'Content-Type': 'application/json', ...h } });

async function same(a, b) {               // compare secrets without leaking timing
  if (typeof a !== 'string' || typeof b !== 'string' || !b) return false;
  const enc = new TextEncoder();
  const [x, y] = await Promise.all([crypto.subtle.digest('SHA-256', enc.encode(a)), crypto.subtle.digest('SHA-256', enc.encode(b))]);
  const u = new Uint8Array(x), v = new Uint8Array(y); let d = 0;
  for (let i = 0; i < u.length; i++) d |= u[i] ^ v[i];
  return d === 0;
}
const safeName = n => (n || 'file').normalize('NFKD').replace(/[^\w.\- ]+/g, '').replace(/\s+/g, '_').slice(-80) || 'file';
const gh = (env, path, init = {}) => fetch(`https://api.github.com/repos/${env.GITHUB_REPO}${path}`, {
  ...init, headers: { Accept: 'application/vnd.github+json', Authorization: `Bearer ${env.GITHUB_TOKEN}`, 'X-GitHub-Api-Version': '2022-11-28',
                      'User-Agent': 'kmc-upload-worker', ...(init.headers || {}) } });
const b64 = s => btoa(String.fromCharCode(...new TextEncoder().encode(s)));
const unb64 = s => new TextDecoder().decode(Uint8Array.from(atob(s.replace(/\n/g, '')), c => c.charCodeAt(0)));

async function upload(req, env, h) {
  let form;
  try { form = await req.formData(); } catch { return json({ ok: false, error: 'Could not read the upload.' }, 400, h); }
  if (!(await same(form.get('password') || '', env.UPLOAD_PASSWORD))) return json({ ok: false, error: 'Wrong upload password.' }, 403, h);
  const trip = String(form.get('trip') || '').slice(0, 80).replace(/[^\w\-]/g, '');
  const by = String(form.get('name') || '').slice(0, 60), note = String(form.get('note') || '').slice(0, 300);
  const files = form.getAll('files').filter(f => f && typeof f === 'object' && 'arrayBuffer' in f);
  if (!files.length) return json({ ok: false, error: 'No files were attached.' }, 400, h);
  if (files.length > MAX_FILES) return json({ ok: false, error: `Please send at most ${MAX_FILES} files at a time.` }, 400, h);
  let total = 0;
  for (const f of files) {
    const ext = (f.name.split('.').pop() || '').toLowerCase();
    if (!OK_EXT.includes(ext)) return json({ ok: false, error: `${f.name}: only GPX tracks and photos (JPG, PNG, HEIC, WebP) can be added.` }, 400, h);
    if (f.size > MAX_FILE_MB * 1048576) return json({ ok: false, error: `${f.name} is larger than ${MAX_FILE_MB} MB.` }, 400, h);
    total += f.size;
  }
  if (total > MAX_TOTAL_MB * 1048576) return json({ ok: false, error: `That's more than ${MAX_TOTAL_MB} MB in one go; please send fewer photos at a time.` }, 400, h);
  const stamp = new Date().toISOString().replace(/[-:]/g, '').slice(0, 15), batch = `${stamp}-${crypto.randomUUID().slice(0, 8)}`;
  const saved = [];
  for (const f of files) {
    const key = `incoming/${batch}/${safeName(f.name)}`;
    await env.INBOX.put(key, await f.arrayBuffer(), { customMetadata: { trip, by, note, name: f.name.slice(0, 120) } });
    saved.push(f.name);
  }
  // start the site's GitHub Action now (it also runs nightly, so a failure here only delays things)
  let started = false;
  try { started = (await gh(env, '/dispatches', { method: 'POST', body: JSON.stringify({ event_type: 'kmc-upload' }) })).status === 204; } catch {}
  return json({ ok: true, received: saved, started }, 200, h);
}

async function pickup(req, env, h, url) {
  const auth = (req.headers.get('Authorization') || '').replace(/^Bearer\s+/i, '');
  if (!(await same(auth, env.PICKUP_KEY))) return json({ ok: false, error: 'not allowed' }, 403, h);
  if (req.method === 'GET' && url.pathname === '/inbox') {
    const out = []; let cursor;
    do {
      const r = await env.INBOX.list({ prefix: 'incoming/', cursor, include: ['customMetadata'] });
      for (const o of r.objects) out.push({ key: o.key, size: o.size, uploaded: o.uploaded, meta: o.customMetadata || {} });
      cursor = r.truncated ? r.cursor : undefined;
    } while (cursor);
    return json({ ok: true, files: out }, 200, h);
  }
  const key = url.searchParams.get('key') || '';
  if (!key.startsWith('incoming/')) return json({ ok: false, error: 'bad key' }, 400, h);
  if (req.method === 'GET') {
    const o = await env.INBOX.get(key);
    return o ? new Response(o.body, { headers: { 'Content-Type': 'application/octet-stream', ...h } }) : json({ ok: false, error: 'not found' }, 404, h);
  }
  if (req.method === 'DELETE') { await env.INBOX.delete(key); return json({ ok: true }, 200, h); }
  return json({ ok: false }, 405, h);
}

async function savePlace(req, env, h) {
  let body; try { body = await req.json(); } catch { return json({ ok: false, error: 'bad request' }, 400, h); }
  if (!env.ADMIN_PASSWORD || !(await same(body.password || '', env.ADMIN_PASSWORD))) return json({ ok: false, error: 'Wrong admin password.' }, 403, h);
  const pid = String(body.pid || '').replace(/[^\w\-]/g, '').slice(0, 80), e = body.entry || {};
  if (!pid || !(Math.abs(e.lat) <= 90) || !(Math.abs(e.lon) <= 180)) return json({ ok: false, error: 'bad place' }, 400, h);
  const entry = { name: String(e.name || pid).slice(0, 120), lat: +(+e.lat).toFixed(5), lon: +(+e.lon).toFixed(5), point: String(e.point || '').slice(0, 20),
                  aliases: (Array.isArray(e.aliases) ? e.aliases : []).slice(0, 10).map(a => String(a).slice(0, 80)), saved_at: new Date().toISOString() };
  for (let i = 0; i < 3; i++) {
    const r = await gh(env, `/contents/data/places_manual.json?ref=main`);
    let data = {}, sha;
    if (r.ok) { const j = await r.json(); sha = j.sha; data = JSON.parse(unb64(j.content) || '{}'); }
    else if (r.status !== 404) return json({ ok: false, error: `GitHub said ${r.status}` }, 502, h);
    data[pid] = entry;
    const p = await gh(env, '/contents/data/places_manual.json', { method: 'PUT', body: JSON.stringify({
      message: `Place "${entry.name}" on the map`, content: b64(JSON.stringify(data, null, 1) + '\n'), branch: 'main', ...(sha ? { sha } : {}) }) });
    if (p.ok) return json({ ok: true, entry }, 200, h);
    if (p.status !== 409 && p.status !== 422) return json({ ok: false, error: `GitHub said ${p.status}` }, 502, h);
  }
  return json({ ok: false, error: 'GitHub was busy; please try again.' }, 503, h);
}

export default {
  async fetch(req, env) {
    const h = cors(env, req), url = new URL(req.url);
    if (req.method === 'OPTIONS') return new Response(null, { status: 204, headers: { ...h, 'Access-Control-Max-Age': '86400' } });
    try {
      if (req.method === 'POST' && url.pathname === '/check') {
        const b = await req.json().catch(() => ({}));
        return json({ ok: await same(b.password || '', env.UPLOAD_PASSWORD), admin: !!env.ADMIN_PASSWORD && await same(b.password || '', env.ADMIN_PASSWORD) }, 200, h);
      }
      if (req.method === 'POST' && url.pathname === '/upload') return upload(req, env, h);
      if (req.method === 'POST' && url.pathname === '/admin/place') return savePlace(req, env, h);
      if (url.pathname === '/inbox' || url.pathname === '/inbox/file') return pickup(req, env, h, url);
      return json({ ok: true, service: 'KMC trip map uploads' }, 200, h);
    } catch (e) {
      return json({ ok: false, error: 'Something went wrong; please try again.' }, 500, h);
    }
  },
};
