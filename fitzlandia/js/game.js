/* FitzLandia — game.js
   Game state, modes, UI, economy, challenges, particles, save/load, main loop. */
'use strict';

const SAVE_KEY = 'fitzlandia_save_v1';
const LAND_STEP = 6;
const G = {
  money: 600, totalEarned: 0, rides: [], buildings: [], claimed: [], stats: {},
  mode: 'view', sel: null, pending: null, shopType: null, selected: null, pieceSel: null, insertMode: false,
  test: null, time: 0, sound: true, hintShown: {},
  totalStars() { return this.rides.reduce((a, r) => a + (r.open ? r.stars : 0), 0) + this.buildings.reduce((a, b) => a + (b.def.stars || 0), 0); },
  earn(amount, pos, icon) {
    this.money += amount; this.totalEarned += amount;
    if (pos) Particles.floatText(`+$${amount}`, pos, icon);
    Audio_.coin();
  },
  spend(amount) { if (this.money < amount) return false; this.money -= amount; return true; },
};

// ---------- occupancy ----------
function buildingHeightLevels(b) { return b.type === 'ferris' ? 7 : b.type === 'spooky' ? 5 : b.type === 'carousel' ? 4 : b.type === 'tree' ? 2 : b.type === 'flowers' || b.type === 'fountain' ? 1 : 3; }
function occupied(cx, cz, lmin, lmax, excludeRide, excludeIdx) {
  for (const r of G.rides) for (let i = 0; i < r.pieces.length; i++) {
    if (r === excludeRide) continue;
    const p = r.pieces[i]; const def = PIECES[p.type];
    if (!Ride.pieceCells(p).some(([x, z]) => x === cx && z === cz)) continue;
    const pmin = Math.min(p.l0, p.l1), pmax = Math.max(p.l0, p.l1) + (def.hgt || 0);
    if (lmin < pmax + 2 && lmax > pmin - 2) return true;
  }
  for (const b of G.buildings) for (const [x, z] of b.cells()) if (x === cx && z === cz) { if (lmin < buildingHeightLevels(b) + 2) return true; }
  return false;
}
function cellFree(cx, cz) { return inPark(cx, cz) && !occupied(cx, cz, 0, 0, null, -1); }

// ---------- particles ----------
const Particles = {
  mesh: null, items: [], N: 400, floats: [],
  init() {
    const geo = new THREE.SphereGeometry(0.16, 6, 5);
    this.mesh = new THREE.InstancedMesh(geo, new THREE.MeshBasicMaterial({ vertexColors: false }), this.N);
    this.mesh.instanceMatrix.setUsage(THREE.DynamicDrawUsage);
    this.mesh.frustumCulled = false;
    for (let i = 0; i < this.N; i++) { this.items.push({ life: 0, p: new THREE.Vector3(), v: new THREE.Vector3(), c: new THREE.Color(), s: 1 }); this.mesh.setColorAt(i, new THREE.Color(1, 1, 1)); }
    World.scene.add(this.mesh); this.hideAll();
  },
  hideAll() { const m = new THREE.Matrix4().makeScale(0, 0, 0); for (let i = 0; i < this.N; i++) this.mesh.setMatrixAt(i, m); this.mesh.instanceMatrix.needsUpdate = true; },
  emit(pos, count, opts) {
    let n = 0;
    for (let i = 0; i < this.N && n < count; i++) { const it = this.items[i]; if (it.life > 0) continue;
      it.life = opts.life || 1; it.maxLife = it.life; it.p.copy(pos); it.s = opts.size || 1;
      it.v.set((Math.random() - 0.5) * opts.spread, opts.up * (0.4 + Math.random() * 0.8), (Math.random() - 0.5) * opts.spread);
      it.c.set(Array.isArray(opts.color) ? opts.color[(Math.random() * opts.color.length) | 0] : opts.color); this.mesh.setColorAt(i, it.c); n++; }
    if (this.mesh.instanceColor) this.mesh.instanceColor.needsUpdate = true;
  },
  splash(pos) { this.emit(pos, 60, { spread: 9, up: 9, life: 1.1, color: [0x3fb4ff, 0xaee6ff, 0xffffff], size: 1.2 }); },
  confetti(pos) { this.emit(pos, 120, { spread: 14, up: 16, life: 2.2, color: [0xff3d6e, 0xffd11a, 0x2ecc71, 0x1e90ff, 0x9b59b6, 0xff8c1a], size: 0.7 }); },
  fireworks(pos) { for (let k = 0; k < 4; k++) setTimeout(() => this.emit(pos.clone().add(new THREE.Vector3((Math.random() - 0.5) * 20, 12 + Math.random() * 10, (Math.random() - 0.5) * 20)), 60, { spread: 16, up: 4, life: 1.6, color: [0xff3d6e, 0xffd11a, 0xffffff, 0x1e90ff][k], size: 1.3 }), k * 350); Audio_.cheer(); },
  floatText(text, pos, icon) {
    const tex = textTexture((icon ? icon + ' ' : '') + text, { bg: 'rgba(255,255,255,0)', color: '#1b8f3a', size: 72, w: 384, h: 128 });
    const sp = new THREE.Sprite(new THREE.SpriteMaterial({ map: tex, transparent: true, depthTest: false })); sp.scale.set(4.5, 1.5, 1); sp.position.copy(pos); sp.renderOrder = 6;
    World.scene.add(sp); this.floats.push({ sp, life: 1.4 });
  },
  update(dt) {
    const m = new THREE.Matrix4(); let any = false;
    for (let i = 0; i < this.N; i++) { const it = this.items[i]; if (it.life <= 0) continue; any = true;
      it.life -= dt; it.v.y -= 14 * dt; it.p.addScaledVector(it.v, dt); if (it.p.y < 0) { it.p.y = 0; it.v.y *= -0.3; }
      const s = it.life <= 0 ? 0 : it.s * Math.min(1, it.life / it.maxLife * 2);
      m.makeScale(s, s, s).setPosition(it.p); this.mesh.setMatrixAt(i, m); }
    if (any) this.mesh.instanceMatrix.needsUpdate = true;
    for (let i = this.floats.length - 1; i >= 0; i--) { const f = this.floats[i]; f.life -= dt; f.sp.position.y += dt * 2.5; f.sp.material.opacity = Math.min(1, f.life); if (f.life <= 0) { disposeObject(f.sp); this.floats.splice(i, 1); } }
  }
};

