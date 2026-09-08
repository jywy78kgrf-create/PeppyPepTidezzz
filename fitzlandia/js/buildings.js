/* FitzLandia — buildings.js
   Shops, carnival games, pre-built attractions, decorations. */
'use strict';

const SHOPS = {
  candy:    { name: 'Candy Store',   icon: '🍭', cost: 150, earn: 6, color: 0xff6fb5, roof: '#ffffff', roof2: '#ff6fb5', kind: 'shop', size: 1, gift: '🍭' },
  toy:      { name: 'Toy Store',     icon: '🧸', cost: 200, earn: 8, color: 0x4fb0ff, roof: '#ffe14d', roof2: '#4fb0ff', kind: 'shop', size: 1, gift: '🧸' },
  icecream: { name: 'Ice Cream',     icon: '🍦', cost: 120, earn: 5, color: 0xfff2a8, roof: '#ff8a65', roof2: '#ffffff', kind: 'shop', size: 1, gift: '🍦' },
  balloon:  { name: 'Balloon Stand', icon: '🎈', cost: 80,  earn: 3, color: 0xff5252, roof: '#ffffff', roof2: '#ff5252', kind: 'booth', size: 1, gift: 'balloon' },
  ringtoss: { name: 'Ring Toss',     icon: '🎯', cost: 100, earn: 4, color: 0xffa726, roof: '#ffa726', roof2: '#ffffff', kind: 'booth', size: 1, gift: '🏆' },
  duckpond: { name: 'Duck Pond',     icon: '🦆', cost: 100, earn: 4, color: 0x7ed957, roof: '#7ed957', roof2: '#ffffff', kind: 'booth', size: 1, gift: '🦆' },
  carousel: { name: 'Carousel',      icon: '🎠', cost: 400, earn: 6, color: 0xffd93d, kind: 'attraction', size: 2, stars: 1, gift: '❤️' },
  ferris:   { name: 'Ferris Wheel',  icon: '🎡', cost: 800, earn: 8, color: 0xff3d6e, kind: 'attraction', size: 2, stars: 2, gift: '❤️' },
  spooky:   { name: 'Spooky House',  icon: '👻', cost: 500, earn: 7, color: 0x3b2450, kind: 'attraction', size: 2, stars: 2, gift: '😱', walkin: true },
  droptower:{ name: 'Drop Tower',    icon: '🗼', cost: 1500, earn: 10, color: 0xff3d6e, kind: 'attraction', size: 1, stars: 3, gift: '😱', level: 3 },
  pirate:   { name: 'Pirate Ship',   icon: '🏴‍☠️', cost: 1200, earn: 9, color: 0x8d5a2b, kind: 'attraction', size: 2, stars: 2, gift: '🤩', level: 4 },
  bumper:   { name: 'Bumper Cars',   icon: '🚗', cost: 900, earn: 6, color: 0x1e90ff, kind: 'attraction', size: 2, stars: 2, gift: '😆', level: 5 },
  pizza:    { name: 'Pizza Place',   icon: '🍕', cost: 180, earn: 7, color: 0xff7043, roof: '#ffffff', roof2: '#e53935', kind: 'shop', size: 1, gift: '🍕' },
  popcorn:  { name: 'Popcorn Cart',  icon: '🍿', cost: 90,  earn: 4, color: 0xffca28, roof: '#e53935', roof2: '#ffffff', kind: 'booth', size: 1, gift: '🍿' },
  lemonade: { name: 'Lemonade',      icon: '🍋', cost: 90,  earn: 4, color: 0xfff176, roof: '#ffee58', roof2: '#ffffff', kind: 'booth', size: 1, gift: '🍋' },
  fireworks:{ name: 'Fireworks',     icon: '🎆', cost: 600, earn: 0, kind: 'deco', size: 1, level: 6 },
  path:     { name: 'Path Tile',     icon: '🧱', cost: 5,   earn: 0, kind: 'path', size: 1 },
  lamp:     { name: 'Lamp Post',     icon: '💡', cost: 30,  earn: 0, kind: 'deco', size: 1 },
  statue:   { name: 'Statue',        icon: '🗽', cost: 250, earn: 0, kind: 'deco', size: 1, stars: 1, level: 4 },
  flag:     { name: 'Flag',          icon: '🚩', cost: 20,  earn: 0, kind: 'deco', size: 1 },
  tree:     { name: 'Tree',          icon: '🌳', cost: 20,  earn: 0, kind: 'deco', size: 1 },
  fountain: { name: 'Fountain',      icon: '⛲', cost: 80,  earn: 0, kind: 'deco', size: 1 },
  flowers:  { name: 'Flowers',       icon: '🌷', cost: 15,  earn: 0, kind: 'deco', size: 1 },
};
const SHOP_ORDER = ['candy', 'icecream', 'pizza', 'toy', 'popcorn', 'lemonade', 'balloon', 'ringtoss', 'duckpond', 'carousel', 'ferris', 'spooky', 'droptower', 'pirate', 'bumper', 'path', 'tree', 'flowers', 'fountain', 'lamp', 'flag', 'statue', 'fireworks'];

