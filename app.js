(async () => {
  const $ = s => document.querySelector(s);
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const getJSON = (u, d) => fetch(u + '?v=' + Date.now()).then(r => r.ok ? r.json() : d).catch(() => d);
  const setHdr = () => document.documentElement.style.setProperty('--hdr', ($('#hdr').offsetHeight + $('#filters').offsetHeight) + 'px');
  const [trips, cfg] = await Promise.all([getJSON('data/site_trips.json', []), getJSON('data/config.json', {})]);
  if (cfg.title) { $('#title').textContent = cfg.title; document.title = cfg.title; }
  const startHash = location.hash;
  for (const t of trips) { t.tracks ||= []; t.photos ||= []; }
  const lsGet = k => { try { return localStorage.getItem(k) || ''; } catch { return ''; } };
  const lsSet = (k, v) => { try { v == null ? localStorage.removeItem(k) : localStorage.setItem(k, v); } catch {} };
  const norm = s => s.toLowerCase().replace(/'/g, '').replace(/\bmount\b|\bmt\b\.?/g, 'mt').replace(/[^a-z0-9]+/g, ' ').trim();
  const slug = s => norm(s).replace(/ /g, '-');
  const UP = (cfg.upload_url || '').replace(/\/$/, '');      // Cloudflare upload Worker (optional)
  const canEdit = () => !!((lsGet('kmc_token') && lsGet('kmc_repo')) || (UP && lsGet('kmc_admin_pw')));
  const today = new Date().toISOString().slice(0, 10);
  // places just moved/placed on this device show right away, until the rebuilt site data catches up
  let pendingPl = {}; try { pendingPl = JSON.parse(lsGet('kmc_places_pending') || '{}'); } catch {}
  function applyPlace(pid, e) {
    const aliases = new Set((e.aliases || []).map(norm));
    for (const t of trips) {
      if ((t.place && t.place.id === pid) || (!t.place && aliases.has(norm(t.name)))) {
        t.place = Object.assign({}, t.place || { id: pid, name: e.name || t.name }, { id: pid, lat: e.lat, lon: e.lon, precision: 'place', source: 'placed by hand', point: e.point, official: null });
      }
    }
  }
  for (const [pid, e] of Object.entries(pendingPl)) {
    const live = trips.find(t => t.place && t.place.id === pid);
    if ((live && Math.abs(live.place.lat - e.lat) < 1e-5 && Math.abs(live.place.lon - e.lon) < 1e-5) || Date.now() - Date.parse(e.saved_at) > 864e5) delete pendingPl[pid];
    else applyPlace(pid, e);
  }
  lsSet('kmc_places_pending', JSON.stringify(pendingPl));

  const MON = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  const fmt = (d, y = true) => { const [Y, M, D] = d.split('-').map(Number); return `${MON[M - 1]} ${D}${y ? ', ' + Y : ''}`; };
  const when = t => t.end ? `${fmt(t.date, false)} – ${fmt(t.end)}` : fmt(t.date);
  const TYPES = { Camp: '#6b3fa0', Hike: '#2f7d4a', Scramble: '#b0522c', Snowshoe: '#3b7fb8', Ski: '#5a55b5', Bike: '#c88a12', Paddle: '#1b8f9e', Climb: '#a23b72', Other: '#777' };
  const PHYS = { A: 'easy', B: 'moderate', C: 'strenuous', D: 'very strenuous', E: 'extended, multi-day' };
  const TECH = { 1: 'hike on trail', 2: 'scramble / off-trail', 3: 'scramble, some exposure', 4: 'climb', 5: 'climb, continual belays' };
  const BIKE = { 1: 'suitable for all bikes', 2: 'hybrid or mountain bike recommended', 3: 'moderate mountain-biking skills' };
  const gradeText = t => {
    const g = t.grade; if (!g) return '';
    const p = (g.physical || '').split('').map(c => PHYS[c]).filter(Boolean).join(' to ');
    const tt = (g.technical || '').split('/').map(n => (t.type === 'Bike' ? BIKE : TECH)[n]).filter(Boolean).join(' to ');
    return [p, tt].filter(Boolean).join('; ');
  };
  const years = [...new Set(trips.map(t => t.year))].sort((a, b) => b - a);

  // ---------------- state (kept in the URL hash so links can be shared)
  const st = { year: 'all', types: new Set(), grade: '', pt: false, gps: false, showAll: false, q: '', view: 'map', place: null, trip: null };
  const readHash = () => {
    const h = new URLSearchParams(location.hash.slice(1));
    st.year = h.get('y') || 'all'; st.place = h.get('p'); st.trip = h.get('t'); st.view = h.has('list') ? 'list' : 'map';
    const sg = (h.get('s') || '').split(',');
    st.sugg = sg.length >= 2 && !isNaN(+sg[0]) && !isNaN(+sg[1]) ? { lat: +sg[0], lon: +sg[1], point: sg[2] || '', note: h.get('n') || '' } : null;
  };
  let writeHash = () => {
    const h = new URLSearchParams();
    if (st.year !== 'all') h.set('y', st.year);
    if (st.view === 'list') h.set('list', '');
    if (st.place) h.set('p', st.place);
    if (st.trip) h.set('t', st.trip);
    history.replaceState(null, '', '#' + h.toString().replace(/list=(&|$)/, 'list$1'));
  };
  readHash();

  const inYear = t => st.year === 'all' || String(t.year) === String(st.year);
  const visible = t => inYear(t) && (st.showAll || t.status === 'held') && (!st.types.size || st.types.has(t.type))
    && (!st.grade || (t.grade && (t.grade.physical || '').includes(st.grade))) && (!st.pt || t.parent_tot) && (!st.gps || t.tracks.length)
    && (!st.q || (t.name + ' ' + (t.organizer || '') + ' ' + (t.place ? t.place.name : '') + ' ' + t.reports.map(r => r.title).join(' ')).toLowerCase().includes(st.q));

  // ---------------- header: years + stats
  function renderYears() {
    $('#years').innerHTML = ['all', ...years].map(y => `<button role="tab" class="${String(y) === String(st.year) ? 'on' : ''}" data-y="${y}">${y === 'all' ? 'All years' : y}</button>`).join('');
    $('#years').querySelectorAll('button').forEach(b => b.onclick = () => { st.year = b.dataset.y; st.place = null; st.trip = null; refresh(); });
  }
  function renderStats() {
    const held = trips.filter(t => visible(t) && t.status === 'held');
    const filtered = st.types.size || st.grade || st.pt || st.gps || st.q;
    const ntr = held.reduce((a, t) => a + t.tracks.length, 0), nph = held.reduce((a, t) => a + t.photos.length, 0);
    const people = held.reduce((a, t) => a + (t.participants_count || 0), 0);
    const counted = held.filter(t => t.participants_count != null).length;
    const reps = held.reduce((a, t) => a + t.reports.length, 0);
    const places = new Set(held.filter(t => t.place && t.place.lat != null).map(t => t.place.id)).size;
    $('#stats').innerHTML = (filtered ? '<span class="muted">Filtered:</span> ' : '') + `<b>${held.length}</b> trips · <b>${places}</b> places` + (counted ? ` · <b>${people.toLocaleString()}</b> sign-ups` : '') +
      (reps ? ` · <b>${reps}</b> newsletter report${reps === 1 ? '' : 's'}` : '') + (ntr ? ` · <b>${ntr}</b> GPS track${ntr === 1 ? '' : 's'}` : '') +
      (nph ? ` · <b>${nph}</b> photo${nph === 1 ? '' : 's'}` : '');
  }
  function renderFilters() {
    const present = [...new Set(trips.filter(inYear).map(t => t.type))];
    const order = Object.keys(TYPES).filter(k => present.includes(k));
    $('#filters').innerHTML = `<div class="chips">${order.map(k => `<button class="chip${st.types.has(k) ? ' on' : ''}" data-type="${k}"><i style="background:${TYPES[k]}"></i>${k}</button>`).join('')}</div>
      <select id="fGrade" aria-label="Effort"><option value="">Any effort</option>${Object.entries(PHYS).map(([k, v]) => `<option value="${k}"${st.grade === k ? ' selected' : ''}>${k}: ${v}</option>`).join('')}</select>
      <label class="tick"><input type="checkbox" id="fPT"${st.pt ? ' checked' : ''}> Parent &amp; Tot</label>
      <label class="tick"><input type="checkbox" id="fGps"${st.gps ? ' checked' : ''}> With GPS track</label>
      <label class="tick"><input type="checkbox" id="fAll"${st.showAll ? ' checked' : ''}> Include postponed / cancelled</label>
      <input type="search" id="fQ" placeholder="Search trips, places, organizers" value="${esc(st.q)}">`;
    $('#filters').querySelectorAll('[data-type]').forEach(b => b.onclick = () => { st.types.has(b.dataset.type) ? st.types.delete(b.dataset.type) : st.types.add(b.dataset.type); refresh(); });
    $('#fGrade').onchange = e => { st.grade = e.target.value; refresh(); };
    $('#fPT').onchange = e => { st.pt = e.target.checked; refresh(); };
    $('#fAll').onchange = e => { st.showAll = e.target.checked; refresh(); };
    $('#fGps').onchange = e => { st.gps = e.target.checked; refresh(); };
    const q = $('#fQ'); q.oninput = () => { st.q = q.value.trim().toLowerCase(); refreshData(); };
  }

  // ---------------- map
  const map = L.map('map', { zoomControl: true, preferCanvas: true }).setView([49.45, -117.45], 9);
  const topo = L.tileLayer('https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png', { maxZoom: 17, attribution: '© OpenStreetMap contributors, SRTM | © OpenTopoMap (CC-BY-SA)' });
  const osm = L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', { maxZoom: 19, attribution: '© OpenStreetMap contributors' });
  const sat = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', { maxZoom: 19, attribution: 'Imagery © Esri' });
  topo.addTo(map);
  L.control.layers({ 'Topographic': topo, 'Street map': osm, 'Satellite': sat }, null, { collapsed: true }).addTo(map);
  const markL = L.layerGroup().addTo(map);
  const legend = L.control({ position: 'bottomleft' });
  legend.onAdd = () => { const d = L.DomUtil.create('div', 'legend');
    d.innerHTML = Object.entries(TYPES).map(([k, c]) => `<span><i style="background:${c}"></i>${k}</span>`).join('') +
      `<span class="lg-note"><i class="ring"></i>number = trips there · dashed = approximate spot</span>`;
    return d; };
  legend.addTo(map);
  const adm = L.control({ position: 'bottomright' });
  adm.onAdd = () => { const a = L.DomUtil.create('a', 'admin-link'); a.id = 'adminLink'; a.href = '#admin'; a.textContent = canEdit() ? 'Admin ✓' : 'Admin'; L.DomEvent.disableClickPropagation(a); return a; };
  adm.addTo(map);
  let firstFit = true;

  function groupByPlace(list) {
    const g = new Map();
    for (const t of list) {
      if (!t.place || t.place.lat == null) continue;
      if (!g.has(t.place.id)) g.set(t.place.id, { place: t.place, trips: [] });
      g.get(t.place.id).trips.push(t);
    }
    return [...g.values()];
  }
  function renderMap(list) {
    markL.clearLayers();
    const groups = groupByPlace(list);
    for (const g of groups) {
      const n = g.trips.length, last = g.trips.slice().sort((a, b) => b.date.localeCompare(a.date))[0];
      const types = [...new Set(g.trips.map(t => t.type))];
      const col = TYPES[last.type] || TYPES.Other;
      const approx = g.place.precision === 'town';
      const size = Math.min(34, 18 + Math.sqrt(n) * 5);
      const rep = g.trips.some(t => t.reports.length);
      const icon = L.divIcon({ className: '', iconSize: [size, size], html:
        `<div class="pm${approx ? ' approx' : ''}${st.place === g.place.id ? ' sel' : ''}" style="--c:${col};width:${size}px;height:${size}px">${n > 1 ? n : ''}${rep ? '<b class="rep" title="Newsletter report">✎</b>' : ''}</div>` });
      L.marker([g.place.lat, g.place.lon], { icon, title: g.place.name, riseOnHover: true })
        .bindTooltip(`<b>${esc(g.place.name)}</b><br>${n} trip${n > 1 ? 's' : ''} · ${types.join(', ')}${g.trips.some(t => t.tracks.length) ? ' · GPS track' : ''}<br>last: ${when(last)}`, { direction: 'top', offset: [0, -size / 2] })
        .on('click', () => openPlace(g.place.id)).addTo(markL);
    }
    if (firstFit && groups.length) {
      firstFit = false;
      const b = L.latLngBounds(groups.filter(g => g.place.lat > 48.8 && g.place.lat < 51.3 && g.place.lon > -119.3).map(g => [g.place.lat, g.place.lon]));
      if (b.isValid()) map.fitBounds(b, { padding: [30, 30] });
    }
  }

  // ---------------- GPS tracks and photos for the open place
  const trkL = L.layerGroup().addTo(map), phL = L.layerGroup().addTo(map);
  const trackCache = {};
  async function drawTracks(list, p) {
    trkL.clearLayers(); phL.clearLayers();
    const withT = list.filter(t => t.tracks.length);
    const b = L.latLngBounds([[p.lat, p.lon]]);
    const sel = st.trip;
    for (const t of withT) {
      for (const [i, tr] of t.tracks.entries()) {
        trackCache[tr.id] ||= await getJSON(`data/tracks/${tr.id}.json`, null);
        const rec = trackCache[tr.id]; if (!rec || !rec.coords) continue;
        const ll = rec.coords.map(([x, y]) => [y, x]);
        const main = i === 0, hi = !sel || sel === t.id;
        L.polyline(ll, { color: '#fff', weight: main ? 7 : 4, opacity: hi ? 0.8 : 0.4, interactive: false }).addTo(trkL);
        L.polyline(ll, { color: TYPES[t.type] || TYPES.Other, weight: main ? 4 : 2, opacity: hi ? 0.95 : 0.45, dashArray: main ? null : '5 6' })
          .bindTooltip(`${esc(t.name)} · ${when(t)}${tr.km ? ' · ' + tr.km + ' km' : ''}`, { sticky: true }).addTo(trkL);
        if (hi) ll.forEach(x => b.extend(x));
      }
    }
    for (const t of list) t.photos.forEach((ph, i) => { if (ph.lat == null) return;
      L.marker([ph.lat, ph.lon], { icon: L.divIcon({ className: '', iconSize: [34, 34], html: `<div class="phm" style="background-image:url('${esc(ph.thumb)}')"></div>` }) })
        .on('click', () => openLB(t, i)).addTo(phL); });
    const pad = window.innerWidth > 760 ? { paddingTopLeft: [40, 40], paddingBottomRight: [470, 40] } : { paddingTopLeft: [20, 20], paddingBottomRight: [20, window.innerHeight * 0.62] };
    if (withT.length) map.flyToBounds(b, { ...pad, maxZoom: 14, duration: 0.6 });
    else map.flyTo([p.lat, p.lon], Math.max(map.getZoom(), 11), { duration: 0.6 });
  }
  function wirePhotos(box) {
    box.querySelectorAll('[data-trip][data-i]').forEach(el => el.onclick = () => openLB(trips.find(t => t.id === el.dataset.trip), +el.dataset.i));
  }
  const lb = document.createElement('div'); lb.id = 'lb'; lb.innerHTML = '<button class="x" aria-label="Close">×</button><button class="pv" aria-label="Previous">‹</button><img alt=""><button class="nx" aria-label="Next">›</button><div class="cap"></div>';
  document.body.appendChild(lb);
  let lbT = null, lbI = 0;
  function openLB(t, i) { lbT = t; lbI = i; showLB(); lb.classList.add('open'); }
  function showLB() {
    const p = lbT.photos[lbI];
    lb.querySelector('img').src = p.file; lb.querySelector('img').alt = `Photo from ${lbT.name}`;
    lb.querySelector('.cap').textContent = `${lbT.name} · ${when(lbT)}${p.taken ? ' · ' + p.taken.slice(11, 16) : ''} · ${lbI + 1}/${lbT.photos.length}`;
  }
  lb.querySelector('.x').onclick = () => lb.classList.remove('open');
  lb.querySelector('.pv').onclick = () => { lbI = (lbI - 1 + lbT.photos.length) % lbT.photos.length; showLB(); };
  lb.querySelector('.nx').onclick = () => { lbI = (lbI + 1) % lbT.photos.length; showLB(); };
  addEventListener('keydown', e => { if (!lb.classList.contains('open')) return; if (e.key === 'Escape') lb.classList.remove('open'); if (e.key === 'ArrowLeft') lb.querySelector('.pv').click(); if (e.key === 'ArrowRight') lb.querySelector('.nx').click(); });

  // ---------------- panel (one place, its trips)
  const POINTS = { trailhead: 'trailhead / parking', destination: 'summit / destination', other: 'other spot' };
  const editLinks = (pid, name) => `<div class="editlinks small"><a href="#" data-sugg="${esc(pid)}" data-name="${esc(name)}">Suggest a better location</a>${canEdit() ? ` · <a href="#" data-move="${esc(pid)}" data-name="${esc(name)}">Move this marker</a>` : ''}</div>`;
  function wireEditLinks(box, aliases) {
    box.querySelectorAll('[data-sugg],[data-move]').forEach(a => a.onclick = e => {
      e.preventDefault();
      const pid = a.dataset.sugg || a.dataset.move;
      startPick({ pid, name: a.dataset.name, aliases, mode: a.dataset.move ? 'admin' : 'suggest' });
    });
  }
  const precisionNote = p => !p ? '' : p.precision === 'town'
    ? `Shown at ${esc(p.official || p.name)} (approximate: the exact spot isn't known yet).`
    : /GPS track/.test(p.source || '') ? `Map point: highest point of a member's GPS track (${(+p.lat).toFixed(4)}, ${(+p.lon).toFixed(4)}).`
    : /club|hand/.test(p.source || '') ? `Map point: ${esc(p.source)}${p.point ? ' – ' + esc(POINTS[p.point] || p.point) : ''} (${(+p.lat).toFixed(4)}, ${(+p.lon).toFixed(4)}).`
    : `Map point: ${esc(p.official || p.name)} from ${esc(p.source || '')} (the feature, not necessarily the trailhead).`;
  const trackLine = t => !t.tracks.length ? '' : `<div class="gps small"><span class="gl" style="background:${TYPES[t.type] || TYPES.Other}"></span><b>GPS track</b>: ${[
      t.tracks[0].km ? t.tracks[0].km + ' km' : '', t.tracks[0].gain_m ? '+' + t.tracks[0].gain_m.toLocaleString() + ' m' : '', t.tracks[0].hours ? t.tracks[0].hours + ' h' : ''].filter(Boolean).join(' · ')}${t.tracks.length > 1 ? ` <span class="muted">(${t.tracks.length} tracks)</span>` : ''}</div>`;
  const photoStrip = t => !t.photos.length ? '' : `<div class="thumbs">${t.photos.slice(0, 8).map((p, i) => `<img src="${esc(p.thumb)}" alt="Photo from ${esc(t.name)}" loading="lazy" data-trip="${esc(t.id)}" data-i="${i}">`).join('')}${t.photos.length > 8 ? `<button class="more" data-trip="${esc(t.id)}" data-i="8">+${t.photos.length - 8}</button>` : ''}</div>`;
  function tripCard(t) {
    const g = gradeText(t);
    const status = t.status === 'held' ? '' : `<span class="chip st-${t.status.replace(' ', '-')}">${esc(t.status)}${t.moved_to ? ' → ' + fmt(t.moved_to) : ''}</span>`;
    const reps = t.reports.map(r => {
      const where = `${esc(r.issue_title)}, p.&nbsp;${r.page}`;
      const s = r.stats || {};
      const stats = [s.km ? s.km + ' km' : '', s.gain_m ? '+' + s.gain_m.toLocaleString() + ' m' : '', s.hours ? s.hours + ' h' : ''].filter(Boolean).join(' · ');
      const ppl = r.participants.length ? (cfg.show_participants ? `<div class="ppl"><span class="muted">Participants:</span> ${r.participants.map(esc).join(', ')}</div>`
        : `<div class="muted small">${r.participants.length} participant name${r.participants.length > 1 ? 's' : ''} in the report (hidden).</div>`) : '';
      return `<div class="report"><div>✎ <b>Trip report</b>: “${esc(r.title)}”${r.writer ? ' by ' + esc(r.writer) : ''}</div>
        <div class="muted">${r.url ? `<a href="${esc(r.url)}#page=${r.page}" target="_blank" rel="noopener">${where}</a>` : where}${stats ? ' · ' + stats : ''}</div>${ppl}</div>`;
    }).join('');
    return `<div class="trip${st.trip === t.id ? ' sel' : ''}" id="trip-${esc(t.id)}">
      <div class="trip-h"><span class="dot" style="background:${TYPES[t.type] || TYPES.Other}"></span><b>${when(t)}</b> · ${esc(t.type)}${t.grade ? ` · <span class="grade" title="${esc(g)}">${esc(t.grade.raw)}</span>` : ''} ${status}${t.parent_tot ? '<span class="chip pt">Parent &amp; Tot</span>' : ''}</div>
      <div class="trip-n">${esc(t.name)}</div>
      <div class="muted small">${[t.organizer ? 'Organizer: ' + esc(t.organizer) : '', t.participants_count != null ? `${t.participants_count} on trip${t.non_members ? ` (${t.non_members} non-member${t.non_members > 1 ? 's' : ''})` : ''}` : '', g ? esc(g) : ''].filter(Boolean).join(' · ')}</div>
      ${t.notes && !/^see note$/i.test(t.notes) ? `<div class="muted small">“${esc(t.notes)}”</div>` : ''}${reps}${trackLine(t)}${photoStrip(t)}
      ${UP && t.status === 'held' && t.date <= today ? `<button class="addbtn" data-up="${esc(t.id)}">＋ Add GPS track / photos</button>` : ''}</div>`;
  }
  function openPlace(pid, tripId) {
    st.place = pid; st.trip = tripId || null;
    const all = trips.filter(t => t.place && t.place.id === pid);
    if (!all.length) return;
    const p = all[0].place;
    const shown = all.filter(visible).sort((a, b) => b.date.localeCompare(a.date));
    const other = all.filter(t => !visible(t) && t.status === 'held').length;
    const yrs = [...new Set(all.filter(t => t.status === 'held').map(t => t.year))].sort();
    $('#panelInner').innerHTML = `<div class="kicker">${yrs.length ? 'KMC trips ' + yrs.join(', ') : 'Place'}</div><h2>${esc(p.name)}</h2>
      <div class="muted small">${precisionNote(p)} <a href="https://www.google.com/maps/search/?api=1&query=${p.lat},${p.lon}" target="_blank" rel="noopener">Google Maps</a></div>
      ${editLinks(pid, p.name)}
      ${shown.map(tripCard).join('') || '<div class="muted" style="margin-top:12px">No trips here match the current filters.</div>'}
      ${other ? `<div class="muted small" style="margin-top:10px">${other} more trip${other > 1 ? 's' : ''} here in other years or filtered out. <a href="#" id="showAllYears">Show all years</a></div>` : ''}
      ${cfg.drive_folder_url ? `<div class="addtrack small">Were you on one of these trips? Add your GPS track and photos to the <a href="${esc(cfg.drive_folder_url)}" target="_blank" rel="noopener">club's shared folder</a>. They appear here within a day.</div>` : ''}`;
    wirePhotos($('#panelInner')); wireUploads($('#panelInner'));
    wireEditLinks($('#panelInner'), []);
    const sa = $('#showAllYears'); if (sa) sa.onclick = e => { e.preventDefault(); st.year = 'all'; st.types.clear(); st.grade = ''; st.pt = false; refresh(); openPlace(pid); };
    $('#panel').classList.add('open');
    if (st.view !== 'map') { st.view = 'map'; showView(); }
    drawTracks(shown, p);
    if (tripId) { const el = document.getElementById('trip-' + tripId); if (el) el.scrollIntoView({ block: 'center' }); }
    renderMap(trips.filter(visible));
    writeHash();
  }
  const closePanel = () => { trkL.clearLayers(); phL.clearLayers(); $('#panel').classList.remove('open'); st.place = null; st.trip = null; renderMap(trips.filter(visible)); writeHash(); };
  $('#closePanel').onclick = closePanel;

  // ---------------- list
  let sortKey = 'date', sortDir = -1;
  function renderList(list) {
    const rows = list.slice().sort((a, b) => {
      const v = k => k === 'date' ? a.date.localeCompare(b.date) : k === 'n' ? (a.participants_count || 0) - (b.participants_count || 0) : String(a[k] || '').localeCompare(String(b[k] || ''));
      return v(sortKey) * sortDir || a.date.localeCompare(b.date);
    });
    const unplaced = list.filter(t => !t.place || t.place.lat == null);
    const th = (k, label, cls = '') => `<th class="${cls}" data-k="${k}">${label}${sortKey === k ? (sortDir < 0 ? ' ▾' : ' ▴') : ''}</th>`;
    $('#list').innerHTML = `<div class="list-h"><b>${list.length}</b> trips${unplaced.length ? ` · <span class="muted">${unplaced.length} not on the map yet (marked ○)</span>` : ''}</div>
      <table><thead><tr>${th('date', 'Date')}${th('name', 'Destination')}${th('type', 'Type')}<th>Grade</th>${th('organizer', 'Organizer', 'hide-sm')}${th('n', '#', 'num')}<th title="Newsletter report">✎</th><th title="GPS track">GPS</th></tr></thead><tbody>
      ${rows.map(t => `<tr class="row${t.status !== 'held' ? ' dim' : ''}" data-id="${esc(t.id)}"><td class="nowrap">${when(t)}</td>
        <td>${!t.place || t.place.lat == null ? '<span title="Not placed on the map yet">○ </span>' : ''}${esc(t.name)}${t.status !== 'held' ? ` <span class="chip st-${t.status.replace(' ', '-')}">${esc(t.status)}</span>` : ''}</td>
        <td><span class="dot" style="background:${TYPES[t.type] || TYPES.Other}"></span>${esc(t.type)}</td><td>${t.grade ? esc(t.grade.raw) : ''}</td>
        <td class="hide-sm">${esc(t.organizer || '')}</td><td class="num">${t.participants_count ?? ''}</td><td>${t.reports.length ? '✎' : ''}</td><td>${t.tracks.length ? '✓' : ''}${t.photos.length ? ` <span class="muted small">${t.photos.length}📷</span>` : ''}</td></tr>`).join('')}</tbody></table>`;
    $('#list').querySelectorAll('th[data-k]').forEach(h => h.onclick = () => { const k = h.dataset.k; sortDir = sortKey === k ? -sortDir : (k === 'date' || k === 'n' ? -1 : 1); sortKey = k; renderList(list); });
    $('#list').querySelectorAll('tr.row').forEach(r => r.onclick = () => {
      const t = trips.find(x => x.id === r.dataset.id);
      if (t.place && t.place.lat != null) openPlace(t.place.id, t.id);
      else openUnplaced(t);
    });
  }

  function openUnplaced(t) {
    const pid = (t.place && t.place.id) || slug(t.name);
    st.place = null; st.trip = t.id;
    $('#panelInner').innerHTML = `<div class="kicker">Not on the map yet</div><h2>${esc(t.name)}</h2>${tripCard(t)}
      <div class="flag">This destination hasn't been placed on the map yet.
        ${canEdit() ? `<div style="margin-top:8px"><button class="primary" data-move="${esc(pid)}" data-name="${esc(t.place ? t.place.name : t.name)}">Place it on the map</button></div>` : ''}
        <div style="margin-top:6px"><a href="#" data-sugg="${esc(pid)}" data-name="${esc(t.place ? t.place.name : t.name)}">Know where it is? Suggest the spot</a></div></div>`;
    wireEditLinks($('#panelInner'), [norm(t.name)]); wireUploads($('#panelInner'));
    $('#panel').classList.add('open');
    if (st.view !== 'map') { st.view = 'map'; showView(); }
    writeHash();
  }

  // ---------------- placing / moving markers (admins save; everyone else can email a suggestion)
  let pickPin = null;
  const pinIcon = L.divIcon({ className: '', iconSize: [30, 42], iconAnchor: [15, 40], html: '<div class="pin"></div>' });
  function endPick() { document.body.classList.remove('picking'); if (pickPin) { map.removeLayer(pickPin); pickPin = null; } map.off('click', onPickClick); $('#map').classList.remove('picking'); }
  function onPickClick(e) { if (pickPin) { pickPin.setLatLng(e.latlng); updPick(); } }
  let updPick = () => {};
  function startPick(o) {
    endPick();
    const cur = trips.find(t => t.place && t.place.id === o.pid && t.place.lat != null);
    const small = window.innerWidth <= 760;            // on phones the panel covers the lower part of the map
    document.body.classList.add('picking');
    const start = o.at || (cur ? { lat: cur.place.lat, lon: cur.place.lon } : (() => { const sz = map.getSize(); const c = map.containerPointToLatLng([sz.x / 2, small ? sz.y * 0.27 : sz.y / 2]); return { lat: c.lat, lon: c.lng }; })());
    pickPin = L.marker([start.lat, start.lon], { icon: pinIcon, draggable: true, zIndexOffset: 2000 }).addTo(map);
    pickPin.on('drag dragend', () => updPick());
    map.on('click', onPickClick); $('#map').classList.add('picking');
    map.setView([start.lat, start.lon], Math.max(map.getZoom(), cur || o.at ? 13 : map.getZoom()), { animate: false });
    if (small) map.panBy([0, map.getSize().y * 0.23], { animate: false });
    const admin = o.mode === 'admin';
    $('#panelInner').innerHTML = `<div class="kicker">${admin ? (cur ? 'Move marker' : 'Place on the map') : 'Suggest a location'}</div><h2>${esc(o.name)}</h2>
      ${o.review ? `<div class="flag">Suggested by a member${o.review.note ? `: “${esc(o.review.note)}”` : '.'}${admin ? ' Check it, then save.' : ''}</div>` : ''}
      <ol class="small steps"><li>Zoom in on the map, then <b>drag the red pin</b> (or click the map) to the right spot.</li>
        <li>Say what the spot is.</li><li>${admin ? 'Save. The map updates for everyone in a minute or two.' : 'Send the suggestion; a club admin will check it.'}</li></ol>
      <div class="coords" id="pkCoords"></div>
      <label class="small">This point is the
        <select id="pkPoint">${Object.entries(POINTS).map(([k, v]) => `<option value="${k}"${(o.review && o.review.point === k) ? ' selected' : ''}>${v}</option>`).join('')}</select></label>
      ${admin ? '' : `<label class="small" for="pkNote" style="display:block;margin-top:8px">Note (optional): your name, how you know, trailhead details…</label><textarea id="pkNote" rows="3"></textarea>`}
      <div class="actions"><button class="primary" id="pkGo">${admin ? 'Save location' : 'Email suggestion'}</button><button id="pkCancel">Cancel</button></div>
      <div class="status small" id="pkMsg"></div>`;
    $('#panel').classList.add('open');
    updPick = () => { const ll = pickPin.getLatLng(); $('#pkCoords').textContent = `${ll.lat.toFixed(5)}, ${ll.lng.toFixed(5)}`; };
    updPick();
    $('#pkCancel').onclick = () => { endPick(); cur ? openPlace(o.pid) : closePanel(); };
    $('#pkGo').onclick = async () => {
      const ll = pickPin.getLatLng(), point = $('#pkPoint').value;
      const lat = +ll.lat.toFixed(5), lon = +ll.lng.toFixed(5);
      if (!admin) {
        const site = location.origin + location.pathname;
        const tr = trips.find(t => (t.place && t.place.id === o.pid) || o.aliases.includes(norm(t.name)));
        const link = `${site}#${cur ? 'p=' + encodeURIComponent(o.pid) : 't=' + encodeURIComponent(tr ? tr.id : '')}&s=${lat},${lon},${point}&n=${encodeURIComponent(($('#pkNote').value || '').slice(0, 300))}`;
        const body = `Place: ${o.name}\nSuggested location: ${lat}, ${lon} (${POINTS[point]})\nNote: ${$('#pkNote').value || '-'}\n\nOpen this on the map (admins can save it from there):\n${link}\n`;
        location.href = `mailto:${encodeURIComponent(cfg.suggest_email || '')}?subject=${encodeURIComponent('Map location: ' + o.name)}&body=${encodeURIComponent(body)}`;
        $('#pkMsg').innerHTML = `Your email app should open with the suggestion filled in. If it doesn't, copy this and send it to ${esc(cfg.suggest_email || 'a club admin')}:
          <textarea id="pkMail" rows="6" readonly>${esc(body)}</textarea>`;
        return;
      }
      const entry = { name: o.name, lat, lon, point, aliases: o.aliases || [], saved_at: new Date().toISOString() };
      $('#pkMsg').textContent = 'Saving…'; $('#pkGo').disabled = true;
      try {
        await ghSaveManual(o.pid, entry, `Place "${o.name}" on the map`);
        pendingPl[o.pid] = entry; lsSet('kmc_places_pending', JSON.stringify(pendingPl));
        applyPlace(o.pid, entry); endPick(); st.sugg = null;
        refreshData(); openPlace(o.pid);
        const m = document.createElement('div'); m.className = 'status ok small'; m.textContent = 'Saved ✓ Everyone will see it after the site rebuilds (a minute or two).';
        $('#panelInner').prepend(m);
      } catch (e) { $('#pkGo').disabled = false; $('#pkMsg').innerHTML = `<span class="err">Not saved. ${esc(e.message)}</span>`; }
    };
  }
  const b64enc = s => btoa(unescape(encodeURIComponent(s)));
  const b64dec = b => decodeURIComponent(escape(atob(b.replace(/\n/g, ''))));
  async function ghSaveManual(pid, entry, message) {
    if (UP && lsGet('kmc_admin_pw')) {                       // admin password: the upload Worker saves it with its own GitHub token
      const r = await fetch(UP + '/admin/place', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ password: lsGet('kmc_admin_pw'), pid, entry }) });
      const j = await r.json().catch(() => ({}));
      if (!r.ok || !j.ok) throw new Error(j.error || `The upload service said ${r.status}.`);
      return;
    }
    const repo = lsGet('kmc_repo'), H = { Accept: 'application/vnd.github+json', Authorization: `Bearer ${lsGet('kmc_token')}`, 'X-GitHub-Api-Version': '2022-11-28' };
    const url = `https://api.github.com/repos/${repo}/contents/data/places_manual.json`;
    for (let i = 0; i < 3; i++) {
      let sha = null, data = {};
      const r = await fetch(`${url}?ref=main&t=${Date.now()}`, { headers: H, cache: 'no-store' });
      if (r.ok) { const j = await r.json(); sha = j.sha; data = JSON.parse(b64dec(j.content) || '{}'); }
      else if (r.status !== 404) throw new Error(r.status === 401 ? 'GitHub did not accept the saved token (it may have expired). Set it up again under Admin.' : `GitHub said ${r.status}.`);
      data[pid] = entry;
      const body = { message, content: b64enc(JSON.stringify(data, null, 1) + '\n'), branch: 'main' }; if (sha) body.sha = sha;
      const p = await fetch(url, { method: 'PUT', headers: { ...H, 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
      if (p.ok) return;
      if (p.status === 409 || p.status === 422) continue;
      if (p.status === 403 || p.status === 404) throw new Error('The token cannot write to this repository. It needs Contents: Read and write for ' + repo + '.');
      throw new Error(`GitHub said ${p.status}.`);
    }
    throw new Error('GitHub was busy; please try again.');
  }
  // ---------------- members add GPS tracks / photos to a trip (through the upload Worker)
  function wireUploads(box) { box.querySelectorAll('[data-up]').forEach(b => b.onclick = () => openUpload(trips.find(t => t.id === b.dataset.up))); }
  function openUpload(t) {
    const back = () => (t.place && t.place.lat != null ? openPlace(t.place.id, t.id) : openUnplaced(t));
    $('#panelInner').innerHTML = `<div class="kicker">Add to this trip</div><h2>${esc(t.name)}</h2><div class="muted">${when(t)} · ${esc(t.type)}</div>
      <p class="small">Add your <b>GPS track</b> (a .gpx file exported from Gaia, Strava, Garmin, CalTopo…) and/or <b>photos</b>.
        The start and end of tracks are trimmed and photo details (camera, location data) are removed before anything is published.</p>
      <label class="small">Files<input type="file" id="upFiles" multiple accept=".gpx,image/*,.heic,.heif"></label>
      <div id="upList" class="small muted"></div>
      <label class="small">Your name (optional)<input type="text" id="upName" maxlength="60" value="${esc(lsGet('kmc_upload_name'))}"></label>
      <label class="small">Note (optional)<input type="text" id="upNote" maxlength="300" placeholder="e.g. we took the north ridge on the way down"></label>
      <label class="small">Club upload password<input type="password" id="upPw" value="${esc(lsGet('kmc_upload_pw'))}" autocomplete="current-password"></label>
      <div class="actions"><button class="primary" id="upGo">Upload</button><button id="upBack">Back</button></div>
      <div class="bar up" hidden><div id="upBar"></div></div><div class="status small" id="upMsg"></div>`;
    $('#panel').classList.add('open');
    const fi = $('#upFiles');
    fi.onchange = () => { $('#upList').innerHTML = [...fi.files].map(f => `${esc(f.name)} (${(f.size / 1048576).toFixed(1)} MB)`).join('<br>'); };
    $('#upBack').onclick = back;
    $('#upGo').onclick = () => {
      const files = [...fi.files], pw = $('#upPw').value;
      if (!files.length) { $('#upMsg').innerHTML = '<span class="err">Choose a GPX file or some photos first.</span>'; return; }
      if (!pw) { $('#upMsg').innerHTML = '<span class="err">Enter the club upload password.</span>'; return; }
      const fd = new FormData();
      fd.append('password', pw); fd.append('trip', t.id); fd.append('name', $('#upName').value.trim()); fd.append('note', $('#upNote').value.trim());
      files.forEach(f => fd.append('files', f, f.name));
      const xhr = new XMLHttpRequest();
      xhr.open('POST', UP + '/upload');
      $('.bar.up').hidden = false; $('#upGo').disabled = true; $('#upMsg').textContent = 'Uploading…';
      xhr.upload.onprogress = e => { if (e.lengthComputable) $('#upBar').style.width = (100 * e.loaded / e.total).toFixed(0) + '%'; };
      xhr.onload = () => {
        let j = {}; try { j = JSON.parse(xhr.responseText); } catch {}
        $('#upGo').disabled = false;
        if (xhr.status === 200 && j.ok) {
          lsSet('kmc_upload_pw', pw); lsSet('kmc_upload_name', $('#upName').value.trim());
          $('#upMsg').innerHTML = `<span class="ok">Thanks! ${j.received.length} file${j.received.length > 1 ? 's' : ''} received.</span> They'll appear on this trip in a few minutes, once the site has processed and republished them.`;
          fi.value = ''; $('#upList').textContent = '';
        } else {
          if (xhr.status === 403) lsSet('kmc_upload_pw', null);
          $('#upMsg').innerHTML = `<span class="err">Not uploaded. ${esc(j.error || 'The upload service said ' + xhr.status + '.')}</span>`;
        }
      };
      xhr.onerror = () => { $('#upGo').disabled = false; $('#upMsg').innerHTML = '<span class="err">Could not reach the upload service. Check your connection and try again.</span>'; };
      xhr.send(fd);
    };
  }
  // admin sign-in (one time per device): a GitHub fine-grained token with Contents read/write on the site's repository
  function openAdmin() {
    $('#panelInner').innerHTML = `<div class="kicker">Admin</div><h2>Admin sign-in</h2>
      <p class="small">Admins can place and move markers directly. Sign-in is saved only on this device.</p>
      ${UP ? `<label class="small">Admin password<input type="password" id="adPw" value="${esc(lsGet('kmc_admin_pw'))}" autocomplete="current-password"></label>
        <div class="actions"><button class="primary" id="adPwSave">Sign in</button>${lsGet('kmc_admin_pw') ? '<button id="adPwOut">Sign out</button>' : ''}</div><div class="status small" id="adPwMsg"></div>
        <details class="small" style="margin-top:14px"><summary>Or use a GitHub token instead</summary>` : ''}
      <ol class="small steps"><li>On GitHub: Settings → Developer settings → Fine-grained tokens → Generate new token.</li>
        <li>Repository access: <i>Only select repositories</i> → this site's repository. Permissions: <b>Contents: Read and write</b>.</li>
        <li>Paste the token and the repository below.</li></ol>
      <label class="small">Repository (owner/name)<input type="text" id="adRepo" value="${esc(lsGet('kmc_repo') || cfg.repo || '')}" placeholder="kmc-org/kmc-trip-map"></label>
      <label class="small">Token<input type="password" id="adTok" value="${esc(lsGet('kmc_token'))}" placeholder="github_pat_…"></label>
      <div class="actions"><button class="primary" id="adSave">Save on this device</button>${lsGet('kmc_token') ? '<button id="adOut">Sign out</button>' : ''}</div><div class="status small" id="adMsg"></div>${UP ? '</details>' : ''}`;
    $('#panel').classList.add('open');
    if ($('#adPwSave')) $('#adPwSave').onclick = async () => {
      const pw = $('#adPw').value; $('#adPwMsg').textContent = 'Checking…';
      try {
        const j = await (await fetch(UP + '/check', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ password: pw }) })).json();
        if (!j.admin) throw new Error('That is not the admin password.');
        lsSet('kmc_admin_pw', pw); $('#adPwMsg').innerHTML = '<span class="ok">Signed in ✓ You can now place and move markers on this device.</span>';
      } catch (e) { $('#adPwMsg').innerHTML = `<span class="err">${esc(e.message.includes('fetch') ? 'Could not reach the upload service.' : e.message)}</span>`; }
    };
    if ($('#adPwOut')) $('#adPwOut').onclick = () => { lsSet('kmc_admin_pw', null); openAdmin(); };
    $('#adSave').onclick = async () => {
      const repo = $('#adRepo').value.trim().replace(/^https:\/\/github.com\//, '').replace(/\/$/, ''), tok = $('#adTok').value.trim();
      $('#adMsg').textContent = 'Checking…';
      try {
        const r = await fetch(`https://api.github.com/repos/${repo}`, { headers: { Authorization: `Bearer ${tok}`, Accept: 'application/vnd.github+json' } });
        if (!r.ok) throw new Error(r.status === 401 ? 'GitHub did not accept the token.' : r.status === 404 ? 'Repository not found (check the name, and that the token includes it).' : 'GitHub said ' + r.status);
        const j = await r.json();
        if (j.permissions && !j.permissions.push) throw new Error('The token can read but not write. Give it Contents: Read and write.');
        lsSet('kmc_repo', repo); lsSet('kmc_token', tok);
        $('#adMsg').innerHTML = '<span class="ok">Saved ✓ You can now place and move markers on this device.</span>';
      } catch (e) { $('#adMsg').innerHTML = `<span class="err">${esc(e.message)}</span>`; }
    };
    if ($('#adOut')) $('#adOut').onclick = () => { lsSet('kmc_token', null); openAdmin(); };
  }
  $('#adminLink').onclick = e => { e.preventDefault(); openAdmin(); };

  // ---------------- views
  function showView() {
    $('#list').classList.toggle('open', st.view === 'list');
    $('#tabList').classList.toggle('on', st.view === 'list'); $('#tabMap').classList.toggle('on', st.view === 'map');
    if (st.view === 'map') setTimeout(() => map.invalidateSize(), 50);
  }
  $('#tabFilt').onclick = () => { const on = document.body.classList.toggle('showfilters'); $('#tabFilt').setAttribute('aria-expanded', on); $('#tabFilt').classList.toggle('on', on); setHdr(); };
  $('#tabMap').onclick = e => { e.preventDefault(); st.view = 'map'; showView(); writeHash(); };
  $('#tabList').onclick = e => { e.preventDefault(); st.view = 'list'; $('#panel').classList.remove('open'); showView(); writeHash(); };

  function refreshData() {
    const list = trips.filter(visible);
    renderMap(list); renderList(list); renderStats();
    if (st.place && $('#panel').classList.contains('open')) openPlace(st.place, st.trip);
  }
  function refresh() { renderYears(); renderFilters(); refreshData(); writeHash(); setHdr(); }
  refresh(); showView();
  if (st.place) openPlace(st.place, st.trip);
  else if (st.trip) { const t = trips.find(x => x.id === st.trip); if (t) (t.place && t.place.lat != null ? openPlace(t.place.id, t.id) : openUnplaced(t)); }
  if (st.sugg) {                                   // opened from a member's emailed suggestion
    const t = st.trip ? trips.find(x => x.id === st.trip) : trips.find(x => x.place && x.place.id === st.place);
    if (t) startPick({ pid: (t.place && t.place.id) || slug(t.name), name: t.place ? t.place.name : t.name, aliases: t.place && t.place.lat != null ? [] : [norm(t.name)],
      mode: canEdit() ? 'admin' : 'suggest', at: st.sugg, review: st.sugg });
  }
  if (startHash === '#admin') openAdmin();
  addEventListener('resize', setHdr); setHdr();
  let lastHash = location.hash;
  addEventListener('hashchange', () => {           // shared links / back button
    if (location.hash === lastHash) return;
    readHash(); refresh(); showView();
    if (st.place) openPlace(st.place, st.trip); else $('#panel').classList.remove('open');
  });
  const _w = writeHash; writeHash = () => { _w(); lastHash = location.hash; };
})();