// ---------- challenges ----------
function maxStat(fn) { let m = 0; for (const r of G.rides) if (r.open && r.stats) m = Math.max(m, fn(r) || 0); return m; }
const CHALLENGES = [
  { id: 'first', icon: '🎢', title: 'First Ride!', desc: 'Build and test a working roller coaster', reward: 250, check: () => [G.rides.filter(r => r.open && r.type === 'coaster').length, 1] },
  { id: 'candy', icon: '🍭', title: 'Sweet Tooth', desc: 'Build a Candy Store', reward: 100, check: () => [G.buildings.filter(b => b.type === 'candy').length, 1] },
  { id: 'sky', icon: '🏔️', title: 'Sky High', desc: 'Make a ride that reaches height 6', reward: 300, check: () => [maxStat(r => r.stats.maxLevel), 6] },
  { id: 'water', icon: '💦', title: 'Splash Time', desc: 'Build a working water ride', reward: 300, check: () => [G.rides.filter(r => r.open && r.type === 'water').length, 1] },
  { id: 'twisty', icon: '🌀', title: 'Twisty Turny', desc: 'A ride with 6 turns', reward: 250, check: () => [maxStat(r => r.stats.turns), 6] },
  { id: 'speed', icon: '⚡', title: 'Speed Demon', desc: 'Reach speed 18 on a ride', reward: 300, check: () => [Math.floor(maxStat(r => r.stats.maxV)), 18] },
  { id: 'guests20', icon: '🧑‍🤝‍🧑', title: 'Crowd Pleaser', desc: 'Have 20 guests in the park at once', reward: 300, check: () => [G.stats.maxGuests || 0, 20] },
  { id: 'stars3', icon: '⭐', title: 'Three Star Ride', desc: 'Get a 3-star ride', reward: 300, check: () => [maxStat(r => r.stars), 3] },
  { id: 'shops5', icon: '🏪', title: 'Shopping Street', desc: 'Build 5 shops or games', reward: 400, check: () => [G.buildings.filter(b => b.def.earn > 0).length, 5] },
  { id: 'riders50', icon: '🎟️', title: 'Fifty Riders', desc: '50 guests ride your rides', reward: 400, check: () => [G.stats.ridersServed || 0, 50] },
  { id: 'rides3', icon: '🎪', title: 'Triple Thrill', desc: 'Have 3 rides open', reward: 600, check: () => [G.rides.filter(r => r.open).length, 3] },
  { id: 'land', icon: '🌱', title: 'Growing Park', desc: 'Buy more land', reward: 300, check: () => [World.parkCells > 20 ? 1 : 0, 1] },
  { id: 'loop', icon: '➰', title: 'Loop the Loop', desc: 'Build a coaster with a Loop', reward: 500, check: () => [maxStat(r => r.stats.loops), 1] },
  { id: 'bigdrop', icon: '⬇️', title: 'Mega Drop', desc: 'A ride with a drop of 7 levels', reward: 500, check: () => [maxStat(r => r.stats.bigDrop), 7] },
  { id: 'cork', icon: '🌪️', title: 'Corkscrew King', desc: 'A coaster with 2 Corkscrews', reward: 600, check: () => [maxStat(r => r.stats.corks), 2] },
  { id: 'inv4', icon: '🙃', title: 'Upside-Down Madness', desc: 'A coaster with 4 loops or corkscrews', reward: 1500, check: () => [maxStat(r => (r.stats.loops || 0) + (r.stats.corks || 0)), 4] },
  { id: 'ferris', icon: '🎡', title: 'Big Wheel', desc: 'Build a Ferris Wheel', reward: 500, check: () => [G.buildings.filter(b => b.type === 'ferris').length, 1] },
  { id: 'spooky', icon: '👻', title: 'Brave Explorer', desc: 'Walk all the way through the Spooky House', reward: 600, check: () => [G.stats.spookySurvived || 0, 1] },
  { id: 'stars5', icon: '🌟', title: 'Five Star Ride!', desc: 'Get a 5-star ride', reward: 1000, check: () => [maxStat(r => r.stars), 5] },
  { id: 'rich', icon: '💰', title: 'Tycoon', desc: 'Earn $5000 in total', reward: 1000, check: () => [Math.floor(G.totalEarned), 5000] },
  { id: 'riders300', icon: '🎫', title: 'Ride Master', desc: '300 guests ride your rides', reward: 1200, check: () => [G.stats.ridersServed || 0, 300] },
  { id: 'mega', icon: '🏰', title: 'Mega Park', desc: 'Have 6 rides open', reward: 2000, check: () => [G.rides.filter(r => r.open).length, 6] },
  { id: 'stars15', icon: '👑', title: 'Superstar Park', desc: 'Collect 15 stars', reward: 3000, check: () => [G.totalStars(), 15] },
  { id: 'stars30', icon: '🏆', title: 'FitzLandia Legend', desc: 'Collect 30 stars', reward: 5000, check: () => [G.totalStars(), 30] },
];
function checkChallenges() {
  for (const c of CHALLENGES) {
    if (G.claimed.includes(c.id)) continue;
    const [cur, max] = c.check();
    if (cur >= max) { G.claimed.push(c.id); G.money += c.reward; G.totalEarned += c.reward; toast(`🏆 Challenge done: ${c.title}! +$${c.reward}`, 4000, 'gold'); Audio_.fanfare(); Particles.confetti(World.cam.target.clone().setY(8)); save(); }
  }
}

// ---------- UI helpers ----------
const $ = s => document.querySelector(s);
let toastTimer = null;
function toast(msg, ms = 2600, cls = '') { const t = $('#toast'); t.textContent = msg; t.className = 'show ' + cls; clearTimeout(toastTimer); toastTimer = setTimeout(() => t.className = '', ms); }
function setHint(msg) { const h = $('#hint'); if (!msg) { h.hidden = true; return; } h.hidden = false; h.textContent = msg; }
function showModal(html, opts = {}) { const m = $('#modal'); $('#modalBox').innerHTML = html; m.hidden = false; m.dataset.dismiss = opts.dismiss === false ? '0' : '1'; }
function closeModal() { $('#modal').hidden = true; }
function fmtMoney(n) { return '$' + Math.floor(n).toLocaleString(); }
function starStr(n) { return '⭐'.repeat(n) + '☆'.repeat(Math.max(0, 5 - n)); }
function updateTopbar() {
  $('#stMoney').textContent = '💰 ' + fmtMoney(G.money);
  $('#stStars').textContent = '⭐ ' + G.totalStars();
  $('#stGuests').textContent = '🧑 ' + Guests.list.length;
}

// ---------- modes ----------
function setMode(mode, data) {
  if (G.mode === 'test' && mode !== 'test') endTestVisuals();
  if (G.mode === 'walk' && mode !== 'walk') Walk.exit();
  if (mode === 'walk' && G.mode !== 'walk') Walk.enter();
  G.mode = mode; G.selected = null;
  World.grid.visible = (mode === 'placeStation' || mode === 'build' || mode === 'placeShop');
  document.querySelectorAll('#tabs button').forEach(b => b.classList.toggle('active', b.dataset.mode === tabFor(mode)));
  if (mode === 'placeStation') { G.pending = Object.assign({ heading: 1, color: RIDE_COLORS[G.rides.length % RIDE_COLORS.length] }, data); }
  G.pieceSel = null; G.insertMode = false;
  if (mode === 'build') { G.sel = data.ride; if (data.pieceSel != null) G.pieceSel = data.pieceSel; const s = G.sel.station; const c = cellCenter(s.cx, s.cz); focusCamera(c.x, c.z, Math.max(World.cam.dist, 40)); }
  if (mode !== 'build' && mode !== 'test') { if (G.sel && !G.sel.closed && G.sel.pieces.length === 1 && !G.sel.open) { /* keep unbuilt ride */ } }
  ghostClear();
  renderContext();
}
function tabFor(mode) { return { placeStation: G.pending && G.pending.type === 'water' ? 'water' : 'coaster', build: G.sel && G.sel.water ? 'water' : 'coaster', placeShop: 'shops', shops: 'shops', view: 'view', test: 'view', walk: 'walk' }[mode] || 'view'; }

