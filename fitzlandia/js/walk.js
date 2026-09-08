/* FitzLandia — walk.js
   First-person "visitor" mode: walk the park with a joystick, look around, ride any ride. */
'use strict';

const Walk = {
  active: false, pos: new THREE.Vector3(0, 0, 0), yaw: 0, pitch: -0.05,
  move: { x: 0, y: 0 }, keys: {}, speed: 7,
  state: 'walk',          // walk | waiting | riding | attached
  ride: null, seat: null, attach: null, near: null, nearKey: '', rideTimer: 0,
  eye: 1.5,

  enter() {
    this.active = true; this.state = 'walk'; this.ride = null; this.seat = null; this.attach = null;
    this.pos.set(0, 0, parkHalf() - 5); this.yaw = 0; this.pitch = -0.05;
    World.camera.fov = 70; World.camera.updateProjectionMatrix();
    World.customCam = () => this.cameraUpdate();
    World.dragHook = (dx, dy) => { this.yaw -= dx * 0.0045; this.pitch = THREE.MathUtils.clamp(this.pitch - dy * 0.0035, -1.2, 1.2); return true; };
    World.rideCam = null;
    document.getElementById('joy').hidden = false;
    document.getElementById('camBtns').hidden = true;
  },
  exit() {
    this.active = false; this.unboard(true);
    World.camera.fov = 50; World.camera.updateProjectionMatrix();
    World.customCam = null; World.dragHook = null;
    document.getElementById('joy').hidden = true;
    document.getElementById('camBtns').hidden = false;
  },
  forward() { return new THREE.Vector3(-Math.sin(this.yaw), 0, -Math.cos(this.yaw)); },
  right() { return new THREE.Vector3(Math.cos(this.yaw), 0, -Math.sin(this.yaw)); },

  update(dt) {
    if (!this.active) return;
    if (this.state === 'walk') {
      let mx = this.move.x, my = this.move.y;
      const k = this.keys;
      if (k.KeyW || k.ArrowUp) my += 1; if (k.KeyS || k.ArrowDown) my -= 1;
      if (k.KeyA) mx -= 1; if (k.KeyD) mx += 1;
      if (k.ArrowLeft) this.yaw += 1.8 * dt; if (k.ArrowRight) this.yaw -= 1.8 * dt;
      const len = Math.hypot(mx, my); if (len > 1) { mx /= len; my /= len; }
      if (len > 0.01) {
        this.pos.addScaledVector(this.forward(), my * this.speed * dt).addScaledVector(this.right(), mx * this.speed * dt);
        this.bob = (this.bob || 0) + dt * 9 * Math.min(1, len);
      }
      const lim = parkHalf() - 0.8;
      this.pos.x = THREE.MathUtils.clamp(this.pos.x, -lim, lim); this.pos.z = THREE.MathUtils.clamp(this.pos.z, -lim, lim);
      this.collide();
      this.findNear();
    } else if (this.state === 'waiting') {
      const v = this.ride && this.ride.vehicle;
      if (!this.ride || !this.ride.open) { this.unboard(true); toast('That ride closed!'); }
      else if (v && v.mode === 'loading' && v.timer > 0.6) this.board();
    } else if (this.state === 'attached' && this.attach) {
      this.attach.timer -= dt;
      if (this.attach.timer <= 0) { this.unboard(); toast('🎡 What a view! 🌆', 2500, 'gold'); }
    }
  },
  collide() {
    const p = this.pos, r = 0.6;
    for (const b of G.buildings) {
      const s = b.size; const minx = b.cx * CELL - 0.2, maxx = (b.cx + s) * CELL + 0.2, minz = b.cz * CELL - 0.2, maxz = (b.cz + s) * CELL + 0.2;
      if (p.x + r > minx && p.x - r < maxx && p.z + r > minz && p.z - r < maxz) {
        const dl = p.x + r - minx, dr = maxx - (p.x - r), dn = p.z + r - minz, ds = maxz - (p.z - r);
        const m = Math.min(dl, dr, dn, ds);
        if (m === dl) p.x = minx - r; else if (m === dr) p.x = maxx + r; else if (m === dn) p.z = minz - r; else p.z = maxz + r;
      }
    }
  },
  findNear() {
    let best = null, bestD = 99;
    for (const r of G.rides) { const c = cellCenter(r.station.cx, r.station.cz); const d = c.distanceTo(this.pos); if (d < 7 && d < bestD) { best = { kind: 'ride', ride: r, key: 'r' + r.id }; bestD = d; } }
    for (const b of G.buildings) {
      if (b.def.kind === 'deco') continue;
      const d = b.door.distanceTo(this.pos); const lim = b.def.kind === 'attraction' ? 8 : 5;
      if (d < lim && d < bestD) { best = { kind: b.def.kind === 'attraction' ? 'attraction' : 'shop', building: b, key: 'b' + b.id }; bestD = d; }
    }
    const key = best ? best.key : '';
    if (key !== this.nearKey) { this.nearKey = key; this.near = best; renderContext(); }
  },
  // ---- rides ----
  requestRide(r) {
    if (!r.open) { toast('This ride is not open yet! Build and test it first. 🔧'); return; }
    this.ride = r; this.state = 'waiting'; toast(`⏳ Waiting for ${r.name} to come into the station…`, 2500); renderContext();
  },
  board() {
    const v = this.ride.vehicle; this.seat = v.seats[0]; this.state = 'riding'; this.rideTimer = 0;
    Audio_.cheer(); toast(`🎢 Here we go! Hold on! 🙌`, 2000, 'gold'); renderContext();
  },
  rideAttraction(b) {
    if (!b.seats || !b.seats.length) return;
    this.attach = { obj: b.seats[(Math.random() * b.seats.length) | 0], offset: b.type === 'ferris' ? new THREE.Vector3(0, -0.3, 0) : new THREE.Vector3(0, 2.0, 0), timer: b.type === 'ferris' ? 26 : 16, building: b };
    this.state = 'attached'; this.yaw = 0; this.pitch = 0; Audio_.cheer(); toast(`${b.def.icon} Enjoy the ride!`, 2000, 'gold'); renderContext();
  },
  visitShop(b) {
    const lines = { candy: '🍭 Yum! A giant lollipop!', icecream: '🍦 Mmm, chocolate swirl!', toy: '🧸 You got a fluffy teddy bear!', balloon: '🎈 A big red balloon! Hold on tight!', ringtoss: '🎯 Ring toss… and you WIN a prize! 🏆', duckpond: '🦆 You picked the lucky duck! 🏆' };
    toast(lines[b.type] || (b.def.icon + ' Fun!'), 2600, 'gold'); Audio_.coin(); b.visitors++;
    Particles.emit(b.door.clone().setY(2.5), 25, { spread: 4, up: 5, life: 0.9, color: [0xff3d6e, 0xffd11a, 0x2ecc71, 0x1e90ff], size: 0.6 });
  },
  unboard(silent) {
    if (this.state === 'riding' || this.state === 'waiting') {
      const r = this.ride; if (r) { const s = r.station; const d = DIRS[s.h]; const c = cellCenter(s.cx, s.cz); this.pos.set(c.x - d.z * 3.5 + d.x * 2, 0, c.z + d.x * 3.5 + d.z * 2); this.yaw = Math.atan2(-(c.x - this.pos.x), -(c.z - this.pos.z)); }
      if (!silent && r) { toast(`🎉 ${r.name} was ${starStr(r.stars)}! Go again?`, 3000, 'gold'); Audio_.cheer(); }
    }
    if (this.state === 'attached' && this.attach) { const b = this.attach.building; if (b) { const d = b.door; this.pos.set(d.x, 0, d.z + 1.5); this.yaw = 0; } }
    this.state = 'walk'; this.ride = null; this.seat = null; this.attach = null; this.pitch = -0.05;
    if (this.active) renderContext();
  },
  /** called by the ride loop when its train arrives at the station */
  onRideArrived(r) { if (this.state === 'riding' && this.ride === r) this.unboard(); },

  // ---- camera ----
  _q: new THREE.Quaternion(), _e: new THREE.Euler(), _p: new THREE.Vector3(), _flip: new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0, 1, 0), Math.PI),
  cameraUpdate() {
    const cam = World.camera;
    if (this.state === 'riding' && this.seat) {
      this.seat.getWorldPosition(this._p); this.seat.getWorldQuaternion(this._q);
      const off = new THREE.Vector3(0, 0.75, 0.25).applyQuaternion(this._q);
      cam.position.copy(this._p).add(off);
      const look = new THREE.Quaternion().setFromEuler(this._e.set(this.pitch, this.yaw, 0, 'YXZ'));
      cam.quaternion.copy(this._q).multiply(this._flip).multiply(look);
      const v = this.ride && this.ride.vehicle; if (v) Audio_.setWhoosh(v.v);
      return;
    }
    if (this.state === 'attached' && this.attach) {
      const o = this.attach.obj; o.getWorldPosition(this._p); o.getWorldQuaternion(this._q);
      cam.position.copy(this._p).add(this.attach.offset.clone().applyQuaternion(this._q));
      const look = new THREE.Quaternion().setFromEuler(this._e.set(this.pitch, this.yaw, 0, 'YXZ'));
      cam.quaternion.copy(this._q).multiply(look);
      return;
    }
    const bob = Math.sin(this.bob || 0) * 0.05;
    cam.position.set(this.pos.x, this.eye + bob, this.pos.z);
    cam.quaternion.setFromEuler(this._e.set(this.pitch, this.yaw, 0, 'YXZ'));
    Audio_.setWhoosh(0);
  },
};

