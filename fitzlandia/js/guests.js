/* FitzLandia — guests.js
   NPC visitors: walk around, buy treats, queue for rides, ride them, cheer. */
'use strict';

const SKIN = [0xffdbac, 0xf1c27d, 0xe0ac69, 0xc68642, 0x8d5524, 0xffe0bd];
const SHIRTS = [0xff3d6e, 0xff8c1a, 0xffd11a, 0x2ecc71, 0x1e90ff, 0x9b59b6, 0x00bcd4, 0xffffff, 0xf06292, 0x8bc34a];
const PANTS = [0x37474f, 0x1565c0, 0x5d4037, 0x263238, 0xd32f2f];
const _geo = {};
function sharedGeo(name, make) { return _geo[name] || (_geo[name] = make()); }
const _mats = new Map();
function sharedMat(color) { if (!_mats.has(color)) _mats.set(color, new THREE.MeshStandardMaterial({ color, roughness: 0.8 })); return _mats.get(color); }

let _gId = 1;
class Guest {
  constructor(pos) {
    this.id = _gId++;
    const g = new THREE.Group(); this.group = g;
    const kid = Math.random() < 0.4; this.scale = kid ? 0.75 : 1;
    const shirt = SHIRTS[(Math.random() * SHIRTS.length) | 0], skin = SKIN[(Math.random() * SKIN.length) | 0], pants = PANTS[(Math.random() * PANTS.length) | 0];
    const legs = new THREE.Mesh(sharedGeo('legs', () => new THREE.BoxGeometry(0.5, 0.7, 0.3)), sharedMat(pants)); legs.position.y = 0.35; g.add(legs);
    const body = new THREE.Mesh(sharedGeo('body', () => new THREE.CapsuleGeometry(0.3, 0.55, 4, 8)), sharedMat(shirt)); body.position.y = 1.05; body.castShadow = true; g.add(body);
    const head = new THREE.Mesh(sharedGeo('head', () => new THREE.SphereGeometry(0.28, 10, 8)), sharedMat(skin)); head.position.y = 1.75; g.add(head);
    const hairC = [0x3e2723, 0xffb300, 0x212121, 0xbf360c, 0x795548][(Math.random() * 5) | 0];
    const hair = new THREE.Mesh(sharedGeo('hair', () => new THREE.SphereGeometry(0.29, 10, 8, 0, Math.PI * 2, 0, Math.PI / 2)), sharedMat(hairC)); hair.position.y = 1.8; g.add(hair);
    if (Math.random() < 0.3) { const hat = new THREE.Mesh(sharedGeo('hat', () => new THREE.ConeGeometry(0.3, 0.5, 8)), sharedMat(SHIRTS[(Math.random() * SHIRTS.length) | 0])); hat.position.y = 2.2; g.add(hat); }
    g.scale.setScalar(this.scale);
    g.position.copy(pos);
    this.body = body; this.head = head;
    this.state = 'wander'; this.target = null; this.timer = 0; this.speed = 2.2 + Math.random() * 1.2;
    this.ride = null; this.building = null; this.seat = null; this.happy = 0; this.life = 150 + Math.random() * 150;
    this.balloon = null; this.bubble = null; this.walkT = Math.random() * 10; this.queueIndex = -1;
    this.visited = new Set();
  }
  setTarget(p) { this.target = p.clone(); }
  giveBalloon() {
    if (this.balloon) return;
    const b = new THREE.Group();
    const s = new THREE.Mesh(sharedGeo('balloon', () => new THREE.SphereGeometry(0.32, 10, 8)), sharedMat(SHIRTS[(Math.random() * 6) | 0])); s.scale.y = 1.2; s.position.y = 1.2; b.add(s);
    const str = new THREE.Mesh(sharedGeo('string', () => new THREE.CylinderGeometry(0.015, 0.015, 1.2, 4)), sharedMat(0xffffff)); str.position.y = 0.5; b.add(str);
    b.position.set(0.4, 1.9, 0); this.group.add(b); this.balloon = b;
  }
  say(emoji, secs = 2.2) {
    if (this.bubble) { this.group.remove(this.bubble); this.bubble.material.map.dispose(); this.bubble.material.dispose(); }
    const tex = canvasTex(128, 128, (ctx, w, h) => { ctx.fillStyle = 'rgba(255,255,255,0.95)'; ctx.beginPath(); ctx.arc(w / 2, h / 2 - 8, 50, 0, Math.PI * 2); ctx.fill(); ctx.font = '64px sans-serif'; ctx.textAlign = 'center'; ctx.textBaseline = 'middle'; ctx.fillText(emoji, w / 2, h / 2 - 4); });
    const sp = new THREE.Sprite(new THREE.SpriteMaterial({ map: tex, transparent: true, depthTest: false })); sp.scale.set(1.3, 1.3, 1); sp.position.y = 2.9; sp.renderOrder = 5;
    this.group.add(sp); this.bubble = sp; this.bubbleT = secs;
  }
  dispose() { disposeObject(this.group); }
}