function renderContext() {
  const ctx = $('#context'); let html = '';
  const m = G.mode;
  if (m === 'placeStation') {
    const p = G.pending; const arrow = ['➡️', '⬇️', '⬅️', '⬆️'][p.heading];
    html = `<div class="row"><div class="label">${p.type === 'water' ? '🌊 New Water Ride' : '🎢 New Coaster'}</div>
      ${RIDE_COLORS.map(c => `<button class="swatch ${c === p.color ? 'on' : ''}" data-action="color" data-color="${c}" style="background:#${c.toString(16).padStart(6, '0')}"></button>`).join('')}
      <button class="btn" data-action="rotate">🔄 Direction ${arrow}</button>
      <button class="btn grey" data-action="cancel">✖ Cancel</button></div>`;
  } else if (m === 'build' && G.pieceSel != null) {
    const r = G.sel; const i = G.pieceSel; const p = r.pieces[i]; const d0 = PIECES[p.type];
    html = `<div class="row"><div class="label">✏️ Piece ${i} of ${r.pieces.length - 1}: ${d0.icon} <b>${d0.name}</b> — ${G.insertMode ? 'tap a piece to INSERT it after this one' : 'tap a piece to SWAP it'}</div>
        <button class="btn ${G.insertMode ? 'green' : 'blue'}" data-action="insertMode">${G.insertMode ? '🔁 Swap instead' : '➕ Insert after'}</button>
        <button class="btn grey" data-action="prevPiece" ${i > 1 ? '' : 'disabled'}>◀</button><button class="btn grey" data-action="nextPiece" ${i < r.pieces.length - 1 ? '' : 'disabled'}>▶</button>
        <button class="btn red" data-action="removePiece">➖ Remove</button>
        <button class="btn grey" data-action="deselect">✖ Done</button></div>
      <div class="row pieces">${r.palette.map(t => { const d = PIECES[t]; const cur = !G.insertMode && t === p.type; return `<button class="piece ${cur ? 'on' : ''}" data-action="piece" data-type="${t}"><span class="ic">${d.icon}</span><span class="nm">${d.name}</span><span class="cost">$${d.cost}</span></button>`; }).join('')}</div>
      <div class="row"><div class="label">💡 Changing a piece moves everything after it. Undo if you don't like it.</div><button class="btn grey" data-action="undo">↩️ Undo</button></div>`;
  } else if (m === 'build') {
    const r = G.sel; const c = r.cursor; const closed = r.closed;
    html = `<div class="row pieces">${r.palette.map(t => { const d = PIECES[t]; const ok = !closed && r.canAdd(t, occupied).ok && G.money >= d.cost; return `<button class="piece ${ok ? '' : 'dim'}" data-action="piece" data-type="${t}"><span class="ic">${d.icon}</span><span class="nm">${d.name}</span><span class="cost">$${d.cost}</span></button>`; }).join('')}</div>
      <div class="row">
        <div class="label">${closed ? '✅ Loop complete!' : `📏 ${r.pieces.length} pieces · Height ${c.l}`} · Cost $${r.cost} · <span class="small">tap any track piece to change it</span></div>
        <button class="btn grey" data-action="undo" ${(r.pieces.length > 1 || (r.history && r.history.length)) ? '' : 'disabled'}>↩️ Undo</button>
        <button class="btn blue" data-action="auto" ${closed || r.pieces.length < 2 ? 'disabled' : ''}>🧲 Auto-Finish</button>
        <button class="btn green big" data-action="test" ${closed ? '' : 'disabled'}>🧪 TEST RIDE!</button>
        <button class="btn grey" data-action="done">💾 Later</button>
        <button class="btn red" data-action="deleteRide">🗑️</button>
      </div>`;
  } else if (m === 'shops' || m === 'placeShop') {
    const nextLand = landPrice();
    html = `<div class="row pieces">${SHOP_ORDER.map(t => { const d = SHOPS[t]; const ok = G.money >= d.cost; return `<button class="piece ${G.shopType === t ? 'on' : ''} ${ok ? '' : 'dim'}" data-action="shop" data-type="${t}"><span class="ic">${d.icon}</span><span class="nm">${d.name}</span><span class="cost">$${d.cost}</span></button>`; }).join('')}
      <button class="piece land ${G.money >= nextLand ? '' : 'dim'}" data-action="land" ${World.parkCells >= MAX_PARK ? 'disabled' : ''}><span class="ic">🌱</span><span class="nm">More Land</span><span class="cost">${World.parkCells >= MAX_PARK ? 'MAX' : '$' + nextLand}</span></button></div>
      <div class="row"><div class="label">${G.shopType ? `Tap the grass to place your ${SHOPS[G.shopType].icon} ${SHOPS[G.shopType].name}` : 'Pick something to build, then tap the grass 🌿'}</div>${G.shopType ? '<button class="btn grey" data-action="cancelShop">✖ Cancel</button>' : ''}</div>`;
  } else if (m === 'walk') {
    const n = Walk.near; let mid = '';
    if (Spooky.active) mid = `<div class="label">🏚️ Inside the <b>Spooky House</b>… follow the hallway to the EXIT! 👻</div><button class="btn red" data-action="getOff">🚪 Get me out!</button>`;
    else if (Walk.state === 'waiting') mid = `<div class="label">⏳ Waiting for <b>${Walk.ride.name}</b> to pull in…</div><button class="btn grey" data-action="getOff">✖ Never mind</button>`;
    else if (Walk.state === 'riding') mid = `<div class="label">🙌 Riding <b>${Walk.ride.name}</b>! Drag to look around.</div><button class="btn red" data-action="getOff">🚪 Get off</button>`;
    else if (Walk.state === 'attached') mid = `<div class="label">${Walk.attach.building.def.icon} Riding the <b>${Walk.attach.building.def.name}</b>! Drag to look around.</div><button class="btn red" data-action="getOff">🚪 Get off</button>`;
    else if (n && n.kind === 'ride') mid = n.ride.open ? `<div class="label">${n.ride.water ? '🌊' : '🎢'} <b>${n.ride.name}</b> ${starStr(n.ride.stars)}</div><button class="btn green big" data-action="walkRide">🎟️ RIDE IT!</button>` : `<div class="label">🔧 <b>${n.ride.name}</b> is not open yet</div>`;
    else if (n && n.kind === 'shop') mid = `<div class="label">${n.building.def.icon} <b>${n.building.def.name}</b></div><button class="btn green big" data-action="walkShop">${n.building.def.kind === 'booth' ? '🎯 PLAY!' : '🛍️ BUY!'}</button>`;
    else if (n && n.kind === 'attraction') mid = `<div class="label">${n.building.def.icon} <b>${n.building.def.name}</b></div><button class="btn green big" data-action="walkAttraction">🎟️ RIDE IT!</button>`;
    else mid = `<div class="label">🚶 Walk up to a ride or shop! Joystick = walk · drag = look · (keyboard: WASD + arrows)</div>`;
    html = `<div class="row">${mid}<button class="btn grey" data-action="exitWalk">👀 Stop walking</button></div>`;
  } else if (m === 'test') {
    html = `<div class="row"><div class="label">🧪 Testing <b>${G.test.ride.name}</b>… Speed: <span id="tSpeed">0</span></div>
      <button class="btn blue" data-action="rideCam">🎥 Ride Cam</button><button class="btn red" data-action="stopTest">✖ Stop</button></div>`;
  } else if (m === 'view') {
    const s = G.selected;
    if (s && s.kind === 'ride') {
      const r = s.ride; const st = r.stats || {};
      html = `<div class="row"><div class="label">${r.water ? '🌊' : '🎢'} <b>${r.name}</b> ${r.open ? starStr(r.stars) : '(not finished)'}${r.open ? ` · 🎟️ ${r.ridersServed} riders · 💰 $${Math.floor(r.earned)} earned · ⚡ top speed ${Math.floor(st.maxV || 0)}` : ''}</div>
        ${r.open ? '<button class="btn blue" data-action="rideCamThis">🎥 Ride Cam</button>' : ''}
        <button class="btn blue" data-action="rename">✏️ Name</button>
        <button class="btn green" data-action="edit">🔧 ${r.open ? 'Edit (closes ride)' : 'Keep Building'}</button>
        <button class="btn red" data-action="deleteRide">🗑️ Remove</button></div>`;
    } else if (s && s.kind === 'building') {
      const b = s.building;
      html = `<div class="row"><div class="label">${b.def.icon} <b>${b.def.name}</b>${b.def.earn ? ` · 🧑 ${b.visitors} visitors · 💰 $${b.earned} earned` : ''}</div>
        <button class="btn red" data-action="deleteBuilding">🗑️ Remove (+$${Math.floor(b.def.cost / 2)})</button></div>`;
    } else {
      const open = G.rides.filter(r => r.open).length;
      html = `<div class="row"><div class="label">👀 Watching FitzLandia · ${open} ride${open === 1 ? '' : 's'} open · ${G.buildings.length} buildings · Tap a ride or shop to see it</div>${open ? '<button class="btn blue" data-action="rideCamAny">🎥 Ride Cam</button>' : ''}</div>`;
    }
  }
  ctx.innerHTML = html;
  updateTopbar();
}