let _bId = 1;
class Building {
  constructor(type, cx, cz) {
    this.id = _bId++; this.type = type; this.cx = cx; this.cz = cz;
    this.def = SHOPS[type]; this.group = null; this.earned = 0; this.visitors = 0; this.anim = null;
  }
  get size() { return this.def.size || 1; }
  /** world center */
  get center() { const s = this.size; return new THREE.Vector3((this.cx + s / 2) * CELL, 0, (this.cz + s / 2) * CELL); }
  /** where guests stand to use it (south side) */
  get door() { const c = this.center; c.z += this.size * CELL / 2 + 1.0; return c; }
  cells() { const out = []; for (let i = 0; i < this.size; i++) for (let j = 0; j < this.size; j++) out.push([this.cx + i, this.cz + j]); return out; }
  build(scene) {
    if (this.group) disposeObject(this.group);
    const g = buildBuildingMesh(this); this.group = g;
    const c = this.center; g.position.set(c.x, 0, c.z);
    g.userData.pick = { kind: 'building', id: this.id }; g.traverse(o => { o.userData.pick = g.userData.pick; });
    scene.add(g); return g;
  }
  toJSON() { return { type: this.type, cx: this.cx, cz: this.cz, earned: this.earned, visitors: this.visitors }; }
}

function hex(c) { return '#' + new THREE.Color(c).getHexString(); }