const Guests = {
  list: [], spawnTimer: 2,
  gatePos() { return new THREE.Vector3(0, 0, parkHalf() + 3); },
  randomParkPoint() { const h = parkHalf() - 3; return new THREE.Vector3((Math.random() * 2 - 1) * h, 0, (Math.random() * 2 - 1) * h); },
  maxGuests(G) {
    const stars = G.totalStars();
    const shops = G.buildings.filter(b => b.def.earn > 0).length;
    return Math.min(60, 6 + stars * 3 + shops * 2 + G.rides.filter(r => r.open).length * 4);
  },
  spawn(G) {
    const g = new Guest(this.gatePos()); g.setTarget(this.randomParkPoint());
    World.scene.add(g.group); this.list.push(g); return g;
  },
  update(G, dt, t) {
    this.spawnTimer -= dt;
    if (this.spawnTimer <= 0) { this.spawnTimer = 1.5 + Math.random() * 2.5; if (this.list.length < this.maxGuests(G)) this.spawn(G); G.stats.guestsVisited = (G.stats.guestsVisited || 0) + (this.list.length < this.maxGuests(G) ? 1 : 0); }
    for (let i = this.list.length - 1; i >= 0; i--) {
      const g = this.list[i];
      if (g.bubble) { g.bubbleT -= dt; if (g.bubbleT <= 0) { g.group.remove(g.bubble); g.bubble.material.map.dispose(); g.bubble.material.dispose(); g.bubble = null; } }
      if (g.balloon) g.balloon.position.x = 0.4 + Math.sin(t * 2 + g.id) * 0.15;
      if (g.state === 'riding') continue; // vehicle moves us
      g.life -= dt;
      this.think(G, g, dt, t);
      if (g.state === 'gone') { g.dispose(); this.list.splice(i, 1); }
    }
  },
  walkTo(g, dt, t) {
    if (!g.target) return true;
    const d = g.target.clone().sub(g.group.position); d.y = 0; const dist = d.length();
    if (dist < 0.3) return true;
    d.normalize(); g.group.position.addScaledVector(d, Math.min(dist, g.speed * dt));
    g.group.rotation.y = Math.atan2(d.x, d.z);
    g.walkT += dt * 10; g.group.position.y = Math.abs(Math.sin(g.walkT)) * 0.08; g.body.rotation.z = Math.sin(g.walkT) * 0.06;
    return false;
  },
  think(G, g, dt, t) {
    switch (g.state) {
      case 'wander': {
        if (this.walkTo(g, dt, t)) {
          g.body.rotation.z = 0; g.group.position.y = 0;
          g.timer = 0.5 + Math.random() * 2; g.state = 'idle';
        }
        break;
      }
      case 'idle': {
        g.timer -= dt; if (g.timer > 0) break;
        if (g.life <= 0) { g.state = 'leaving'; g.setTarget(this.gatePos()); break; }
        // choose: open ride, shop, or wander
        const rides = G.rides.filter(r => r.open && r.queue.length < 10);
        const shops = G.buildings.filter(b => b.def.earn > 0 && !g.visited.has(b.id));
        const r = Math.random();
        if (rides.length && r < 0.45) {
          const ride = rides[(Math.random() * rides.length) | 0];
          g.ride = ride; g.state = 'toQueue'; g.setTarget(queueSpot(ride, ride.queue.length));
        } else if (shops.length && r < 0.85) {
          const b = shops[(Math.random() * shops.length) | 0]; g.building = b; g.state = 'toShop'; g.setTarget(b.door);
        } else { g.state = 'wander'; g.setTarget(this.randomParkPoint()); }
        break;
      }
      case 'toShop': {
        if (this.walkTo(g, dt, t)) { g.state = 'shopping'; g.timer = 1.5 + Math.random(); g.group.position.y = 0; g.group.lookAt(g.building.center.x, 0, g.building.center.z); }
        break;
      }
      case 'shopping': {
        g.timer -= dt; if (g.timer > 0) break;
        const b = g.building; const def = b.def;
        if (b.group && b.group.parent) { // still exists
          G.earn(def.earn, b.door.clone().setY(3), def.icon); b.earned += def.earn; b.visitors++; g.visited.add(b.id);
          G.stats.shopSales = (G.stats.shopSales || 0) + 1;
          if (def.gift === 'balloon') g.giveBalloon(); else g.say(def.gift || '😊');
          g.happy++;
        }
        g.building = null; g.state = 'wander'; g.setTarget(this.randomParkPoint());
        break;
      }
      case 'toQueue': {
        const ride = g.ride;
        if (!ride || !ride.open) { g.state = 'wander'; g.ride = null; g.setTarget(this.randomParkPoint()); break; }
        if (this.walkTo(g, dt, t)) { g.state = 'queue'; ride.queue.push(g); g.queueIndex = ride.queue.length - 1; g.group.position.y = 0; }
        break;
      }
      case 'queue': {
        const ride = g.ride;
        if (!ride || !ride.open) { g.state = 'wander'; g.ride = null; g.setTarget(this.randomParkPoint()); break; }
        const idx = ride.queue.indexOf(g);
        if (idx >= 0) { const spot = queueSpot(ride, idx); g.setTarget(spot); this.walkTo(g, dt, t); }
        break;
      }
      case 'unloading': {
        if (this.walkTo(g, dt, t)) { g.state = 'idle'; g.timer = 0.5; }
        break;
      }
      case 'leaving': {
        if (this.walkTo(g, dt, t)) g.state = 'gone';
        break;
      }
    }
  },
  /** called by ride when its vehicle is at the station with `seats` free */
  board(G, ride, vehicle) {
    let n = 0;
    while (ride.queue.length && vehicle.riders.length < vehicle.seats.length) {
      const g = ride.queue.shift(); const seat = vehicle.seats[vehicle.riders.length];
      g.state = 'riding'; g.seat = seat; vehicle.riders.push(g);
      seat.add(g.group); g.group.position.set(0, 0, 0); g.group.rotation.set(0, 0, 0); g.body.rotation.z = 0;
      n++;
    }
    return n;
  },
  unload(G, ride, vehicle) {
    const s = ride.station; const d = DIRS[s.h]; const C = cellCenter(s.cx, s.cz);
    const side = new THREE.Vector3(-d.z, 0, d.x); // right side exit
    for (const g of vehicle.riders) {
      const wp = new THREE.Vector3(); g.group.getWorldPosition(wp);
      g.seat.remove(g.group); World.scene.add(g.group); g.group.position.set(wp.x, 0, wp.z); g.group.rotation.set(0, 0, 0);
      g.state = 'unloading'; g.seat = null; g.happy += ride.stars; g.ride = null;
      g.setTarget(C.clone().addScaledVector(side, 3.5 + Math.random() * 2).addScaledVector(new THREE.Vector3(d.x, 0, d.z), (Math.random() - 0.5) * 4));
      g.say(['🎉', '😄', '🤩', '❤️', '🙌'][(Math.random() * 5) | 0], 3);
      ride.ridersServed++; G.stats.ridersServed = (G.stats.ridersServed || 0) + 1;
    }
    const n = vehicle.riders.length;
    vehicle.riders = [];
    return n;
  },
  clearRide(ride) {
    for (const g of this.list) if (g.ride === ride) {
      if (g.state === 'riding') { const wp = new THREE.Vector3(); g.group.getWorldPosition(wp); if (g.seat) g.seat.remove(g.group); World.scene.add(g.group); g.group.position.set(wp.x, 0, wp.z); }
      g.state = 'wander'; g.ride = null; g.seat = null; g.setTarget(this.randomParkPoint());
    }
    ride.queue = [];
  },
  clearBuilding(b) { for (const g of this.list) if (g.building === b) { g.building = null; g.state = 'wander'; g.setTarget(this.randomParkPoint()); } },
  clearAll() { for (const g of this.list) g.dispose(); this.list = []; },
};

/** queue spot i for a ride: a line on the left side of the station, heading backwards */
function queueSpot(ride, i) {
  const s = ride.station; const d = DIRS[s.h]; const C = cellCenter(s.cx, s.cz);
  const left = new THREE.Vector3(d.z, 0, -d.x);
  return C.clone().addScaledVector(left, 3.2).addScaledVector(new THREE.Vector3(d.x, 0, d.z), 1.0 - i * 0.9);
}