// context actions
$('#context').addEventListener('click', e => {
  const b = e.target.closest('[data-action]'); if (!b || b.disabled) return;
  Audio_.resume();
  const a = b.dataset.action;
  if (a === 'color') { G.pending.color = parseInt(b.dataset.color); renderContext(); ghostUpdate(); }
  else if (a === 'rotate') { G.pending.heading = (G.pending.heading + 1) % 4; Audio_.click(); renderContext(); ghostUpdate(); }
  else if (a === 'cancel') setMode('view');
  else if (a === 'piece') { if (G.pieceSel != null) (G.insertMode ? insertPiece(b.dataset.type) : swapPiece(b.dataset.type)); else addPiece(b.dataset.type); }
  else if (a === 'undo') undoChange();
  else if (a === 'insertMode') { G.insertMode = !G.insertMode; renderContext(); }
  else if (a === 'removePiece') removePiece();
  else if (a === 'deselect') selectPiece(null);
  else if (a === 'prevPiece') selectPiece(G.pieceSel - 1);
  else if (a === 'nextPiece') selectPiece(G.pieceSel + 1);
  else if (a === 'auto') doAutoConnect();
  else if (a === 'test') startTest(G.sel);
  else if (a === 'done') { setMode('view'); toast('Saved! Tap the station 🏠 any time to keep building.'); save(); }
  else if (a === 'deleteRide') confirmDeleteRide(G.mode === 'build' ? G.sel : G.selected.ride);
  else if (a === 'shop') { G.shopType = b.dataset.type; setMode('placeShop'); Audio_.click(); }
  else if (a === 'cancelShop') { G.shopType = null; setMode('shops'); }
  else if (a === 'land') buyLand();
  else if (a === 'rideCam') toggleRideCam(G.test.ride.vehicle);
  else if (a === 'rideCamAny') cycleRideCam();
  else if (a === 'rideCamThis') { const r = G.selected.ride; if (r.vehicle) { World.rideCam = { vehicle: r.vehicle }; toast('🎥 Riding ' + r.name + ' — press 🎥 again to stop'); } }
  else if (a === 'stopTest') { failTest(null); setMode('build', { ride: G.test ? G.test.ride : G.sel }); }
  else if (a === 'walkRide') Walk.requestRide(Walk.near.ride);
  else if (a === 'walkShop') Walk.visitShop(Walk.near.building);
  else if (a === 'walkAttraction') Walk.rideAttraction(Walk.near.building);
  else if (a === 'getOff') { if (Spooky.active) Spooky.exit(false); else Walk.unboard(true); }
  else if (a === 'exitWalk') setMode('view');
  else if (a === 'rename') renameRide(G.selected.ride);
  else if (a === 'edit') editRide(G.selected.ride);
  else if (a === 'deleteBuilding') deleteBuilding(G.selected.building);
});
document.querySelectorAll('#tabs button').forEach(btn => btn.addEventListener('click', () => {
  Audio_.resume(); Audio_.click();
  const t = btn.dataset.mode;
  if (G.mode === 'test') { toast('Wait for the test to finish! 🧪'); return; }
  if (t === 'coaster' || t === 'water') {
    const unfinished = G.rides.find(r => !r.open && r.type === t);
    if (G.mode === 'build' && G.sel && G.sel.type === t) return;
    if (unfinished) setMode('build', { ride: unfinished }); else setMode('placeStation', { type: t });
  } else if (t === 'shops') { G.shopType = null; setMode('shops'); }
  else if (t === 'walk') setMode('walk');
  else setMode('view');
}));
$('#btnChallenges').addEventListener('click', () => { Audio_.click(); showChallenges(); });
$('#btnMenu').addEventListener('click', () => { Audio_.click(); showMenu(); });
$('#modal').addEventListener('click', e => { if (e.target.id === 'modal' && $('#modal').dataset.dismiss === '1') closeModal(); });
$('#camIn').addEventListener('click', () => { World.cam.dist *= 0.75; });
$('#camOut').addEventListener('click', () => { World.cam.dist *= 1.33; });
$('#camFind').addEventListener('click', () => { World.rideCam = null; if (G.sel && (G.mode === 'build')) { const c = G.sel.cursor; const p = cellCenter(c.cx, c.cz); focusCamera(p.x, p.z); } else focusCamera(0, 0, 60); });
$('#camRide').addEventListener('click', () => { if (G.test) { toggleRideCam(G.test.ride.vehicle); return; } if (G.mode === 'view' && G.selected && G.selected.kind === 'ride' && G.selected.ride.vehicle && !World.rideCam) { World.rideCam = { vehicle: G.selected.ride.vehicle }; toast('🎥 Riding ' + G.selected.ride.name); return; } cycleRideCam(); });
function toggleRideCam(v) { World.rideCam = World.rideCam && World.rideCam.vehicle === v ? null : { vehicle: v }; }
/** Each press moves the ride cam to the next open ride, then off. */
function cycleRideCam() {
  const open = G.rides.filter(r => r.open && r.vehicle);
  if (!open.length) { toast('Open a ride first to use Ride Cam 🎥'); return; }
  let i = World.rideCam ? open.findIndex(r => r.vehicle === World.rideCam.vehicle) : -1;
  i++;
  if (i >= open.length) { World.rideCam = null; toast('🎥 Ride cam off'); }
  else { World.rideCam = { vehicle: open[i].vehicle }; toast(`🎥 Riding ${open[i].name}${open.length > 1 ? ' — press 🎥 again for the next ride' : ''}`); }
}