function buildBuildingMesh(b) {
  const d = b.def, g = new THREE.Group();
  const std = (color, extra = {}) => new THREE.MeshStandardMaterial(Object.assign({ color, roughness: 0.7 }, extra));
  if (d.kind === 'shop') {
    const body = new THREE.Mesh(new THREE.BoxGeometry(3.3, 2.6, 3.0), std(d.color)); body.position.y = 1.3; body.castShadow = true; body.receiveShadow = true; g.add(body);
    const roof = new THREE.Mesh(new THREE.ConeGeometry(2.7, 1.6, 4), std(0xffffff, { map: stripeTexture(d.roof, d.roof2) })); roof.position.y = 3.4; roof.rotation.y = Math.PI / 4; roof.castShadow = true; g.add(roof);
    const door = new THREE.Mesh(new THREE.BoxGeometry(0.9, 1.5, 0.1), std(0x5d4037)); door.position.set(0, 0.75, 1.52); g.add(door);
    for (const x of [-1.0, 1.0]) { const win = new THREE.Mesh(new THREE.BoxGeometry(0.8, 0.7, 0.1), std(0xbfe8ff, { roughness: 0.2 })); win.position.set(x, 1.5, 1.52); g.add(win); }
    const awn = new THREE.Mesh(new THREE.BoxGeometry(3.4, 0.12, 1.0), std(0xffffff, { map: stripeTexture(d.roof2, '#ffffff') })); awn.position.set(0, 2.15, 1.9); awn.rotation.x = 0.25; awn.castShadow = true; g.add(awn);
    addSign(g, d.icon + ' ' + d.name, hex(d.color), 2.9, 3.0, 1.6);
  } else if (d.kind === 'booth') {
    const counter = new THREE.Mesh(new THREE.BoxGeometry(3.2, 1.1, 2.6), std(d.color)); counter.position.y = 0.55; counter.castShadow = true; g.add(counter);
    const back = new THREE.Mesh(new THREE.BoxGeometry(3.2, 2.4, 0.3), std(d.color)); back.position.set(0, 1.2, -1.15); g.add(back);
    for (const x of [-1.45, 1.45]) { const p = new THREE.Mesh(new THREE.CylinderGeometry(0.08, 0.08, 3, 6), std(0xffffff)); p.position.set(x, 1.5, 1.15); g.add(p); }
    const canopy = new THREE.Mesh(new THREE.ConeGeometry(2.6, 1.2, 4), std(0xffffff, { map: stripeTexture(d.roof, d.roof2) })); canopy.position.y = 3.55; canopy.rotation.y = Math.PI / 4; canopy.castShadow = true; g.add(canopy);
    // prizes / props
    if (b.type === 'balloon') for (let i = 0; i < 5; i++) { const bal = new THREE.Mesh(new THREE.SphereGeometry(0.3, 10, 8), std([0xff5252, 0x4fb0ff, 0xffd93d, 0x7ed957, 0xff6fb5][i])); bal.position.set(-1 + i * 0.5, 2.0 + (i % 2) * 0.4, -0.9); g.add(bal); }
    if (b.type === 'ringtoss') for (let i = 0; i < 6; i++) { const peg = new THREE.Mesh(new THREE.CylinderGeometry(0.06, 0.06, 0.5, 6), std(0xffffff)); peg.position.set(-1 + (i % 3) * 1, 1.35, -0.5 + Math.floor(i / 3) * 0.7); g.add(peg); const ring = new THREE.Mesh(new THREE.TorusGeometry(0.22, 0.05, 6, 12), std(0xff3d6e)); ring.rotation.x = Math.PI / 2; ring.position.copy(peg.position); ring.position.y = 1.12 + Math.random() * 0.3; g.add(ring); }
    if (b.type === 'duckpond') { const pond = new THREE.Mesh(new THREE.CylinderGeometry(1.2, 1.2, 0.2, 16), std(0x2a9ad8)); pond.position.y = 1.2; g.add(pond); const ps = new THREE.Mesh(new THREE.CircleGeometry(1.2, 20), waterMaterial()); ps.rotation.x = -Math.PI / 2; ps.position.y = 1.31; g.add(ps); for (let i = 0; i < 4; i++) { const duck = new THREE.Mesh(new THREE.SphereGeometry(0.18, 8, 6), std(0xffe14d)); const a = i * 1.6; duck.position.set(Math.cos(a) * 0.7, 1.4, Math.sin(a) * 0.7); g.add(duck); } }
    addSign(g, d.icon + ' ' + d.name, hex(d.color), 2.9, 2.9, 1.3);
  } else if (b.type === 'carousel') {
    const base = new THREE.Mesh(new THREE.CylinderGeometry(3.6, 3.8, 0.5, 24), std(0xfff3c4)); base.position.y = 0.25; base.receiveShadow = true; g.add(base);
    const pole = new THREE.Mesh(new THREE.CylinderGeometry(0.25, 0.25, 4.5, 10), std(0xffd93d, { metalness: 0.4 })); pole.position.y = 2.5; g.add(pole);
    const roof = new THREE.Mesh(new THREE.ConeGeometry(4.0, 1.8, 16), std(0xffffff, { map: stripeTexture('#ff3d6e', '#ffffff') })); roof.position.y = 5.3; roof.castShadow = true; g.add(roof);
    const spin = new THREE.Group(); spin.position.y = 0.5; g.add(spin);
    const horseColors = [0xffffff, 0xff8fb1, 0x8fd0ff, 0xffe066, 0xb39ddb, 0xa5d6a7];
    for (let i = 0; i < 6; i++) {
      const a = i / 6 * Math.PI * 2; const h = new THREE.Group();
      const hp = new THREE.Mesh(new THREE.CylinderGeometry(0.06, 0.06, 4, 6), std(0xffd93d)); hp.position.y = 2; h.add(hp);
      const body = new THREE.Mesh(new THREE.BoxGeometry(0.5, 0.5, 1.2), std(horseColors[i])); body.position.y = 1.4; h.add(body);
      const head = new THREE.Mesh(new THREE.BoxGeometry(0.35, 0.5, 0.5), std(horseColors[i])); head.position.set(0, 1.85, 0.7); h.add(head);
      for (const [x, z] of [[-0.18, 0.4], [0.18, 0.4], [-0.18, -0.4], [0.18, -0.4]]) { const leg = new THREE.Mesh(new THREE.BoxGeometry(0.12, 0.6, 0.12), std(horseColors[i])); leg.position.set(x, 0.9, z); h.add(leg); }
      h.position.set(Math.cos(a) * 2.6, 0, Math.sin(a) * 2.6); h.rotation.y = -a; h.userData.phase = i;
      spin.add(h);
    }
    b.anim = (t) => { spin.rotation.y = t * 0.6; spin.children.forEach(h => { h.position.y = Math.sin(t * 3 + h.userData.phase) * 0.35 + 0.35; }); };
    b.seats = spin.children.slice();
    addSign(g, '🎠 Carousel', '#ff3d6e', 4.5, 6.5, 0);
  } else if (b.type === 'ferris') {
    const R = 5;
    const frameMat = std(0xff3d6e, { metalness: 0.3 });
    for (const s of [-1, 1]) { const leg = new THREE.Mesh(new THREE.BoxGeometry(0.35, R * 1.55, 0.35), frameMat); leg.position.set(s * 2.0, R / 2 + 0.5, 0); leg.rotation.z = s * 0.28; leg.castShadow = true; g.add(leg); }
    const wheel = new THREE.Group(); wheel.position.y = R + 1;
    for (const z of [-0.6, 0.6]) { const ring = new THREE.Mesh(new THREE.TorusGeometry(R, 0.15, 8, 40), std(0xffd93d, { metalness: 0.4 })); ring.position.z = z; wheel.add(ring); }
    for (let i = 0; i < 8; i++) { const a = i / 8 * Math.PI; const sp = new THREE.Mesh(new THREE.BoxGeometry(0.12, R * 2, 0.12), std(0xffffff)); sp.rotation.z = a; wheel.add(sp); }
    const hub = new THREE.Mesh(new THREE.CylinderGeometry(0.5, 0.5, 1.6, 12), std(0xffffff)); hub.rotation.x = Math.PI / 2; wheel.add(hub);
    const gondolas = [];
    const gcol = [0xff5252, 0x4fb0ff, 0xffd93d, 0x7ed957, 0xff6fb5, 0xffa726, 0xb39ddb, 0x80deea];
    for (let i = 0; i < 8; i++) {
      const a = i / 8 * Math.PI * 2; const gd = new THREE.Group();
      const cab = new THREE.Mesh(new THREE.BoxGeometry(1.1, 0.9, 1.3), std(gcol[i])); cab.position.y = -0.7; cab.castShadow = true; gd.add(cab);
      const top = new THREE.Mesh(new THREE.ConeGeometry(0.8, 0.5, 8), std(gcol[i])); top.position.y = -0.1; gd.add(top);
      gd.userData.a = a; wheel.add(gd); gondolas.push(gd);
    }
    g.add(wheel); b.seats = gondolas;
    b.anim = (t) => { wheel.rotation.z = t * 0.25; for (const gd of gondolas) { const a = gd.userData.a; gd.position.set(Math.cos(a) * R, Math.sin(a) * R, 0); gd.rotation.z = -wheel.rotation.z; } };
    addSign(g, '🎡 Ferris Wheel', '#ff3d6e', 5, 1.2, 3.2);
  } else if (b.type === 'spooky') {
    const wood = std(0x3b2450, { roughness: 0.9 });
    const body = new THREE.Mesh(new THREE.BoxGeometry(6.4, 5.2, 5.6), wood); body.position.y = 2.6; body.castShadow = true; body.receiveShadow = true; g.add(body);
    const roof = new THREE.Mesh(new THREE.ConeGeometry(5.2, 3.4, 4), std(0x1c1026)); roof.position.y = 6.9; roof.rotation.y = Math.PI / 4; roof.castShadow = true; g.add(roof);
    const tower = new THREE.Mesh(new THREE.CylinderGeometry(0.9, 0.9, 3.5, 8), wood); tower.position.set(2.4, 6.2, -1.6); g.add(tower);
    const cap = new THREE.Mesh(new THREE.ConeGeometry(1.2, 1.8, 8), std(0x1c1026)); cap.position.set(2.4, 8.8, -1.6); g.add(cap);
    const glow = new THREE.MeshBasicMaterial({ color: 0x7dff9a });
    for (const [x, y] of [[-2, 3.4], [2, 3.4], [-2, 1.4], [2, 1.4]]) { const win = new THREE.Mesh(new THREE.BoxGeometry(0.9, 1.0, 0.1), glow); win.position.set(x, y, 2.83); g.add(win); }
    const door = new THREE.Mesh(new THREE.BoxGeometry(1.6, 2.6, 0.12), std(0x120a18)); door.position.set(0, 1.3, 2.83); g.add(door);
    const ghost = new THREE.Mesh(new THREE.SphereGeometry(0.6, 12, 10), std(0xffffff, { emissive: 0x99aaff, emissiveIntensity: 0.5 })); ghost.scale.y = 1.3; ghost.position.set(-2.6, 6.2, 1.2); g.add(ghost);
    const pl = new THREE.PointLight(0x7dff9a, 1.2, 12, 2); pl.position.set(0, 2.5, 3.5); g.add(pl);
    const bats = []; const batMat = new THREE.MeshBasicMaterial({ color: 0x111111, side: THREE.DoubleSide });
    for (let i = 0; i < 4; i++) { const bt = new THREE.Mesh(new THREE.PlaneGeometry(0.9, 0.35), batMat); bt.userData.a = i * 1.6; g.add(bt); bats.push(bt); }
    const fenceMat = std(0x2a2a2a, { metalness: 0.5 });
    for (let i = -3; i <= 3; i++) { const pk = new THREE.Mesh(new THREE.ConeGeometry(0.07, 1.4, 5), fenceMat); pk.position.set(i * 1.0, 0.7, 3.6); g.add(pk); }
    const rail = new THREE.Mesh(new THREE.BoxGeometry(6.6, 0.06, 0.06), fenceMat); rail.position.set(0, 0.9, 3.6); g.add(rail);
    b.anim = (t) => { ghost.position.y = 6.2 + Math.sin(t * 1.5) * 0.4; ghost.position.x = -2.6 + Math.sin(t * 0.7) * 0.6; pl.intensity = 1.0 + Math.sin(t * 9) * 0.4 + (Math.random() < 0.03 ? 1.5 : 0); bats.forEach(bt => { const a = t * 1.3 + bt.userData.a; bt.position.set(Math.cos(a) * 4.5, 8.5 + Math.sin(a * 2) * 0.6, Math.sin(a) * 4.5); bt.rotation.y = -a; bt.scale.y = 0.6 + Math.abs(Math.sin(t * 14 + bt.userData.a)) * 0.6; }); };
    addSign(g, '👻 Spooky House', '#7dff9a', 5, 4.6, 2.9);
  } else if (b.type === 'droptower') {
    const H = 16; const pole = new THREE.Mesh(new THREE.CylinderGeometry(0.45, 0.6, H, 10), std(0xb0bec5, { metalness: 0.5, roughness: 0.4 })); pole.position.y = H / 2; pole.castShadow = true; g.add(pole);
    const base = new THREE.Mesh(new THREE.CylinderGeometry(1.8, 2.0, 0.5, 16), std(0x90a4ae)); base.position.y = 0.25; g.add(base);
    const top = new THREE.Mesh(new THREE.ConeGeometry(0.9, 1.6, 8), std(d.color)); top.position.y = H + 0.7; g.add(top);
    const gond = new THREE.Group(); const ring = new THREE.Mesh(new THREE.TorusGeometry(1.3, 0.25, 8, 20), std(d.color)); ring.rotation.x = Math.PI / 2; gond.add(ring);
    for (let i = 0; i < 6; i++) { const a = i / 6 * Math.PI * 2; const seat = new THREE.Mesh(new THREE.BoxGeometry(0.6, 0.7, 0.6), std(0x263238)); seat.position.set(Math.cos(a) * 1.3, 0.35, Math.sin(a) * 1.3); seat.rotation.y = -a; gond.add(seat); }
    gond.position.y = 1; g.add(gond); b.seats = [gond];
    b.anim = (t) => { const T = t % 16; let y; if (T < 8) y = 1 + (T / 8) * (H - 3); else if (T < 10.5) y = H - 2 + Math.sin(T * 6) * 0.05; else if (T < 11.1) { const u = (T - 10.5) / 0.6; y = (H - 2) - u * u * (H - 3); } else if (T < 12) y = 1 + Math.abs(Math.sin((T - 11.1) * 8)) * 0.6 * (1 - (T - 11.1)); else y = 1; gond.position.y = y; gond.rotation.y = t * 0.3; };
    addSign(g, '🗼 Drop Tower', hex(d.color), 3.2, 3.2, 2.0);
  } else if (b.type === 'pirate') {
    const frame = std(0x546e7a, { metalness: 0.4 });
    for (const sx of [-1, 1]) for (const sz of [-1, 1]) { const leg = new THREE.Mesh(new THREE.CylinderGeometry(0.18, 0.22, 7.4, 8), frame); leg.position.set(sx * 1.6, 3.6, sz * 1.2); leg.rotation.z = -sx * 0.32; leg.rotation.x = sz * 0.2; leg.castShadow = true; g.add(leg); }
    const axle = new THREE.Mesh(new THREE.CylinderGeometry(0.2, 0.2, 3.4, 8), frame); axle.rotation.x = Math.PI / 2; axle.position.y = 7.0; g.add(axle);
    const pivot = new THREE.Group(); pivot.position.y = 7.0; g.add(pivot);
    for (const sz of [-1.1, 1.1]) { const arm = new THREE.Mesh(new THREE.BoxGeometry(0.25, 5.6, 0.25), frame); arm.position.set(0, -2.8, sz); pivot.add(arm); }
    const boat = new THREE.Group(); boat.position.y = -5.6;
    const hull = new THREE.Mesh(new THREE.BoxGeometry(5.6, 1.2, 2.0), std(d.color)); hull.castShadow = true; boat.add(hull);
    for (const e of [-1, 1]) { const bow = new THREE.Mesh(new THREE.ConeGeometry(1.0, 1.8, 4), std(d.color)); bow.rotation.z = e * Math.PI / 2; bow.rotation.y = Math.PI / 4; bow.position.set(e * 3.6, 0.4, 0); boat.add(bow); }
    for (let i = 0; i < 4; i++) { const row = new THREE.Mesh(new THREE.BoxGeometry(0.7, 0.5, 1.6), std(0x263238)); row.position.set(-1.9 + i * 1.25, 0.85, 0); boat.add(row); }
    const mast = new THREE.Mesh(new THREE.CylinderGeometry(0.06, 0.08, 2.4, 6), std(0x5d4037)); mast.position.set(0, 1.6, 0); boat.add(mast);
    const flag = new THREE.Mesh(new THREE.PlaneGeometry(1.0, 0.6), new THREE.MeshBasicMaterial({ map: textTexture('☠️', { bg: '#111', color: '#fff', size: 48, w: 128, h: 80 }), side: THREE.DoubleSide })); flag.position.set(0.5, 2.5, 0); boat.add(flag);
    pivot.add(boat); b.seats = [boat];
    b.anim = (t) => { pivot.rotation.z = Math.sin(t * 1.1) * 1.15; };
    addSign(g, '🏴‍☠️ Pirate Ship', hex(d.color), 5, 1.0, 3.2);
  } else if (b.type === 'bumper') {
    const floor = new THREE.Mesh(new THREE.BoxGeometry(7.4, 0.3, 7.4), std(0x37474f, { roughness: 0.4, metalness: 0.2 })); floor.position.y = 0.15; floor.receiveShadow = true; g.add(floor);
    const rim = new THREE.Mesh(new THREE.BoxGeometry(7.8, 0.6, 7.8), std(0xffca28)); rim.position.y = 0.3; g.add(rim); const inner = new THREE.Mesh(new THREE.BoxGeometry(7.0, 0.7, 7.0), std(0x37474f)); inner.position.y = 0.35; g.add(inner);
    for (const [x, z] of [[-3.7, -3.7], [3.7, -3.7], [-3.7, 3.7], [3.7, 3.7]]) { const post = new THREE.Mesh(new THREE.CylinderGeometry(0.1, 0.1, 5, 6), std(0xffca28)); post.position.set(x, 2.5, z); g.add(post); }
    const roof = new THREE.Mesh(new THREE.BoxGeometry(8.2, 0.25, 8.2), std(0xffffff, { map: stripeTexture('#1e90ff', '#ffffff') })); roof.position.y = 5.1; roof.castShadow = true; g.add(roof);
    const cars = []; const cc = [0xff3d6e, 0x2ecc71, 0xffd11a, 0x9b59b6, 0xff8c1a];
    for (let i = 0; i < 5; i++) { const car = new THREE.Group(); const body = new THREE.Mesh(new THREE.CylinderGeometry(0.55, 0.65, 0.5, 12), std(cc[i])); body.position.y = 0.6; car.add(body); const bumperRing = new THREE.Mesh(new THREE.TorusGeometry(0.62, 0.12, 6, 14), std(0x222)); bumperRing.rotation.x = Math.PI / 2; bumperRing.position.y = 0.45; car.add(bumperRing); const seat = new THREE.Mesh(new THREE.BoxGeometry(0.5, 0.4, 0.4), std(0x263238)); seat.position.set(0, 0.95, -0.15); car.add(seat); const pole = new THREE.Mesh(new THREE.CylinderGeometry(0.03, 0.03, 4.2, 4), std(0x999)); pole.position.set(0, 2.9, -0.4); pole.rotation.x = 0.15; car.add(pole); car.userData = { ph: i * 1.3, r: 1.2 + i * 0.4, sp: 0.5 + i * 0.13 }; g.add(car); cars.push(car); }
    b.seats = cars;
    b.anim = (t) => { for (const c of cars) { const u = c.userData; const a = t * u.sp + u.ph; const r = u.r + Math.sin(t * 0.7 + u.ph) * 0.8; const x = Math.cos(a) * r, z = Math.sin(a * 1.3) * r; const nx = Math.cos(a + 0.05) * r, nz = Math.sin((a + 0.05) * 1.3) * r; c.position.set(x, 0.3, z); c.rotation.y = Math.atan2(nx - x, nz - z); } };
    addSign(g, '🚗 Bumper Cars', '#1e90ff', 5, 5.6, 4.0);
  } else if (b.type === 'fireworks') {
    const base = new THREE.Mesh(new THREE.BoxGeometry(2.4, 0.5, 2.4), std(0x5d4037)); base.position.y = 0.25; g.add(base);
    for (const [x, z] of [[-0.6, -0.6], [0.6, -0.6], [-0.6, 0.6], [0.6, 0.6], [0, 0]]) { const tube = new THREE.Mesh(new THREE.CylinderGeometry(0.22, 0.22, 1.2, 8), std([0xff3d6e, 0xffd11a, 0x2ecc71, 0x1e90ff, 0x9b59b6][((x + z) * 3 + 5) | 0 % 5])); tube.position.set(x, 1.0, z); g.add(tube); }
    const fence = new THREE.Mesh(new THREE.BoxGeometry(3.2, 0.5, 3.2), std(0xffd11a, { wireframe: true })); fence.position.y = 0.5; g.add(fence);
    b.timer = 4 + Math.random() * 4;
    b.anim = (t) => { /* launches handled in game loop via b.timer */ };
    addSign(g, '🎆 Fireworks', '#ff3d6e', 3, 2.2, 1.7);
  } else if (b.type === 'path') {
    const tile = new THREE.Mesh(new THREE.PlaneGeometry(CELL, CELL), new THREE.MeshStandardMaterial({ map: pavementTexture(), roughness: 1 })); tile.rotation.x = -Math.PI / 2; tile.position.y = 0.015; tile.receiveShadow = true; g.add(tile);
  } else if (b.type === 'lamp') {
    const pole = new THREE.Mesh(new THREE.CylinderGeometry(0.08, 0.12, 3.6, 6), std(0x37474f)); pole.position.y = 1.8; pole.castShadow = true; g.add(pole);
    const arm = new THREE.Mesh(new THREE.BoxGeometry(0.9, 0.08, 0.08), std(0x37474f)); arm.position.set(0.4, 3.5, 0); g.add(arm);
    const bulb = new THREE.Mesh(new THREE.SphereGeometry(0.3, 10, 8), World.lampMat || std(0xfff1b0)); bulb.position.set(0.8, 3.3, 0); g.add(bulb);
    const bench = new THREE.Mesh(new THREE.BoxGeometry(1.4, 0.12, 0.5), std(0x8d6e63)); bench.position.set(-0.9, 0.5, 0.6); g.add(bench); for (const x of [-1.5, -0.3]) { const bl = new THREE.Mesh(new THREE.BoxGeometry(0.1, 0.5, 0.4), std(0x5d4037)); bl.position.set(x, 0.25, 0.6); g.add(bl); }
  } else if (b.type === 'statue') {
    const ped = new THREE.Mesh(new THREE.BoxGeometry(1.6, 1.4, 1.6), std(0xcfd8dc)); ped.position.y = 0.7; ped.castShadow = true; g.add(ped);
    const gold = std(0xffd54f, { metalness: 0.8, roughness: 0.25 });
    const figure = new THREE.Group(); const body = new THREE.Mesh(new THREE.CapsuleGeometry(0.4, 0.9, 4, 8), gold); body.position.y = 1.0; figure.add(body); const head = new THREE.Mesh(new THREE.SphereGeometry(0.35, 10, 8), gold); head.position.y = 1.95; figure.add(head);
    const arm = new THREE.Mesh(new THREE.CylinderGeometry(0.1, 0.1, 1.2, 6), gold); arm.position.set(0.45, 1.7, 0); arm.rotation.z = -0.5; figure.add(arm); const torch = new THREE.Mesh(new THREE.ConeGeometry(0.22, 0.5, 8), std(0xff8c1a, { emissive: 0xff5a00, emissiveIntensity: 0.6 })); torch.position.set(0.78, 2.45, 0); figure.add(torch);
    figure.position.y = 1.4; figure.scale.setScalar(1.1); g.add(figure);
    addSign(g, '🗽 Park Founder', '#ffd54f', 2.6, 0.9, 0.9);
  } else if (b.type === 'flag') {
    const pole = new THREE.Mesh(new THREE.CylinderGeometry(0.05, 0.07, 4.5, 6), std(0xeceff1)); pole.position.y = 2.25; g.add(pole);
    const col = [0xff3d6e, 0x1e90ff, 0x2ecc71, 0xffd11a, 0x9b59b6][(Math.random() * 5) | 0];
    const fl = new THREE.Mesh(new THREE.PlaneGeometry(1.6, 1.0, 8, 1), std(col, { side: THREE.DoubleSide })); fl.position.set(0.8, 3.9, 0); g.add(fl);
    const pa = fl.geometry.attributes.position; const base = pa.array.slice();
    b.anim = (t) => { for (let i = 0; i < pa.count; i++) { const x = base[i * 3]; pa.array[i * 3 + 2] = Math.sin(t * 6 + x * 3) * 0.12 * (x + 0.8); } pa.needsUpdate = true; };
  } else if (b.type === 'tree') {
    const trunk = new THREE.Mesh(new THREE.CylinderGeometry(0.22, 0.32, 1.6, 8), std(0x795548)); trunk.position.y = 0.8; trunk.castShadow = true; g.add(trunk);
    const greens = [0x2e9e4f, 0x3cb55e, 0x27893f];
    for (let i = 0; i < 3; i++) { const s = new THREE.Mesh(new THREE.SphereGeometry(1.0 + Math.random() * 0.4, 10, 8), std(greens[i])); s.position.set((Math.random() - 0.5) * 0.9, 2.0 + i * 0.55, (Math.random() - 0.5) * 0.9); s.castShadow = true; g.add(s); }
    g.rotation.y = Math.random() * 6;
  } else if (b.type === 'fountain') {
    const basin = new THREE.Mesh(new THREE.CylinderGeometry(1.6, 1.7, 0.6, 20), std(0xd7ccc8)); basin.position.y = 0.3; basin.castShadow = true; g.add(basin);
    const wbase = new THREE.Mesh(new THREE.CylinderGeometry(1.45, 1.45, 0.1, 20), std(0x2a9ad8)); wbase.position.y = 0.55; g.add(wbase);
    const water = new THREE.Mesh(new THREE.CircleGeometry(1.45, 24), waterMaterial()); water.rotation.x = -Math.PI / 2; water.position.y = 0.62; water.renderOrder = 2; g.add(water);
    const col = new THREE.Mesh(new THREE.CylinderGeometry(0.2, 0.3, 1.6, 8), std(0xd7ccc8)); col.position.y = 1.2; g.add(col);
    const jet = new THREE.Mesh(new THREE.SphereGeometry(0.5, 10, 8), std(0x8fd8ff, { transparent: true, opacity: 0.7 })); jet.position.y = 2.2; g.add(jet);
    b.anim = (t) => { jet.scale.setScalar(0.8 + Math.sin(t * 6) * 0.25); jet.position.y = 2.2 + Math.sin(t * 6) * 0.2; };
  } else if (b.type === 'flowers') {
    const bed = new THREE.Mesh(new THREE.CylinderGeometry(1.4, 1.5, 0.3, 12), std(0x6d4c41)); bed.position.y = 0.15; g.add(bed);
    const cols = [0xff3d6e, 0xffd93d, 0xff8c1a, 0xffffff, 0xb39ddb];
    for (let i = 0; i < 14; i++) { const f = new THREE.Mesh(new THREE.SphereGeometry(0.18, 6, 5), std(cols[i % cols.length])); const a = Math.random() * 6.3, r = Math.random() * 1.1; f.position.set(Math.cos(a) * r, 0.45 + Math.random() * 0.2, Math.sin(a) * r); g.add(f); }
  }
  return g;
}

function addSign(g, text, border, width, y, z) {
  const tex = textTexture(text, { bg: '#ffffff', color: '#222', border, size: 60, w: 640, h: 128 });
  const sign = new THREE.Mesh(new THREE.PlaneGeometry(width, width / 5), new THREE.MeshBasicMaterial({ map: tex, side: THREE.DoubleSide, transparent: true }));
  sign.position.set(0, y, z); g.add(sign);
}