// ---- joystick + keyboard ----
function initJoystick() {
  const joy = document.getElementById('joy'), knob = document.getElementById('joyKnob');
  let id = null, cx = 0, cy = 0; const R = 46;
  const set = (x, y) => { knob.style.transform = `translate(${x}px, ${y}px)`; Walk.move.x = x / R; Walk.move.y = -y / R; };
  joy.addEventListener('pointerdown', e => { id = e.pointerId; joy.setPointerCapture(id); const r = joy.getBoundingClientRect(); cx = r.left + r.width / 2; cy = r.top + r.height / 2; e.preventDefault(); });
  joy.addEventListener('pointermove', e => { if (e.pointerId !== id) return; let x = e.clientX - cx, y = e.clientY - cy; const l = Math.hypot(x, y); if (l > R) { x *= R / l; y *= R / l; } set(x, y); });
  const end = e => { if (e.pointerId !== id) return; id = null; set(0, 0); };
  joy.addEventListener('pointerup', end); joy.addEventListener('pointercancel', end);
  window.addEventListener('keydown', e => { if (e.target.tagName === 'INPUT') return; Walk.keys[e.code] = true; if (Walk.active && ['ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight', 'Space'].includes(e.code)) e.preventDefault(); });
  window.addEventListener('keyup', e => { Walk.keys[e.code] = false; });
}