// ---------- building actions ----------
function addPiece(type) {
  const r = G.sel; const def = PIECES[type];
  const res = r.canAdd(type, occupied);
  if (!res.ok) { toast(res.reason); Audio_.fail(); return; }
  if (!G.spend(def.cost)) { toast('Not enough money! 💰 Open a ride or add shops to earn more.'); return; }
  pushHistory(r);
  r.add(type); r.buildMesh(World.scene); Audio_.pop();
  const c = r.cursor; const p = cellCenter(c.cx, c.cz);
  // keep the cursor in view
  const dx = p.x - World.cam.target.x, dz = p.z - World.cam.target.z; if (Math.hypot(dx, dz) > World.cam.dist * 0.45) { World.cam.target.x += dx * 0.5; World.cam.target.z += dz * 0.5; }
  if (r.closed) { toast('🎉 Loop complete! Press TEST RIDE!', 3000, 'gold'); Audio_.coin(); }
  renderContext(); save();
}
function pushHistory(r) { r.history = r.history || []; r.history.push(JSON.stringify(r.pieces)); if (r.history.length > 40) r.history.shift(); }
function undoChange() {
  const r = G.sel; const costBefore = r.cost;
  if (r.history && r.history.length) { r.pieces = JSON.parse(r.history.pop()); r.relayout(); }
  else { const p = r.undo(); if (!p) return; }
  G.money += costBefore - r.cost;
  G.pieceSel = null; G.insertMode = false;
  r.buildMesh(World.scene); Audio_.click(); renderContext(); save();
}
/** Apply a layout edit with validation + money check; reverts and explains on failure. */
function applyEdit(r, mutate) {
  const before = JSON.stringify(r.pieces), costBefore = r.cost;
  mutate(); r.relayout();
  const v = r.validate(occupied);
  if (!v.ok) { r.pieces = JSON.parse(before); r.relayout(); toast("Can't do that: " + v.reason, 3500); Audio_.fail(); return false; }
  const delta = r.cost - costBefore;
  if (delta > 0 && G.money < delta) { r.pieces = JSON.parse(before); r.relayout(); toast(`Not enough money! That costs $${delta} more. 💰`); Audio_.fail(); return false; }
  r.history = r.history || []; r.history.push(before); if (r.history.length > 40) r.history.shift();
  G.money -= delta;
  r.buildMesh(World.scene); Audio_.pop();
  if (r.closed) toast('✅ Still a complete loop! Press TEST RIDE!', 2500, 'gold');
  else toast('The end of the track moved. Bring it back to the Station 🏠 (or 🧲 Auto-Finish)', 3500);
  return true;
}
function selectPiece(i) {
  const r = G.sel; if (!r) return;
  G.insertMode = false;
  G.pieceSel = (i != null && i >= 1 && i < r.pieces.length) ? i : null;
  r.highlightPiece(G.pieceSel, G.pieceSel != null, 0xffd11a, 'selRing');
  if (G.pieceSel != null) { const c = Ride.pieceCenter(r.pieces[G.pieceSel]); const dx = c.x - World.cam.target.x, dz = c.z - World.cam.target.z; if (Math.hypot(dx, dz) > World.cam.dist * 0.4) focusCamera(c.x, c.z); Audio_.click(); }
  renderContext();
}
function swapPiece(type) {
  const r = G.sel, i = G.pieceSel; if (i == null) return;
  if (r.pieces[i].type === type) { toast('It already is a ' + PIECES[type].name + '!'); return; }
  if (applyEdit(r, () => { r.pieces[i] = { type, cx: 0, cz: 0, h: 0, l0: 0, l1: 0 }; })) { selectPiece(i); save(); }
}
function insertPiece(type) {
  const r = G.sel, i = G.pieceSel; if (i == null) return;
  if (applyEdit(r, () => { r.pieces.splice(i + 1, 0, { type, cx: 0, cz: 0, h: 0, l0: 0, l1: 0 }); })) { selectPiece(i + 1); G.insertMode = false; renderContext(); save(); }
}
function removePiece() {
  const r = G.sel, i = G.pieceSel; if (i == null) return;
  if (r.pieces.length <= 2) { toast('Use 🗑️ to remove the whole ride instead.'); return; }
  if (applyEdit(r, () => { r.pieces.splice(i, 1); })) { selectPiece(Math.min(i, r.pieces.length - 1)); save(); }
}
function doAutoConnect() {
  const r = G.sel;
  const pieces = autoConnect(r, occupied);
  if (!pieces) { toast('🧲 Can\'t find a way back to the station! Undo a few pieces and try again.'); Audio_.fail(); return; }
  const cost = pieces.reduce((a, p) => a + PIECES[p.type].cost, 0);
  if (G.money < cost) { toast(`🧲 Auto-Finish costs $${cost}. Not enough money!`); return; }
  let n = 0;
  for (const p of pieces) { const res = r.canAdd(p.type, occupied); if (!res.ok) break; G.money -= PIECES[p.type].cost; r.add(p.type); n++; }
  r.buildMesh(World.scene); Audio_.fanfare();
  toast(r.closed ? `🧲 Added ${n} pieces — loop complete! Press TEST RIDE!` : `🧲 Added ${n} pieces, but the path got blocked. Keep going!`, 3500, 'gold');
  renderContext(); save();
}
function confirmDeleteRide(r) {
  const refund = r.open ? Math.floor(r.cost / 2) : r.cost;
  showModal(`<h2>🗑️ Remove ${r.name}?</h2><p>You get <b>$${refund}</b> back.</p><div class="mrow"><button class="btn red" id="mYes">Yes, remove it</button><button class="btn grey" id="mNo">Keep it</button></div>`);
  $('#mYes').onclick = () => { closeModal(); deleteRide(r, refund); };
  $('#mNo').onclick = closeModal;
}
function deleteRide(r, refund) {
  Guests.clearRide(r); if (Walk.ride === r) Walk.unboard(true);
  if (r.vehicle) { disposeObject(r.vehicle.group); r.vehicle = null; }
  disposeObject(r.group); G.rides.splice(G.rides.indexOf(r), 1);
  G.money += refund; if (G.sel === r) G.sel = null; if (World.rideCam && World.rideCam.vehicle && World.rideCam.vehicle.ride === r) World.rideCam = null;
  setMode('view'); toast(`Removed. +$${refund}`); save();
}
function editRide(r) {
  if (r.open) { r.open = false; r.stars = 0; Guests.clearRide(r); if (r.vehicle) { disposeObject(r.vehicle.group); r.vehicle = null; } }
  // remove last piece so it can be extended? keep loop; kid can undo pieces
  r.buildMesh(World.scene);
  setMode('build', { ride: r });
  toast('Ride closed for building. Undo pieces to change it, then TEST again! 🔧');
}
function renameRide(r) {
  const names = r.water ? ['Splash Mountain', 'Wave Rider', 'Tidal Twist', 'Log Jam', 'Soaker', 'River Rush'] : ['Dragon Fury', 'Thunder Twist', 'Sky Screamer', 'Rocket Rush', 'Loop Beast', 'Comet Coaster', 'Tornado', 'Mega Mouse'];
  showModal(`<h2>✏️ Name your ride</h2><input id="mName" maxlength="18" value="${r.name.replace(/"/g, '')}"><div class="mrow chips">${names.map(n => `<button class="chip" data-n="${n}">${n}</button>`).join('')}</div><div class="mrow"><button class="btn green" id="mOk">OK ✅</button></div>`);
  document.querySelectorAll('.chip').forEach(c => c.onclick = () => { $('#mName').value = c.dataset.n; });
  $('#mOk').onclick = () => { const v = $('#mName').value.trim(); if (v) r.name = v; closeModal(); r.buildMesh(World.scene); renderContext(); save(); };
}
function placeStation(cx, cz) {
  const p = G.pending;
  if (!inPark(cx, cz)) { toast('Build inside the park fence! 🚧'); return; }
  if (!cellFree(cx, cz)) { toast('Something is already there! Pick an empty spot.'); return; }
  const d = DIRS[p.heading];
  if (!inPark(cx + d.x, cz + d.z)) { toast('The station arrow points outside the park. Rotate it 🔄'); return; }
  const r = new Ride(p.type, cx, cz, p.heading, p.color);
  r.name = (p.type === 'water' ? 'Water Ride ' : 'Coaster ') + (G.rides.filter(x => x.type === p.type).length + 1);
  G.rides.push(r); r.buildMesh(World.scene); Audio_.pop();
  setMode('build', { ride: r }); save();
}
function placeShop(cx, cz) {
  const def = SHOPS[G.shopType]; const size = def.size || 1;
  for (let i = 0; i < size; i++) for (let j = 0; j < size; j++) { if (!inPark(cx + i, cz + j)) { toast('Build inside the park fence! 🚧 (buy more land 🌱)'); return; } }
  const b = new Building(G.shopType, cx, cz);
  for (const [x, z] of b.cells()) if (occupied(x, z, 0, buildingHeightLevels(b), null, -1)) { toast('Something is in the way! Pick an empty spot.'); return; }
  if (!G.spend(def.cost)) { toast('Not enough money! 💰'); return; }
  G.buildings.push(b); b.build(World.scene); Audio_.pop(); Particles.emit(b.center.setY(2), 20, { spread: 5, up: 5, life: 0.8, color: 0xffffff, size: 0.8 });
  renderContext(); save();
}
function deleteBuilding(b) {
  Guests.clearBuilding(b); disposeObject(b.group); G.buildings.splice(G.buildings.indexOf(b), 1); G.money += Math.floor(b.def.cost / 2);
  G.selected = null; renderContext(); save();
}
function landPrice() { const steps = (World.parkCells - 20) / LAND_STEP; return [500, 1200, 2500, 5000][steps] || 8000; }
function buyLand() {
  if (World.parkCells >= MAX_PARK) return;
  const price = landPrice(); if (!G.spend(price)) { toast(`More land costs $${price}. Keep earning! 💰`); return; }
  World.parkCells += LAND_STEP; rebuildPark(); Audio_.fanfare(); toast('🌱 Your park is BIGGER! More room to build!', 3500, 'gold'); Particles.confetti(new THREE.Vector3(0, 6, 0));
  renderContext(); save();
}

// ---------- ghost preview ----------
let ghost = null;
function ghostClear() { if (ghost) { disposeObject(ghost); ghost = null; } }
function ghostUpdate(cx, cz) {
  if (G.mode !== 'placeStation' && G.mode !== 'placeShop') { ghostClear(); return; }
  if (cx === undefined) { if (ghost) { cx = ghost.userData.cx; cz = ghost.userData.cz; } else return; }
  ghostClear();
  const size = G.mode === 'placeShop' ? (SHOPS[G.shopType].size || 1) : 1;
  let ok = true;
  for (let i = 0; i < size; i++) for (let j = 0; j < size; j++) if (!inPark(cx + i, cz + j) || occupied(cx + i, cz + j, 0, 3, null, -1)) ok = false;
  const g = new THREE.Group();
  const base = new THREE.Mesh(new THREE.PlaneGeometry(CELL * size - 0.3, CELL * size - 0.3), new THREE.MeshBasicMaterial({ color: ok ? 0x2ecc71 : 0xff3d3d, transparent: true, opacity: 0.5, side: THREE.DoubleSide }));
  base.rotation.x = -Math.PI / 2; base.position.set((cx + size / 2) * CELL, 0.08, (cz + size / 2) * CELL); g.add(base);
  if (G.mode === 'placeStation') {
    const d = DIRS[G.pending.heading];
    const arrow = new THREE.Mesh(new THREE.ConeGeometry(0.9, 2.2, 4), new THREE.MeshBasicMaterial({ color: G.pending.color }));
    arrow.rotation.x = Math.PI / 2; arrow.rotation.z = Math.PI / 4;
    const h = new THREE.Group(); h.add(arrow); const C = cellCenter(cx, cz); h.position.set(C.x, 1.2, C.z); h.lookAt(C.x + d.x, 1.2, C.z + d.z); g.add(h);
  }
  g.userData = { cx, cz }; World.scene.add(g); ghost = g;
}

// ---------- tap handling ----------
function onTap(px, py) {
  Audio_.resume();
  if (G.mode === 'test') return;
  if (G.mode === 'placeStation' || G.mode === 'placeShop') {
    const p = screenToGround(px, py); if (!p) return;
    const cx = Math.floor(p.x / CELL), cz = Math.floor(p.z / CELL);
    if (G.mode === 'placeStation') placeStation(cx, cz); else placeShop(cx, cz);
    return;
  }
  const ray = screenRay(px, py);
  if (G.mode === 'build' && G.sel && G.sel.picks) {
    const hit = ray.intersectObjects(G.sel.picks.children, false);
    if (hit.length) { selectPiece(hit[0].object.userData.pieceIndex); return; }
    if (G.pieceSel != null) { selectPiece(null); return; }
  }
  // pick rides/buildings
  const objs = [];
  for (const r of G.rides) if (r.stationMesh) objs.push(r.stationMesh);
  for (const b of G.buildings) if (b.group) objs.push(b.group);
  const hits = ray.intersectObjects(objs, true);
  if (hits.length) {
    const pick = hits[0].object.userData.pick; Audio_.click();
    if (pick.kind === 'ride') {
      const r = G.rides.find(x => x.id === pick.id);
      if (G.mode === 'build') { if (r !== G.sel) toast('Finish this ride first, or press 💾 Later'); return; }
      if (!r.open) { setMode('build', { ride: r }); return; }
      setMode('view'); G.selected = { kind: 'ride', ride: r }; renderContext();
    } else if (pick.kind === 'building') {
      if (G.mode === 'build') return;
      const b = G.buildings.find(x => x.id === pick.id); setMode('view'); G.selected = { kind: 'building', building: b }; renderContext();
    }
    return;
  }
  if (G.mode === 'view' && G.selected) { G.selected = null; renderContext(); }
}
// ghost follows the pointer (mouse hover or touch move)
document.getElementById('c').addEventListener('pointermove', e => {
  if (G.mode !== 'placeStation' && G.mode !== 'placeShop') return;
  const p = screenToGround(e.clientX, e.clientY); if (!p) return;
  const cx = Math.floor(p.x / CELL), cz = Math.floor(p.z / CELL);
  if (!ghost || ghost.userData.cx !== cx || ghost.userData.cz !== cz) ghostUpdate(cx, cz);
});

// ---------- testing ----------
function startTest(r) {
  if (!r.closed) { toast('Connect the track back to the station first! 🏠'); return; }
  r.buildMesh(World.scene); r.highlightPiece(0, false);
  G.test = { ride: r, stats: newStats(), t: 0 };
  resetVehicle(r.vehicle);
  setMode('test');
  const s = r.station; const c = cellCenter(s.cx, s.cz); focusCamera(c.x, c.z, 34);
  toast('🧪 Testing… watch closely!', 2000);
}
function endTestVisuals() { World.rideCam = null; Audio_.setWhoosh(0); }
function failTest(res) {
  const t = G.test; if (!t) return; G.test = null;
  endTestVisuals();
  const r = t.ride; if (r.vehicle) resetVehicle(r.vehicle);
  if (!res) return; // stopped by user
  r.highlightPiece(res.piece, true); Audio_.fail();
  const p = r.pieces[res.piece]; const c = cellCenter(p.cx, p.cz); focusCamera(c.x, c.z, 30);
  showModal(`<h2>😬 Uh oh! The ride didn't work</h2><p class="big">${res.reason}</p><p>The problem spot is marked with a <b style="color:#e53935">red ring</b>.</p><div class="mrow"><button class="btn green big" id="mFix">🔧 Fix it!</button></div>`, { dismiss: false });
  $('#mFix').onclick = () => { closeModal(); setMode('build', { ride: r, pieceSel: res.piece }); selectPiece(res.piece); r.highlightPiece(res.piece, true); };
}
function passTest() {
  const t = G.test; G.test = null; endTestVisuals();
  const r = t.ride; const rating = rateRide(r, t.stats);
  r.stars = rating.stars; r.open = true; r.stats = Object.assign({}, t.stats, rating); r.highlightPiece(0, false);
  r.vehicle.mode = 'loading'; r.vehicle.timer = 1;
  G.stats.ridesBuilt = (G.stats.ridesBuilt || 0) + 1;
  const s = r.station; const c = cellCenter(s.cx, s.cz);
  if (rating.stars >= 4) Particles.fireworks(c.clone().setY(6)); else Particles.confetti(c.clone().setY(5));
  Audio_.fanfare();
  const tips = rating.stars < 5 ? `<p class="tip">💡 Want more stars? ${r.water ? 'Bigger drops into the Splash Pool, more turns' : 'Taller lift hills, bigger drops, more hills and turns'} make it more exciting!</p>` : '<p class="tip">🌟 A PERFECT ride! Guests will love it!</p>';
  showModal(`<h2>🎉 IT WORKS! ${r.name} is OPEN!</h2><div class="stars">${starStr(rating.stars)}</div>
    <div class="statgrid"><div>⚡ Top speed<b>${Math.floor(t.stats.maxV)}</b></div><div>🏔️ Highest<b>${rating.maxLevel}</b></div><div>⬇️ Biggest drop<b>${rating.bigDrop}</b></div><div>🌀 Turns<b>${t.stats.turns}</b></div><div>🙃 Upside-down<b>${t.stats.inversions}</b></div><div>⏱️ Ride time<b>${Math.floor(t.stats.time)}s</b></div><div>🎟️ Ticket<b>$${ticketPrice(r)}</b></div></div>
    ${tips}<div class="mrow"><button class="btn green big" id="mOpen">🎟️ Let guests ride!</button><button class="btn blue" id="mName2">✏️ Name it</button></div>`, { dismiss: false });
  $('#mOpen').onclick = () => { closeModal(); setMode('view'); G.selected = { kind: 'ride', ride: r }; renderContext(); save(); checkChallenges(); };
  $('#mName2').onclick = () => { closeModal(); setMode('view'); G.selected = { kind: 'ride', ride: r }; renderContext(); save(); renameRide(r); checkChallenges(); };
}
function ticketPrice(r) { return r.stars * 3; }

// ---------- open ride operations ----------
function runOpenRides(dt) {
  for (const r of G.rides) {
    if (!r.open) continue;
    if (!r.vehicle) { if (!r.path) r.buildPath(); r.vehicle = makeVehicle(r); r.vehicle.mode = 'loading'; r.vehicle.timer = 2; }
    const v = r.vehicle;
    if (v.mode === 'loading' && v.timer < 0.5 && !v.boarded) { Guests.board(G, r, v); v.boarded = true; }
    const res = stepVehicle(v, dt, null, {
      onSplash: (f, sp) => { Particles.splash(f.p.clone()); Audio_.splash(); },
      onStation: (veh) => {
        const n = Guests.unload(G, r, veh);
        if (n) { const s = r.station; const c = cellCenter(s.cx, s.cz).setY(5); const amt = n * ticketPrice(r); r.earned += amt; G.earn(amt, c, '🎟️'); }
        veh.boarded = false;
        Walk.onRideArrived(r);
      }
    });
    if (res && res.reason) { // should not happen for a tested ride; reset safely
      resetVehicle(v); v.mode = 'loading'; v.timer = 2;
    }
  }
}

// ---------- hints (tutorial) ----------
function computeHint() {
  const m = G.mode;
  if (m === 'placeStation') return 'Tap the grass where your Station 🏠 should go. The arrow shows which way the cars leave.';
  if (m === 'build') {
    const r = G.sel; const types = r.pieces.map(p => p.type);
    if (G.pieceSel != null) return G.insertMode ? 'Pick a piece below to add it right after the yellow ring.' : 'Pick a piece below to swap it in. Everything after it moves along. ➖ removes it.';
    if (r.closed) return '✅ Loop complete! Press 🧪 TEST RIDE to see if it works. Tap any piece to change it.';
    if (r.pieces.length === 1) return r.water ? 'Add a Conveyor 🔼 to carry the boat up high!' : 'Add a Chain Lift ⛓️ to pull the cars up high — the higher, the faster!';
    if (!types.some(t => PIECES[t].dl < 0)) return r.water ? 'Now add a Drop ↘️ or Big Drop ⬇️ — SPLASH! Then a Splash Pool 💦 at the bottom.' : 'Now add a Drop ↘️ or Big Drop ⬇️ ... wheeee!';
    if (r.water && !types.includes('splash') && r.cursor.l === 0) return 'Add a Splash Pool 💦 here on the ground!';
    if (!r.water && !types.some(t => PIECES[t].inversion) && r.pieces.length < 12) return 'Too fast? Use Brakes 🛑 or a Bank Turn 🏎️. Too slow? Add a Booster 🚀. Loops ➰ need speed 12!';
    return 'Bring the track back to the Station 🏠 to make a loop. Stuck? Press 🧲 Auto-Finish!';
  }
  if (m === 'walk') return Spooky.active ? '' : (Walk.state === 'walk' ? 'Walk up to a ride and press RIDE IT! Drag on the screen to look around.' : '');
  if (m === 'test') return 'Watch the ride! It must make it all the way around without getting stuck or going too fast on turns.';
  if (m === 'placeShop') return 'Tap an empty spot on the grass to build it. Guests will come and spend money! 💰';
  if (m === 'shops') return 'Shops and games earn money from guests. Rides earn tickets. Use money to build MORE!';
  const openRides = G.rides.filter(r => r.open).length;
  if (openRides === 0 && !G.rides.length) return 'Welcome to FitzLandia! Tap 🎢 Coaster to build your first ride!';
  if (openRides === 0) return 'Tap 🎢 Coaster to keep building your ride, then TEST it!';
  if (!G.buildings.length) return 'Tap 🏪 Shops to add a Candy Store 🍭 — guests will buy treats!';
  if (openRides === 1 && G.rides.length === 1) return 'Nice! Try a 🌊 Water Ride next, or check 🏆 Challenges for rewards!';
  return '';
}

// ---------- modals ----------
function showChallenges() {
  const rows = CHALLENGES.map(c => { const [cur, max] = c.check(); const done = G.claimed.includes(c.id); const pct = Math.min(100, Math.round(cur / max * 100));
    return `<div class="ch ${done ? 'done' : ''}"><div class="chi">${c.icon}</div><div class="cht"><b>${c.title}</b><span>${c.desc}</span><div class="bar"><i style="width:${done ? 100 : pct}%"></i></div></div><div class="chr">${done ? '✅' : `$${c.reward}<small>${Math.min(cur, max)}/${max}</small>`}</div></div>`; }).join('');
  showModal(`<h2>🏆 Challenges</h2><div class="chlist">${rows}</div><div class="mrow"><button class="btn grey" onclick="closeModal()">Close</button></div>`);
}
function showMenu() {
  showModal(`<h2>🎡 FitzLandia</h2>
    <div class="menugrid">
      <button class="btn blue" id="mSound">${Audio_.enabled ? '🔊 Sound ON' : '🔇 Sound OFF'}</button>
      <button class="btn blue" id="mRules">📜 Ride Rules</button>
      <button class="btn blue" id="mHelp">❓ How to play</button>
      <button class="btn red" id="mReset">🧨 New Park</button>
    </div>
    <p class="small">Stats: ${G.stats.ridersServed || 0} riders · ${G.stats.shopSales || 0} sales · $${Math.floor(G.totalEarned)} earned all-time</p>
    <div class="mrow"><button class="btn grey" onclick="closeModal()">Close</button></div>`);
  $('#mSound').onclick = () => { Audio_.enabled = !Audio_.enabled; save(); showMenu(); };
  $('#mRules').onclick = showRules;
  $('#mHelp').onclick = showHelp;
  $('#mReset').onclick = () => { showModal(`<h2>🧨 Start a brand new park?</h2><p>Your whole park will be deleted!</p><div class="mrow"><button class="btn red" id="mYes">Yes, start over</button><button class="btn grey" id="mNo">No!</button></div>`); $('#mYes').onclick = () => { localStorage.removeItem(SAVE_KEY); location.reload(); }; $('#mNo').onclick = closeModal; };
}
function showRules() {
  showModal(`<h2>📜 The Laws of FitzLandia Physics</h2><ul class="rules">
    <li>⛓️ <b>Chain Lifts</b> and 🔼 <b>Conveyors</b> pull cars up slowly. Everything else is <b>gravity</b>!</li>
    <li>⬇️ Going <b>down</b> makes you faster. Going <b>up</b> makes you slower. A hill can only be climbed if you have enough speed from a taller hill before it.</li>
    <li>🌀 <b>Turns</b> have a speed limit of <b>${PHYS.turnMax}</b>. 🏎️ <b>Banked turns</b> lean into the curve and allow <b>${PIECES.bankleft.turnMax}</b>.</li>
    <li>🛑 <b>Brakes</b> slow the cars down to <b>${PIECES.brake.brake}</b>. 🚀 <b>Boosters</b> speed them up to <b>${PIECES.booster.boost}</b>. 🐫 <b>Bumps</b> give a little hop and scrub off a bit of speed.</li>
    <li>➰ <b>Loops</b> need speed <b>${PIECES.loop.minSpeed}</b> going in, 🌪️ <b>Corkscrews</b> need <b>${PIECES.corkscrew.minSpeed}</b>. Put a big drop right before them!</li>
    <li>🏁 The track must make a <b>loop</b> back to the Station.</li>
    <li>💦 Water rides: water only flows <b>downhill</b>. Splash Pools must be on the ground.</li>
    <li>🐢 Friction slowly steals speed, so a long flat track will stop. Keep it moving!</li>
    <li>⭐ More height, bigger drops, more turns and more hills = more <b>stars</b> = more money from guests!</li>
  </ul><div class="mrow"><button class="btn grey" onclick="closeModal()">Got it!</button></div>`);
}
function showHelp() {
  showModal(`<h2>❓ How to play</h2><ul class="rules">
    <li>🎢 <b>Coaster</b> / 🌊 <b>Water Ride</b>: place a Station, then tap pieces to add them one after another.</li>
    <li>↩️ <b>Undo</b> takes back your last change. 🧲 <b>Auto-Finish</b> finds a way home.</li>
    <li>✏️ <b>Tap any piece</b> of your track to swap it, remove it, or insert a new piece after it. The rest of the track moves with it.</li>
    <li>🧪 <b>TEST</b> the ride. If it works, guests can ride it and you earn money!</li>
    <li>🏪 <b>Shops</b>: candy, toys, games and big attractions earn money too. 🌱 Buy more land to grow.</li>
    <li>🏆 <b>Challenges</b> give big money rewards.</li>
    <li>👆 One finger: spin the camera. Two fingers: move and zoom. 🎥 Ride Cam puts you in the front seat (press again for the next ride).</li>
    <li>🚶 <b>Walk</b>: be a visitor! Joystick to walk, drag to look, walk up to any ride, shop or the Ferris Wheel and press the button.</li>
  </ul><div class="mrow"><button class="btn grey" onclick="closeModal()">Let's go!</button></div>`);
}

// ---------- save / load ----------
function save() {
  try {
    const data = { v: 1, money: G.money, totalEarned: G.totalEarned, parkCells: World.parkCells, claimed: G.claimed, stats: G.stats, sound: Audio_.enabled,
      rides: G.rides.map(r => r.toJSON()), buildings: G.buildings.map(b => b.toJSON()) };
    localStorage.setItem(SAVE_KEY, JSON.stringify(data));
  } catch (e) { /* storage may be unavailable */ }
}
function load() {
  let data = null;
  try { data = JSON.parse(localStorage.getItem(SAVE_KEY)); } catch (e) { }
  if (!data) return false;
  G.money = data.money; G.totalEarned = data.totalEarned || 0; G.claimed = data.claimed || []; G.stats = data.stats || {}; Audio_.enabled = data.sound !== false;
  if (data.parkCells && data.parkCells !== World.parkCells) { World.parkCells = data.parkCells; rebuildPark(); }
  for (const j of data.rides || []) { const r = Ride.fromJSON(j); G.rides.push(r); r.buildMesh(World.scene); if (r.open && r.stats && !r.stats.maxLevel) r.stats = Object.assign(r.stats, rateRide(r, r.stats)); }
  for (const j of data.buildings || []) { const b = new Building(j.type, j.cx, j.cz); b.earned = j.earned || 0; b.visitors = j.visitors || 0; G.buildings.push(b); b.build(World.scene); }
  return true;
}

// ---------- main ----------
function main() {
  const canvas = document.getElementById('c');
  initWorld(canvas); Particles.init(); Audio_.init();
  initControls(canvas, onTap); initJoystick();
  const loaded = load();
  setMode('view');
  if (!loaded) { showHelp(); }
  document.addEventListener('pointerdown', () => { Audio_.init(); Audio_.resume(); }, { once: true });
  let last = performance.now(), saveT = 0, chalT = 0, allowanceT = 0, hintT = 0;
  function frame(now) {
    requestAnimationFrame(frame);
    const dt = Math.min(0.1, (now - last) / 1000); last = now; G.time += dt;
    animateWorld(dt, G.time);
    for (const b of G.buildings) if (b.anim) b.anim(G.time);
    Guests.update(G, dt, G.time);
    G.stats.maxGuests = Math.max(G.stats.maxGuests || 0, Guests.list.length);
    runOpenRides(dt);
    Walk.update(dt);
    if (G.test) {
      const t = G.test; const v = t.ride.vehicle;
      const res = stepVehicle(v, dt, t.stats, { onSplash: (f, sp) => { Particles.splash(f.p.clone()); Audio_.splash(); } });
      const el = $('#tSpeed'); if (el) el.textContent = v.v.toFixed(0);
      Audio_.setWhoosh(v.v);
      if (!World.rideCam) { const p = v.cars[0].position; World.cam.target.lerp(new THREE.Vector3(p.x, p.y * 0.5, p.z), 0.08); }
      if (res && res.done) passTest(); else if (res && res.reason) failTest(res);
    } else if (World.rideCam && World.rideCam.vehicle) { Audio_.setWhoosh(World.rideCam.vehicle.v); if (!World.rideCam.vehicle.group.parent) World.rideCam = null; }
    else Audio_.setWhoosh(0);
    Particles.update(dt);
    updateCameraTransform();
    World.renderer.render(Spooky.active ? Spooky.scene : World.scene, World.camera);
    saveT += dt; if (saveT > 8) { saveT = 0; save(); }
    chalT += dt; if (chalT > 1) { chalT = 0; checkChallenges(); updateTopbar(); if (G.mode === 'shops' || G.mode === 'placeShop' || G.mode === 'build') refreshAffordability(); }
    hintT += dt; if (hintT > 0.5) { hintT = 0; setHint(computeHint()); }
    // safety net: never let the player get totally stuck with no money
    if (G.money < 40 && !G.rides.some(r => r.open) && !G.buildings.some(b => b.def.earn > 0)) { allowanceT += dt; if (allowanceT > 12) { allowanceT = 0; G.money += 100; toast('🧓 Grandma sent you $100 to keep building!', 3500, 'gold'); Audio_.coin(); updateTopbar(); } } else allowanceT = 0;
  }
  requestAnimationFrame(frame);
}
function refreshAffordability() {
  document.querySelectorAll('#context .piece').forEach(el => { const t = el.dataset.type; if (!t) return; const cost = (G.mode === 'build' ? PIECES[t] : SHOPS[t]).cost; const ok = G.money >= cost && (G.mode !== 'build' || (!G.sel.closed && G.sel.canAdd(t, occupied).ok)); el.classList.toggle('dim', !ok); });
}
window.addEventListener('load', main);
