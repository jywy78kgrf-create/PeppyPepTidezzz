/* FitzLandia — spooky.js
   The Spooky House: a walk-through haunted mansion with rooms, props, lightning and jump scares.
   Rendered in its own dark scene while the player is inside. */
'use strict';

const Spooky = {
  scene: null, built: false, active: false, building: null, savedPos: null,
  cells: new Set(), scares: [], anims: [], lights: [], flicker: 0, shake: 0, t: 0, heartT: 0, thunderT: 6, blackout: 0,
  C: 4,
  // main route (scares trigger on these, in order) + extra room cells that are walkable
  route: [[0,0],[0,1],[0,2],[1,2],[2,2],[2,1],[2,0],[3,0],[4,0],[4,1],[4,2],[4,3],[3,3],[2,3],[1,3],[0,3],[0,4],[0,5],[1,5],[2,5],[3,5],[4,5],[5,5],[6,5]],
  extras: [[1,1],[3,1],[3,2],[5,3],[5,4],[6,4],[1,4]],

  key(x, z) { return x + ',' + z; },
  center(x, z) { return new THREE.Vector3((x + 0.5) * this.C, 0, (z + 0.5) * this.C); },

  // ---------- canvas art for the scare faces ----------
  art: {},
  makeArt() {
    const A = this.art; if (A.ghost) return;
    A.ghost = canvasTex(256, 320, (ctx, w, h) => {
      const g = ctx.createRadialGradient(128, 130, 20, 128, 150, 150); g.addColorStop(0, '#ffffff'); g.addColorStop(0.7, '#d8dcff'); g.addColorStop(1, 'rgba(180,190,255,0)');
      ctx.fillStyle = g; ctx.beginPath(); ctx.ellipse(128, 130, 105, 125, 0, 0, 6.3); ctx.fill();
      ctx.fillStyle = '#e4e8ff'; ctx.beginPath(); ctx.moveTo(30, 200); for (let i = 0; i <= 6; i++) ctx.lineTo(30 + i * 33, 200 + (i % 2 ? 90 : 40)); ctx.lineTo(226, 200); ctx.fill();
      for (const ex of [88, 168]) { const eg = ctx.createRadialGradient(ex, 115, 4, ex, 115, 30); eg.addColorStop(0, '#ff2020'); eg.addColorStop(0.5, '#300'); eg.addColorStop(1, '#000'); ctx.fillStyle = eg; ctx.beginPath(); ctx.ellipse(ex, 115, 28, 36, ex < 128 ? -0.3 : 0.3, 0, 6.3); ctx.fill(); }
      ctx.fillStyle = '#05000a'; ctx.beginPath(); ctx.ellipse(128, 195, 34, 52, 0, 0, 6.3); ctx.fill();
      ctx.fillStyle = '#fff'; for (let i = 0; i < 5; i++) { ctx.beginPath(); ctx.moveTo(100 + i * 14, 150); ctx.lineTo(107 + i * 14, 168); ctx.lineTo(114 + i * 14, 150); ctx.fill(); }
    });
    A.zombie = canvasTex(256, 256, (ctx, w, h) => {
      ctx.fillStyle = '#5f9a3a'; ctx.beginPath(); ctx.ellipse(128, 128, 96, 110, 0, 0, 6.3); ctx.fill();
      ctx.fillStyle = '#3f6a26'; for (let i = 0; i < 12; i++) { ctx.beginPath(); ctx.arc(40 + Math.random() * 176, 40 + Math.random() * 176, 4 + Math.random() * 8, 0, 6.3); ctx.fill(); }
      for (const ex of [90, 166]) { ctx.fillStyle = '#fff6a8'; ctx.beginPath(); ctx.ellipse(ex, 105, 26, 20, 0, 0, 6.3); ctx.fill(); ctx.fillStyle = '#000'; ctx.beginPath(); ctx.arc(ex + (ex < 128 ? 6 : -6), 108, 8, 0, 6.3); ctx.fill(); }
      ctx.strokeStyle = '#222'; ctx.lineWidth = 6; ctx.beginPath(); ctx.moveTo(70, 180); ctx.quadraticCurveTo(128, 215, 186, 180); ctx.stroke();
      for (let i = 0; i < 6; i++) { ctx.beginPath(); ctx.moveTo(80 + i * 20, 170); ctx.lineTo(80 + i * 20, 205); ctx.stroke(); }
      ctx.fillStyle = '#7a1c1c'; ctx.beginPath(); ctx.moveTo(150, 40); ctx.lineTo(200, 70); ctx.lineTo(170, 90); ctx.fill();
    });
    A.vampire = canvasTex(256, 320, (ctx, w, h) => {
      ctx.fillStyle = '#0b0010'; ctx.beginPath(); ctx.moveTo(10, 320); ctx.lineTo(60, 150); ctx.lineTo(128, 190); ctx.lineTo(196, 150); ctx.lineTo(246, 320); ctx.fill();
      ctx.fillStyle = '#e8e2f0'; ctx.beginPath(); ctx.ellipse(128, 120, 74, 90, 0, 0, 6.3); ctx.fill();
      ctx.fillStyle = '#111'; ctx.beginPath(); ctx.moveTo(54, 60); ctx.quadraticCurveTo(128, 0, 202, 60); ctx.lineTo(202, 80); ctx.lineTo(128, 45); ctx.lineTo(54, 80); ctx.fill();
      for (const ex of [98, 158]) { ctx.fillStyle = '#ff2a2a'; ctx.beginPath(); ctx.ellipse(ex, 110, 16, 11, 0, 0, 6.3); ctx.fill(); ctx.fillStyle = '#000'; ctx.beginPath(); ctx.arc(ex, 110, 5, 0, 6.3); ctx.fill(); ctx.strokeStyle = '#111'; ctx.lineWidth = 5; ctx.beginPath(); ctx.moveTo(ex - 20, 90 + (ex < 128 ? 0 : 8)); ctx.lineTo(ex + 20, 90 + (ex < 128 ? 8 : 0)); ctx.stroke(); }
      ctx.fillStyle = '#5a0010'; ctx.beginPath(); ctx.ellipse(128, 168, 30, 16, 0, 0, Math.PI); ctx.fill();
      ctx.fillStyle = '#fff'; for (const fx of [110, 146]) { ctx.beginPath(); ctx.moveTo(fx - 6, 166); ctx.lineTo(fx, 192); ctx.lineTo(fx + 6, 166); ctx.fill(); }
    });
    A.witch = canvasTex(320, 200, (ctx, w, h) => {
      const mg = ctx.createRadialGradient(160, 100, 40, 160, 100, 110); mg.addColorStop(0, '#fff6c8'); mg.addColorStop(0.75, '#ffe07a'); mg.addColorStop(1, 'rgba(255,220,120,0)');
      ctx.fillStyle = mg; ctx.beginPath(); ctx.arc(160, 100, 110, 0, 6.3); ctx.fill();
      ctx.fillStyle = '#000'; ctx.fillRect(40, 118, 200, 8); ctx.beginPath(); ctx.moveTo(235, 108); ctx.lineTo(310, 100); ctx.lineTo(310, 145); ctx.lineTo(235, 136); ctx.fill();
      ctx.beginPath(); ctx.moveTo(90, 120); ctx.lineTo(130, 40); ctx.lineTo(180, 120); ctx.fill(); ctx.fillRect(105, 38, 55, 6); ctx.beginPath(); ctx.moveTo(115, 40); ctx.lineTo(145, 0); ctx.lineTo(150, 42); ctx.fill();
      ctx.fillStyle = '#7ed957'; ctx.beginPath(); ctx.arc(135, 58, 14, 0, 6.3); ctx.fill(); ctx.fillStyle = '#000'; ctx.beginPath(); ctx.arc(130, 55, 2.5, 0, 6.3); ctx.arc(140, 55, 2.5, 0, 6.3); ctx.fill();
    });
    A.boo = canvasTex(512, 512, (ctx, w, h) => {
      const g = ctx.createRadialGradient(256, 256, 40, 256, 256, 250); g.addColorStop(0, '#ffffff'); g.addColorStop(0.6, '#cfd6ff'); g.addColorStop(1, 'rgba(120,140,255,0)');
      ctx.fillStyle = g; ctx.beginPath(); ctx.arc(256, 256, 250, 0, 6.3); ctx.fill();
      for (const ex of [170, 342]) { const eg = ctx.createRadialGradient(ex, 200, 10, ex, 200, 70); eg.addColorStop(0, '#ff4040'); eg.addColorStop(0.4, '#500'); eg.addColorStop(1, '#000'); ctx.fillStyle = eg; ctx.beginPath(); ctx.ellipse(ex, 200, 62, 78, ex < 256 ? -0.35 : 0.35, 0, 6.3); ctx.fill(); }
      ctx.fillStyle = '#000'; ctx.beginPath(); ctx.ellipse(256, 370, 95, 110, 0, 0, 6.3); ctx.fill();
      ctx.fillStyle = '#fff'; for (let i = 0; i < 7; i++) { ctx.beginPath(); ctx.moveTo(180 + i * 24, 275); ctx.lineTo(192 + i * 24, 310); ctx.lineTo(204 + i * 24, 275); ctx.fill(); }
      ctx.fillStyle = '#c00'; ctx.beginPath(); ctx.ellipse(256, 430, 40, 30, 0, 0, 6.3); ctx.fill();
    });
    A.eyes = canvasTex(128, 64, (ctx) => { for (const ex of [32, 96]) { const g = ctx.createRadialGradient(ex, 32, 2, ex, 32, 22); g.addColorStop(0, '#fff'); g.addColorStop(0.3, '#ff3030'); g.addColorStop(1, 'rgba(255,0,0,0)'); ctx.fillStyle = g; ctx.beginPath(); ctx.arc(ex, 32, 22, 0, 6.3); ctx.fill(); } });
    A.window = canvasTex(128, 192, (ctx, w, h) => { const g = ctx.createLinearGradient(0, 0, 0, h); g.addColorStop(0, '#0a1030'); g.addColorStop(1, '#1a2050'); ctx.fillStyle = g; ctx.fillRect(0, 0, w, h); ctx.fillStyle = '#fff8d0'; ctx.beginPath(); ctx.arc(80, 50, 22, 0, 6.3); ctx.fill(); ctx.fillStyle = '#0a1030'; ctx.beginPath(); ctx.arc(90, 44, 18, 0, 6.3); ctx.fill(); ctx.fillStyle = '#000'; for (let i = 0; i < 5; i++) { ctx.beginPath(); ctx.moveTo(10 + i * 25, 192); ctx.lineTo(20 + i * 25, 120 + Math.random() * 40); ctx.lineTo(35 + i * 25, 192); ctx.fill(); } ctx.strokeStyle = '#2a1a10'; ctx.lineWidth = 8; ctx.strokeRect(4, 4, w - 8, h - 8); ctx.beginPath(); ctx.moveTo(w / 2, 0); ctx.lineTo(w / 2, h); ctx.moveTo(0, h / 2); ctx.lineTo(w, h / 2); ctx.stroke(); });
    A.grave = canvasTex(128, 160, (ctx, w, h) => { ctx.fillStyle = '#8a8f96'; ctx.beginPath(); ctx.moveTo(10, h); ctx.lineTo(10, 50); ctx.arc(64, 50, 54, Math.PI, 0); ctx.lineTo(118, h); ctx.fill(); ctx.fillStyle = '#3a3f46'; ctx.font = 'bold 34px sans-serif'; ctx.textAlign = 'center'; ctx.fillText('RIP', 64, 80); ctx.font = '22px sans-serif'; ctx.fillText(['BOO', 'YIKES', 'ZZZ', 'EEK'][(Math.random() * 4) | 0], 64, 115); });
    A.clock = canvasTex(128, 128, (ctx, w, h) => { ctx.fillStyle = '#f2e8c8'; ctx.beginPath(); ctx.arc(64, 64, 58, 0, 6.3); ctx.fill(); ctx.strokeStyle = '#222'; ctx.lineWidth = 4; ctx.stroke(); for (let i = 0; i < 12; i++) { const a = i / 6 * Math.PI; ctx.beginPath(); ctx.moveTo(64 + Math.cos(a) * 46, 64 + Math.sin(a) * 46); ctx.lineTo(64 + Math.cos(a) * 54, 64 + Math.sin(a) * 54); ctx.stroke(); } ctx.lineWidth = 5; ctx.beginPath(); ctx.moveTo(64, 64); ctx.lineTo(64, 24); ctx.moveTo(64, 64); ctx.lineTo(92, 64); ctx.stroke(); });
    A.portrait = (variant) => canvasTex(128, 160, (ctx, w, h) => { ctx.fillStyle = '#7a5a2a'; ctx.fillRect(0, 0, w, h); ctx.fillStyle = '#c9a15a'; ctx.fillRect(6, 6, w - 12, h - 12); ctx.fillStyle = '#20202a'; ctx.fillRect(12, 12, w - 24, h - 24); ctx.fillStyle = variant === 2 ? '#9fd48a' : '#e0d6c8'; ctx.beginPath(); ctx.ellipse(w / 2, 78, 30, 40, 0, 0, 6.3); ctx.fill(); ctx.fillStyle = '#3a2a1a'; ctx.beginPath(); ctx.ellipse(w / 2, 46, 32, 16, 0, 0, 6.3); ctx.fill(); ctx.fillStyle = variant === 2 ? '#ff2020' : '#111'; ctx.beginPath(); ctx.arc(w / 2 - 12, 74, 5, 0, 6.3); ctx.arc(w / 2 + 12, 74, 5, 0, 6.3); ctx.fill(); ctx.strokeStyle = '#111'; ctx.lineWidth = 3; ctx.beginPath(); if (variant === 2) { ctx.arc(w / 2, 100, 12, 0, Math.PI); } else if (variant === 1) { ctx.arc(w / 2, 108, 10, Math.PI, 0); } else { ctx.moveTo(w / 2 - 10, 104); ctx.lineTo(w / 2 + 10, 104); } ctx.stroke(); });
  },

  build() {
    if (this.built) return; this.built = true; this.makeArt();
    const sc = new THREE.Scene(); sc.background = new THREE.Color(0x07040c); sc.fog = new THREE.Fog(0x120a1c, 6, 42); this.scene = sc;
    sc.add(new THREE.AmbientLight(0x8a7ab0, 2.6));
    const moon = new THREE.DirectionalLight(0x8090ff, 0.6); moon.position.set(-10, 20, -6); sc.add(moon);
    const C = this.C, H = 4.4;
    for (const [x, z] of this.route.concat(this.extras)) this.cells.add(this.key(x, z));
    // materials
    const wallTex = canvasTex(256, 256, (ctx, w, h) => {
      ctx.fillStyle = '#4d2f66'; ctx.fillRect(0, 0, w, h);
      ctx.strokeStyle = 'rgba(255,220,255,0.10)'; ctx.lineWidth = 2; for (let i = 0; i < 8; i++) for (let j = 0; j < 8; j++) { ctx.beginPath(); ctx.moveTo(i * 32 + 16, j * 32); ctx.lineTo(i * 32 + 32, j * 32 + 16); ctx.lineTo(i * 32 + 16, j * 32 + 32); ctx.lineTo(i * 32, j * 32 + 16); ctx.closePath(); ctx.stroke(); }
      ctx.fillStyle = 'rgba(0,0,0,0.35)'; ctx.fillRect(0, 0, w, 14); ctx.fillRect(0, h - 40, w, 40); ctx.fillStyle = '#3a2a22'; ctx.fillRect(0, h - 44, w, 8);
      for (let i = 0; i < 25; i++) { ctx.strokeStyle = 'rgba(0,0,0,.35)'; ctx.beginPath(); const x = Math.random() * w, y = Math.random() * h; ctx.moveTo(x, y); ctx.lineTo(x + Math.random() * 30 - 15, y + Math.random() * 40); ctx.stroke(); }
    }, { repeat: [1, 1] });
    const floorTex = canvasTex(128, 128, (ctx, w, h) => { for (let y = 0; y < 2; y++) for (let x = 0; x < 2; x++) { ctx.fillStyle = (x + y) % 2 ? '#4a3d52' : '#2b2232'; ctx.fillRect(x * 64, y * 64, 64, 64); } ctx.strokeStyle = 'rgba(0,0,0,.4)'; ctx.lineWidth = 2; ctx.strokeRect(0, 0, 64, 64); ctx.strokeRect(64, 64, 64, 64); }, { repeat: [2, 2] });
    const webTex = canvasTex(128, 128, (ctx) => { ctx.strokeStyle = 'rgba(235,235,245,.8)'; ctx.lineWidth = 1.3; for (let i = 0; i < 9; i++) { const a = i / 8 * Math.PI / 2; ctx.beginPath(); ctx.moveTo(0, 0); ctx.lineTo(Math.cos(a) * 128, Math.sin(a) * 128); ctx.stroke(); } for (let r = 16; r < 128; r += 18) { ctx.beginPath(); for (let i = 0; i <= 8; i++) { const a = i / 8 * Math.PI / 2; const rr = r * (0.9 + 0.1 * (i % 2)); ctx.lineTo(Math.cos(a) * rr, Math.sin(a) * rr); } ctx.stroke(); } });
    const wallMat = new THREE.MeshStandardMaterial({ map: wallTex, roughness: 0.95 });
    const floorMat = new THREE.MeshStandardMaterial({ map: floorTex, roughness: 0.85 });
    const ceilMat = new THREE.MeshStandardMaterial({ color: 0x2a2036, roughness: 1 });
    const woodMat = new THREE.MeshStandardMaterial({ color: 0x4a2f1e, roughness: 0.9 });
    const boneMat = new THREE.MeshStandardMaterial({ color: 0xf2f2e6, roughness: 0.6 });
    this.windows = [];
    const rnd = mulberry(77);
    for (const [x, z] of this.route.concat(this.extras)) {
      const c = this.center(x, z);
      const f = new THREE.Mesh(new THREE.PlaneGeometry(C, C), floorMat); f.rotation.x = -Math.PI / 2; f.position.set(c.x, 0, c.z); sc.add(f);
      const ce = new THREE.Mesh(new THREE.PlaneGeometry(C, C), ceilMat); ce.rotation.x = Math.PI / 2; ce.position.set(c.x, H, c.z); sc.add(ce);
      for (const [dx, dz] of [[1, 0], [-1, 0], [0, 1], [0, -1]]) {
        if (this.cells.has(this.key(x + dx, z + dz))) continue;
        const yaw = Math.atan2(-dx, -dz);
        const w = new THREE.Mesh(new THREE.PlaneGeometry(C, H), wallMat); w.position.set(c.x + dx * C / 2, H / 2, c.z + dz * C / 2); w.rotation.y = yaw; sc.add(w);
        const r = rnd();
        if (r < 0.22) { // window with moonlit sky
          const win = new THREE.Mesh(new THREE.PlaneGeometry(1.3, 1.9), new THREE.MeshStandardMaterial({ map: this.art.window, emissive: 0xffffff, emissiveMap: this.art.window, emissiveIntensity: 0.9 }));
          win.position.set(c.x + dx * (C / 2 - 0.04), 2.5, c.z + dz * (C / 2 - 0.04)); win.rotation.y = yaw; sc.add(win); this.windows.push(win);
        } else if (r < 0.5) { const web = new THREE.Mesh(new THREE.PlaneGeometry(1.5, 1.5), new THREE.MeshBasicMaterial({ map: webTex, transparent: true, depthWrite: false })); web.position.set(c.x + dx * (C / 2 - 0.05) + (dz ? (rnd() - 0.5) * 2 : 0), H - 0.8, c.z + dz * (C / 2 - 0.05) + (dx ? (rnd() - 0.5) * 2 : 0)); web.rotation.y = yaw; sc.add(web); }
        else if (r < 0.62) { const chain = new THREE.Mesh(new THREE.CylinderGeometry(0.05, 0.05, 2.2 + rnd(), 6), new THREE.MeshStandardMaterial({ color: 0x777c84, metalness: 0.7, roughness: 0.5 })); chain.position.set(c.x + dx * (C / 2 - 0.35), H - 1.3, c.z + dz * (C / 2 - 0.35)); sc.add(chain); }
      }
    }
    // candles + lights
    const lightCells = [[0,1],[2,1],[3,0],[4,2],[3,3],[1,3],[0,5],[2,5],[4,5],[6,4]];
    const lcol = [0xffa040, 0xa070ff, 0xffa040, 0x40ff90, 0x40ff90, 0xffa040, 0x8090ff, 0xffa040, 0xff5060, 0xffe08a];
    lightCells.forEach(([x, z], i) => {
      const c = this.center(x, z); const l = new THREE.PointLight(lcol[i], 3.4, 19, 2); l.position.set(c.x, 3.0, c.z); l.userData.base = 3.4; sc.add(l); this.lights.push(l);
      const cand = new THREE.Group();
      for (let k = 0; k < 3; k++) { const st = new THREE.Mesh(new THREE.CylinderGeometry(0.06, 0.08, 0.5 + k * 0.1, 6), new THREE.MeshStandardMaterial({ color: 0xf1e6c8 })); st.position.set((k - 1) * 0.28, 0.25 + k * 0.05, 0); cand.add(st); const fl = new THREE.Mesh(new THREE.SphereGeometry(0.07, 6, 5), new THREE.MeshBasicMaterial({ color: 0xffd070 })); fl.position.set((k - 1) * 0.28, 0.58 + k * 0.1, 0); cand.add(fl); }
      const base = new THREE.Mesh(new THREE.CylinderGeometry(0.5, 0.6, 0.12, 8), new THREE.MeshStandardMaterial({ color: 0x8a7020, metalness: 0.6 })); cand.add(base);
      cand.position.set(c.x + 1.55, 1.05, c.z + 1.55); sc.add(cand);
      const shelf = new THREE.Mesh(new THREE.BoxGeometry(1.2, 0.1, 0.8), woodMat); shelf.position.set(c.x + 1.55, 1.0, c.z + 1.55); sc.add(shelf);
    });
    // pumpkins + skulls
    const pumpTex = canvasTex(128, 128, (ctx, w, h) => { ctx.fillStyle = '#ff7a1a'; ctx.fillRect(0, 0, w, h); ctx.fillStyle = '#ffe66b'; ctx.beginPath(); ctx.moveTo(30, 40); ctx.lineTo(50, 60); ctx.lineTo(20, 60); ctx.fill(); ctx.beginPath(); ctx.moveTo(98, 40); ctx.lineTo(108, 60); ctx.lineTo(78, 60); ctx.fill(); ctx.beginPath(); ctx.moveTo(25, 85); for (let i = 0; i <= 6; i++) ctx.lineTo(25 + i * 13, 85 + (i % 2 ? 14 : 0)); ctx.lineTo(103, 100); ctx.lineTo(25, 100); ctx.fill(); });
    for (const [x, z] of [[2,2],[4,0],[0,3],[2,5],[5,5],[1,1],[3,2]]) { const c = this.center(x, z); const p = new THREE.Mesh(new THREE.SphereGeometry(0.45, 12, 10), new THREE.MeshStandardMaterial({ map: pumpTex, emissive: 0xff6a00, emissiveIntensity: 0.5, emissiveMap: pumpTex })); p.scale.y = 0.8; p.position.set(c.x - 1.5, 0.4, c.z - 1.5); p.rotation.y = rnd() * 6; sc.add(p); }
    for (const [x, z] of [[3,0],[4,2],[1,3],[4,5]]) { const c = this.center(x, z); const sk = new THREE.Mesh(new THREE.SphereGeometry(0.25, 10, 8), boneMat); sk.position.set(c.x - 1.6, 1.3, c.z + 1.6); sc.add(sk); for (const ex of [-0.09, 0.09]) { const e = new THREE.Mesh(new THREE.SphereGeometry(0.06, 6, 5), new THREE.MeshBasicMaterial({ color: 0x000 })); e.position.set(c.x - 1.6 + ex, 1.33, c.z + 1.6 + 0.22); sc.add(e); } const sh = new THREE.Mesh(new THREE.BoxGeometry(0.7, 0.08, 0.6), woodMat); sh.position.set(c.x - 1.6, 1.0, c.z + 1.6); sc.add(sh); }
    // portraits
    this.portraits = [];
    for (const [x, z, dx, dz] of [[0,1,-1,0],[1,1,0,-1],[2,1,1,0],[4,2,1,0],[1,3,0,-1],[0,4,-1,0],[2,5,0,1],[4,5,0,-1]]) {
      const c = this.center(x, z); const g = new THREE.Group();
      const mat = new THREE.MeshStandardMaterial({ map: this.art.portrait((rnd() * 2) | 0), roughness: 0.8 });
      const pic = new THREE.Mesh(new THREE.PlaneGeometry(1.3, 1.6), mat); g.add(pic);
      const eyes = new THREE.Sprite(new THREE.SpriteMaterial({ map: this.art.eyes, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending })); eyes.scale.set(0.9, 0.45, 1); eyes.position.set(0, 0.1, 0.06); eyes.visible = false; g.add(eyes);
      g.userData.eyes = eyes; g.userData.mat = mat;
      g.position.set(c.x + dx * (C / 2 - 0.07), 2.3, c.z + dz * (C / 2 - 0.07)); g.rotation.y = Math.atan2(-dx, -dz); sc.add(g); this.portraits.push(g);
    }
    // grandfather clock in the portrait hall
    { const c = this.center(1, 1); const clk = new THREE.Group(); const body = new THREE.Mesh(new THREE.BoxGeometry(0.9, 3.2, 0.6), woodMat); body.position.y = 1.6; clk.add(body); const face = new THREE.Mesh(new THREE.PlaneGeometry(0.7, 0.7), new THREE.MeshStandardMaterial({ map: this.art.clock })); face.position.set(0, 2.6, 0.31); clk.add(face); const pend = new THREE.Mesh(new THREE.CylinderGeometry(0.02, 0.02, 1.2, 4), new THREE.MeshStandardMaterial({ color: 0xd4af37, metalness: 0.8 })); pend.position.set(0, 1.2, 0.2); const bob = new THREE.Mesh(new THREE.SphereGeometry(0.12, 8, 6), pend.material); bob.position.y = -0.6; pend.add(bob); const pg = new THREE.Group(); pg.position.set(0, 1.8, 0.2); pend.position.set(0, -0.6, 0); pg.add(pend); clk.add(pg); this.pendulum = pg; clk.position.set(c.x - 1.5, 0, c.z - 1.5); sc.add(clk); }
    // cauldron room (3,2)
    { const c = this.center(3, 2); const pot = new THREE.Mesh(new THREE.SphereGeometry(0.8, 14, 10, 0, Math.PI * 2, 0, Math.PI * 0.62), new THREE.MeshStandardMaterial({ color: 0x3a3a44, roughness: 0.35, metalness: 0.7, side: THREE.DoubleSide })); pot.rotation.x = Math.PI; pot.position.set(c.x, 1.0, c.z); sc.add(pot); const brew = new THREE.Mesh(new THREE.CircleGeometry(0.72, 16), new THREE.MeshStandardMaterial({ color: 0x3cff5a, emissive: 0x2cff40, emissiveIntensity: 0.9 })); brew.rotation.x = -Math.PI / 2; brew.position.set(c.x, 1.02, c.z); sc.add(brew); const gl = new THREE.PointLight(0x40ff60, 2.5, 8, 2); gl.position.set(c.x, 1.8, c.z); sc.add(gl); this.bubbles = []; for (let i = 0; i < 8; i++) { const b = new THREE.Mesh(new THREE.SphereGeometry(0.07, 6, 5), new THREE.MeshBasicMaterial({ color: 0x9cffb0, transparent: true, opacity: 0.8 })); b.userData = { a: rnd() * 6.3, r: rnd() * 0.5, ph: rnd() * 6 }; b.position.set(c.x, 1, c.z); sc.add(b); this.bubbles.push(b); } this.cauldronPos = c.clone(); }
    // graveyard nook (1,4)/(0,4)
    for (const [x, z, ox, oz] of [[1,4,0.8,-1.2],[1,4,-1.0,1.0],[0,4,1.2,1.3]]) { const c = this.center(x, z); const gr = new THREE.Mesh(new THREE.PlaneGeometry(0.9, 1.1), new THREE.MeshStandardMaterial({ map: this.art.grave, transparent: true, side: THREE.DoubleSide })); gr.position.set(c.x + ox, 0.55, c.z + oz); gr.rotation.y = rnd() * 0.8 - 0.4; sc.add(gr); const mound = new THREE.Mesh(new THREE.SphereGeometry(0.7, 10, 6), new THREE.MeshStandardMaterial({ color: 0x3a2a1a })); mound.scale.set(1, 0.3, 0.6); mound.position.set(c.x + ox, 0.02, c.z + oz + 0.5); sc.add(mound); }
    // coffin at (1,5) against the south wall
    { const c = this.center(1, 5); const cof = new THREE.Group(); const box = new THREE.Mesh(new THREE.BoxGeometry(1.1, 0.7, 2.4), woodMat); box.position.y = 0.35; cof.add(box); const lid = new THREE.Mesh(new THREE.BoxGeometry(1.1, 0.1, 2.4), new THREE.MeshStandardMaterial({ color: 0x5a3a22 })); lid.position.set(-0.55, 0.75, 0); lid.geometry.translate(0.55, 0, 0); cof.add(lid); this.coffinLid = lid; cof.position.set(c.x + 1.2, 0, c.z + 0.6); sc.add(cof); this.coffinPos = new THREE.Vector3(c.x + 1.2, 0.8, c.z + 0.6); }
    // bookshelf + rocking chair in the exit room
    { const c = this.center(5, 4); const shelf = new THREE.Mesh(new THREE.BoxGeometry(2.2, 3.4, 0.5), woodMat); shelf.position.set(c.x, 1.7, c.z - 1.7); sc.add(shelf); const bc = [0x8a2020, 0x204a8a, 0x2a7a3a, 0xc0a040, 0x6a2a8a]; for (let r = 0; r < 4; r++) for (let k = 0; k < 7; k++) { const bk = new THREE.Mesh(new THREE.BoxGeometry(0.22, 0.55 + rnd() * 0.2, 0.35), new THREE.MeshStandardMaterial({ color: bc[(k + r) % 5] })); bk.position.set(c.x - 0.85 + k * 0.28, 0.6 + r * 0.8, c.z - 1.45); sc.add(bk); }
      const chair = new THREE.Group(); const seat = new THREE.Mesh(new THREE.BoxGeometry(0.9, 0.1, 0.9), woodMat); seat.position.y = 0.5; chair.add(seat); const back = new THREE.Mesh(new THREE.BoxGeometry(0.9, 1.1, 0.1), woodMat); back.position.set(0, 1.05, -0.4); chair.add(back); for (const [x, z] of [[-0.4, -0.4], [0.4, -0.4], [-0.4, 0.4], [0.4, 0.4]]) { const leg = new THREE.Mesh(new THREE.BoxGeometry(0.08, 0.5, 0.08), woodMat); leg.position.set(x, 0.25, z); chair.add(leg); } for (const x of [-0.42, 0.42]) { const rk = new THREE.Mesh(new THREE.TorusGeometry(0.9, 0.04, 6, 12, 1.2), woodMat); rk.rotation.y = Math.PI / 2; rk.rotation.x = 0; rk.position.set(x, 0.9, 0); rk.rotation.z = 0; rk.rotation.set(0, Math.PI / 2, 0); rk.rotation.x = Math.PI + 0.35; chair.add(rk); }
      chair.position.set(c.x + 1.2, 0, c.z + 1.0); chair.rotation.y = -0.6; sc.add(chair); this.chair = chair; }
    // actors
    const spr = (tex, w, h) => { const s = new THREE.Sprite(new THREE.SpriteMaterial({ map: tex, transparent: true, depthWrite: false })); s.scale.set(w, h, 1); s.visible = false; sc.add(s); return s; };
    this.ghost = spr(this.art.ghost, 1.8, 2.25); this.boo = spr(this.art.boo, 3, 3); this.zombie = spr(this.art.zombie, 1.4, 1.4); this.vampire = spr(this.art.vampire, 1.7, 2.1); this.witch = spr(this.art.witch, 3.2, 2.0); this.ghost2 = spr(this.art.ghost, 1.8, 2.25);
    // skeleton (3D)
    const sk = new THREE.Group(); const skull = new THREE.Mesh(new THREE.SphereGeometry(0.34, 10, 8), boneMat); skull.position.y = 1.6; sk.add(skull);
    for (const ex of [-0.11, 0.11]) { const e = new THREE.Mesh(new THREE.SphereGeometry(0.08, 6, 5), new THREE.MeshBasicMaterial({ color: 0xff2020 })); e.position.set(ex, 1.65, 0.3); sk.add(e); }
    const jaw = new THREE.Mesh(new THREE.BoxGeometry(0.3, 0.12, 0.2), boneMat); jaw.position.set(0, 1.38, 0.15); sk.add(jaw); this.jaw = jaw;
    const spine = new THREE.Mesh(new THREE.CylinderGeometry(0.06, 0.06, 1.0, 6), boneMat); spine.position.y = 0.9; sk.add(spine);
    for (let i = 0; i < 4; i++) { const rib = new THREE.Mesh(new THREE.TorusGeometry(0.3 - i * 0.03, 0.04, 6, 12, Math.PI), boneMat); rib.rotation.x = Math.PI / 2; rib.rotation.z = Math.PI; rib.position.y = 1.3 - i * 0.18; sk.add(rib); }
    for (const sx of [-1, 1]) { const arm = new THREE.Mesh(new THREE.CylinderGeometry(0.05, 0.05, 0.9, 6), boneMat); arm.position.set(sx * 0.45, 1.05, 0.2); arm.rotation.z = sx * 0.9; arm.rotation.x = -0.8; sk.add(arm); const leg = new THREE.Mesh(new THREE.CylinderGeometry(0.06, 0.05, 0.9, 6), boneMat); leg.position.set(sx * 0.15, 0.0, 0); sk.add(leg); }
    sk.visible = false; sc.add(sk); this.skeleton = sk;
    // spider (3D)
    const sp = new THREE.Group(); const spMat = new THREE.MeshStandardMaterial({ color: 0x111111, roughness: 0.7 });
    const spBody = new THREE.Mesh(new THREE.SphereGeometry(0.42, 10, 8), spMat); spBody.position.set(0, 0, -0.1); sp.add(spBody);
    const head = new THREE.Mesh(new THREE.SphereGeometry(0.24, 8, 6), spMat); head.position.set(0, 0.05, 0.45); sp.add(head);
    for (const ex of [-0.1, 0.1, -0.04, 0.04]) { const e = new THREE.Mesh(new THREE.SphereGeometry(0.05, 6, 5), new THREE.MeshBasicMaterial({ color: 0xff3030 })); e.position.set(ex, 0.14 + (Math.abs(ex) < 0.05 ? 0.06 : 0), 0.66); sp.add(e); }
    this.spiderLegs = [];
    for (let i = 0; i < 8; i++) { const side = i < 4 ? -1 : 1; const leg = new THREE.Group(); const up = new THREE.Mesh(new THREE.CylinderGeometry(0.03, 0.03, 0.7, 4), spMat); up.position.y = 0.35; leg.add(up); const lo = new THREE.Mesh(new THREE.CylinderGeometry(0.02, 0.02, 0.7, 4), spMat); lo.position.set(0, 0.7, 0.3); lo.rotation.x = 1.2; leg.add(lo); leg.position.set(side * 0.35, 0, -0.35 + (i % 4) * 0.22); leg.rotation.z = side * 1.35; leg.rotation.y = side * 0.4; sp.add(leg); this.spiderLegs.push(leg); }
    const thread = new THREE.Mesh(new THREE.CylinderGeometry(0.012, 0.012, 6, 3), new THREE.MeshBasicMaterial({ color: 0xdddddd })); thread.position.y = 3; sp.add(thread);
    sp.visible = false; sc.add(sp); this.spider = sp;
    // zombie hands
    this.hands = []; const handMat = new THREE.MeshStandardMaterial({ color: 0x6fae4a, roughness: 0.8 });
    for (let i = 0; i < 5; i++) { const h = new THREE.Group(); const palm = new THREE.Mesh(new THREE.BoxGeometry(0.3, 0.5, 0.12), handMat); palm.position.y = 0.25; h.add(palm); for (let f = 0; f < 4; f++) { const fg = new THREE.Mesh(new THREE.BoxGeometry(0.06, 0.28, 0.08), handMat); fg.position.set(-0.11 + f * 0.073, 0.6, 0); fg.rotation.x = -0.3; h.add(fg); } const th = new THREE.Mesh(new THREE.BoxGeometry(0.07, 0.2, 0.08), handMat); th.position.set(0.2, 0.4, 0); th.rotation.z = -0.6; h.add(th); const arm = new THREE.Mesh(new THREE.CylinderGeometry(0.09, 0.1, 0.8, 6), new THREE.MeshStandardMaterial({ color: 0x3a2a3a })); arm.position.y = -0.4; h.add(arm); h.visible = false; sc.add(h); this.hands.push(h); }
    // bats
    const batTex = canvasTex(128, 64, (ctx) => { ctx.fillStyle = '#000'; ctx.beginPath(); ctx.moveTo(64, 40); ctx.quadraticCurveTo(40, 10, 4, 24); ctx.quadraticCurveTo(24, 30, 20, 44); ctx.quadraticCurveTo(44, 36, 64, 52); ctx.quadraticCurveTo(84, 36, 108, 44); ctx.quadraticCurveTo(104, 30, 124, 24); ctx.quadraticCurveTo(88, 10, 64, 40); ctx.fill(); ctx.beginPath(); ctx.arc(64, 34, 8, 0, 6.3); ctx.fill(); ctx.fillStyle = '#ff3030'; ctx.beginPath(); ctx.arc(60, 32, 1.8, 0, 6.3); ctx.arc(68, 32, 1.8, 0, 6.3); ctx.fill(); });
    this.bats = []; for (let i = 0; i < 9; i++) { const b = new THREE.Sprite(new THREE.SpriteMaterial({ map: batTex, transparent: true, depthWrite: false })); b.scale.set(1.0, 0.5, 1); b.visible = false; sc.add(b); this.bats.push(b); }
    // entrance door (slams) and exit door
    { const c = this.center(0, 0); const d = new THREE.Group(); const dm = new THREE.Mesh(new THREE.BoxGeometry(1.7, 3.2, 0.12), woodMat); dm.position.set(0.85, 1.6, 0); d.add(dm); d.position.set(c.x - 0.85, 0, c.z - C / 2 + 0.1); d.rotation.y = -1.6; sc.add(d); this.frontDoor = d; }
    const [ex, ez] = this.route[this.route.length - 1]; const ec = this.center(ex, ez);
    { const door = new THREE.Group(); const dm = new THREE.Mesh(new THREE.BoxGeometry(1.7, 3.2, 0.12), woodMat); dm.position.set(0.85, 1.6, 0); door.add(dm); const knob = new THREE.Mesh(new THREE.SphereGeometry(0.08, 6, 5), new THREE.MeshStandardMaterial({ color: 0xffd11a })); knob.position.set(1.45, 1.5, 0.1); door.add(knob); door.position.set(ec.x + C / 2 - 0.1, 0, ec.z - 0.85); door.rotation.y = Math.PI / 2; sc.add(door); this.door = door; }
    const glow = new THREE.PointLight(0xfff0c0, 0, 9, 2); glow.position.set(ec.x + 1.5, 2, ec.z); sc.add(glow); this.exitGlow = glow;
    const exitSign = new THREE.Mesh(new THREE.PlaneGeometry(1.6, 0.5), new THREE.MeshBasicMaterial({ map: textTexture('EXIT', { bg: '#3cff7a', color: '#052', size: 80, w: 256, h: 80 }) })); exitSign.position.set(ec.x + C / 2 - 0.08, 3.6, ec.z); exitSign.rotation.y = -Math.PI / 2; sc.add(exitSign);
    this.thunderLight = new THREE.PointLight(0xbfd0ff, 0, 60, 1); this.thunderLight.position.set(12, 4, 12); sc.add(this.thunderLight);
    // scares in route order
    this.scares = [
      { cell: [0, 1], fn: () => this.scareSlam() },
      { cell: [0, 2], fn: () => this.scarePortrait(0) },
      { cell: [2, 1], fn: () => this.scareGhost() },
      { cell: [4, 1], fn: () => this.scareWitch() },
      { cell: [4, 3], fn: () => this.scareSpider() },
      { cell: [2, 3], fn: () => this.scareBehind() },
      { cell: [0, 4], fn: () => this.scareZombie() },
      { cell: [1, 5], fn: () => this.scareVampire() },
      { cell: [3, 5], fn: () => this.scareSkeleton() },
      { cell: [5, 5], fn: () => this.scareBoo() },
      { cell: [6, 5], fn: () => this.reachExit() },
    ];
  },

  // ---------- enter / exit ----------
  enter(b) {
    this.build(); this.building = b; this.active = true; this.t = 0; this.anims = []; this.shake = 0; this.heartT = 0; this.thunderT = 5; this.blackout = 0;
    for (const s of this.scares) s.fired = false;
    this.savedPos = Walk.pos.clone();
    const c = this.center(0, 0); Walk.pos.set(c.x, 0, c.z - 0.6); Walk.yaw = Math.PI; Walk.pitch = 0; Walk.speed = 4.5;
    this.frontDoor.rotation.y = -1.6; this.door.rotation.y = Math.PI / 2; this.exitGlow.intensity = 0;
    document.getElementById('flash').classList.remove('on');
    toast('🏚️ Ooooh… it\'s dark in here. Find the EXIT! 👻', 3000);
    Audio_.thunder(); this.lightning(); renderContext();
  },
  exit(finished) {
    if (!this.active) return; this.active = false; Walk.speed = 7;
    if (this.building) { const d = this.building.door; Walk.pos.set(d.x, 0, d.z + 1.5); Walk.yaw = 0; Walk.pitch = -0.05; }
    for (const o of [this.ghost, this.ghost2, this.boo, this.zombie, this.vampire, this.witch, this.skeleton, this.spider]) o.visible = false;
    for (const b of this.bats) b.visible = false; for (const h of this.hands) h.visible = false;
    Audio_.setWhoosh(0);
    if (finished) { toast('🏆 You made it out of the Spooky House! Brave!', 3500, 'gold'); Audio_.fanfare(); Particles.confetti(Walk.pos.clone().setY(3)); if (this.building) { this.building.visitors++; G.stats.spookySurvived = (G.stats.spookySurvived || 0) + 1; } }
    renderContext();
  },
  collide(prev) {
    const p = Walk.pos, r = 0.45, C = this.C;
    const inside = (x, z) => this.cells.has(this.key(Math.floor(x / C), Math.floor(z / C)));
    const okAt = (x, z) => inside(x - r, z - r) && inside(x + r, z - r) && inside(x - r, z + r) && inside(x + r, z + r);
    if (!okAt(p.x, p.z)) { if (okAt(p.x, prev.z)) p.z = prev.z; else if (okAt(prev.x, p.z)) p.x = prev.x; else { p.x = prev.x; p.z = prev.z; } }
  },
  update(dt) {
    if (!this.active) return; this.t += dt;
    const C = this.C; const cx = Math.floor(Walk.pos.x / C), cz = Math.floor(Walk.pos.z / C);
    for (const s of this.scares) if (!s.fired && s.cell[0] === cx && s.cell[1] === cz) { s.fired = true; s.fn(); }
    for (let i = this.anims.length - 1; i >= 0; i--) { const a = this.anims[i]; a.t += dt; const u = Math.min(1, a.t / a.dur); a.fn(u, a.t); if (u >= 1) { if (a.done) a.done(); this.anims.splice(i, 1); } }
    // ambient: heartbeat, candles, clock, cauldron, chair, thunder
    this.heartT -= dt; if (this.heartT <= 0) { this.heartT = 1.15; Audio_.heartbeat(); }
    if (this.blackout > 0) { this.blackout -= dt; for (const l of this.lights) l.intensity = 0.05; }
    else if (this.flicker > 0) { this.flicker -= dt; for (const l of this.lights) l.intensity = Math.random() < 0.5 ? 0.1 : l.userData.base * 1.3; if (this.flicker <= 0) for (const l of this.lights) l.intensity = l.userData.base; }
    else for (const l of this.lights) l.intensity = l.userData.base + Math.sin(this.t * 9 + l.position.x * 3) * 0.35 + Math.random() * 0.15;
    if (this.pendulum) this.pendulum.rotation.z = Math.sin(this.t * 2.2) * 0.35;
    if (this.chair) this.chair.rotation.x = Math.sin(this.t * 1.7) * 0.18;
    if (this.bubbles) for (const b of this.bubbles) { const u = b.userData; const ph = (this.t * 0.7 + u.ph) % 1; b.position.set(this.cauldronPos.x + Math.cos(u.a) * u.r, 1.05 + ph * 0.9, this.cauldronPos.z + Math.sin(u.a) * u.r); b.material.opacity = 0.8 * (1 - ph); }
    this.thunderT -= dt; if (this.thunderT <= 0) { this.thunderT = 7 + Math.random() * 8; this.lightning(); Audio_.thunder(); }
    if (this.thunderLight.intensity > 0) this.thunderLight.intensity = Math.max(0, this.thunderLight.intensity - dt * 14);
    for (const w of this.windows) w.material.emissiveIntensity = 0.9 + this.thunderLight.intensity * 0.5;
    if (this.shake > 0) this.shake -= dt;
  },
  lightning() { this.thunderLight.intensity = 6; this.flash(90, 'rgba(200,215,255,0.55)'); },
  inFront(dist, h) { const f = Walk.forward(); return new THREE.Vector3(Walk.pos.x + f.x * dist, h, Walk.pos.z + f.z * dist); },
  flash(ms = 160, color = '#fff') { const el = document.getElementById('flash'); el.style.background = color; el.classList.add('on'); setTimeout(() => el.classList.remove('on'), ms); },
  redPulse() { const el = document.getElementById('vignette'); el.classList.add('on'); setTimeout(() => el.classList.remove('on'), 900); },
  addLight(pos, color, dur, power = 6) { const l = new THREE.PointLight(color, power, 12, 2); l.position.copy(pos); this.scene.add(l); this.anims.push({ t: 0, dur, fn: u => { l.intensity = power * (1 - u); }, done: () => this.scene.remove(l) }); },
  jump(strength = 0.6) { this.shake = strength; this.redPulse(); },

  // ---------- the scares ----------
  scareSlam() {
    this.anims.push({ t: 0, dur: 0.25, fn: u => { this.frontDoor.rotation.y = -1.6 + u * 1.6; }, done: () => { Audio_.slam(); this.shake = 0.5; this.blackout = 1.2; toast('💥 The door slammed shut behind you!', 2200); } });
  },
  scarePortrait(i) {
    const g = this.portraits[i]; if (!g) return; const eyes = g.userData.eyes;
    Audio_.creak(); eyes.visible = true; g.userData.mat.map = this.art.portrait(2); g.userData.mat.needsUpdate = true;
    this.addLight(g.position.clone(), 0xff2020, 1.5, 3);
    this.anims.push({ t: 0, dur: 2.8, fn: (u, t) => { g.rotation.z = Math.sin(t * 7) * 0.3 * (1 - u); eyes.scale.set(0.9 + Math.sin(t * 20) * 0.2, 0.45 + Math.sin(t * 20) * 0.1, 1); }, done: () => { g.rotation.z = 0; eyes.visible = false; } });
    Audio_.whisper();
  },
  scareGhost() {
    const g = this.ghost; g.visible = true; const start = this.inFront(6, 1.7); const end = this.inFront(1.4, 1.5);
    g.position.copy(start); g.material.opacity = 1; Audio_.scream(); this.flash(140); this.jump(0.6); this.addLight(end, 0x99aaff, 0.8);
    this.anims.push({ t: 0, dur: 2.0, fn: (u, t) => { const k = Math.min(1, u * 2.6); g.position.lerpVectors(start, end, k); g.position.y = 1.5 + Math.sin(t * 9) * 0.15 + (u > 0.65 ? (u - 0.65) * 9 : 0); g.material.rotation = Math.sin(t * 10) * 0.18; g.material.opacity = u > 0.7 ? (1 - u) / 0.3 : 1; }, done: () => { g.visible = false; } });
  },
  scareWitch() {
    this.blackout = 0.9; Audio_.cackle(); Audio_.bats(); const f = Walk.forward(), r = Walk.right();
    const w = this.witch; w.visible = true;
    this.anims.push({ t: 0, dur: 2.4, fn: (u, t) => { const s = -7 + u * 14; w.position.set(Walk.pos.x + f.x * 3.5 + r.x * s, 2.6 + Math.sin(u * 6.3) * 0.5, Walk.pos.z + f.z * 3.5 + r.z * s); if (u > 0.4 && u < 0.43) { this.flash(100, 'rgba(120,255,140,0.5)'); this.jump(0.4); } }, done: () => w.visible = false });
    this.bats.forEach((b, i) => { b.visible = true; const off = (i - 4) * 0.5; this.anims.push({ t: 0, dur: 2.4, fn: (u, t) => { const s = -7 + u * 14; b.position.set(Walk.pos.x + f.x * (2.5 + off) + r.x * s, 2.1 + Math.sin(t * 9 + i) * 0.4 + i * 0.1, Walk.pos.z + f.z * (2.5 + off) + r.z * s); b.scale.set(1.0, 0.25 + Math.abs(Math.sin(t * 18 + i)) * 0.35, 1); }, done: () => b.visible = false }); });
    this.anims.push({ t: 0, dur: 1.0, fn: () => {}, done: () => { this.flicker = 1.0; } });
  },
  scareSpider() {
    const sp = this.spider; sp.visible = true; const p = this.inFront(1.5, 4.4); sp.position.copy(p); Audio_.hiss();
    this.anims.push({ t: 0, dur: 3.4, fn: (u, t) => { const drop = u < 0.22 ? u / 0.22 : 1; const y = 4.4 - drop * 3.0 + (u > 0.22 ? Math.sin(t * 5) * 0.15 : 0); sp.position.set(p.x, u > 0.8 ? y + (u - 0.8) * 22 : y, p.z); sp.lookAt(Walk.pos.x, sp.position.y, Walk.pos.z); this.spiderLegs.forEach((l, i) => { l.rotation.x = Math.sin(t * 22 + i) * 0.35; }); if (u > 0.21 && u < 0.24) { Audio_.scream(); this.flash(120); this.jump(0.5); } }, done: () => sp.visible = false });
  },
  scareBehind() {
    const g = this.ghost2; g.visible = true; g.material.opacity = 0.0;
    const f = Walk.forward(); const p = new THREE.Vector3(Walk.pos.x - f.x * 2.2, 1.5, Walk.pos.z - f.z * 2.2); g.position.copy(p);
    Audio_.whisper(); toast('🤫 …psst… it\'s behind you…', 2500);
    const yaw0 = Walk.yaw; let popped = false;
    this.anims.push({ t: 0, dur: 6, fn: (u, t) => { g.material.opacity = Math.min(1, t * 2); g.position.y = 1.5 + Math.sin(t * 4) * 0.1; if (!popped && (Math.abs(((Walk.yaw - yaw0 + Math.PI) % (Math.PI * 2)) - Math.PI) > 1.8 || t > 4.5)) { popped = true; Audio_.scream(); this.flash(160); this.jump(0.7); this.addLight(p, 0xff3060, 0.8); const start = p.clone(); const end = new THREE.Vector3(Walk.pos.x - f.x * 0.9, 1.5, Walk.pos.z - f.z * 0.9); this.anims.push({ t: 0, dur: 1.2, fn: (v) => { g.position.lerpVectors(start, end, Math.min(1, v * 3)); g.position.y = 1.5 + (v > 0.5 ? (v - 0.5) * 8 : 0); g.material.opacity = v > 0.7 ? (1 - v) / 0.3 : 1; }, done: () => g.visible = false }); } }, done: () => { if (!popped) g.visible = false; } });
  },
  scareZombie() {
    const f = Walk.forward(), r = Walk.right(); Audio_.groan(); this.redPulse();
    this.hands.forEach((h, i) => { h.visible = true; const px = Walk.pos.x + f.x * (1.4 + i * 0.5) + r.x * ((i - 2) * 0.7), pz = Walk.pos.z + f.z * (1.4 + i * 0.5) + r.z * ((i - 2) * 0.7); h.position.set(px, -1.2, pz); h.rotation.y = Math.random() * 6; this.anims.push({ t: 0, dur: 3.2, fn: (u, t) => { const up = Math.min(1, Math.max(0, (u - i * 0.06) * 3)); h.position.y = -1.2 + up * 1.4 - (u > 0.85 ? (u - 0.85) * 12 : 0); h.rotation.z = Math.sin(t * 6 + i) * 0.3; }, done: () => h.visible = false }); });
    const z = this.zombie; z.visible = true; const p = this.inFront(1.6, -0.6); z.position.copy(p);
    this.anims.push({ t: 0, dur: 2.6, fn: (u, t) => { const up = Math.min(1, Math.max(0, (u - 0.25) * 2.5)); z.position.set(p.x, -0.6 + up * 2.1 + Math.sin(t * 6) * 0.05, p.z); if (u > 0.3 && u < 0.33) { Audio_.scream(); this.flash(140, 'rgba(160,255,120,0.55)'); this.jump(0.6); } z.material.opacity = u > 0.8 ? (1 - u) / 0.2 : 1; }, done: () => { z.visible = false; z.material.opacity = 1; } });
  },
  scareVampire() {
    const lid = this.coffinLid; Audio_.creak();
    this.anims.push({ t: 0, dur: 0.9, fn: u => { lid.rotation.z = -u * 2.2; }, done: () => {
      const v = this.vampire; v.visible = true; const p = this.coffinPos.clone(); v.position.set(p.x, 0.2, p.z); Audio_.scream(); Audio_.cackle(); this.flash(150, 'rgba(255,80,80,0.5)'); this.jump(0.6); this.addLight(p.clone().setY(2), 0xff2040, 1.0);
      this.anims.push({ t: 0, dur: 2.4, fn: (u, t) => { const up = Math.min(1, u * 3); v.position.set(p.x, 0.2 + up * 1.6 + Math.sin(t * 5) * 0.05, p.z); v.material.opacity = u > 0.8 ? (1 - u) / 0.2 : 1; }, done: () => { v.visible = false; v.material.opacity = 1; this.anims.push({ t: 0, dur: 0.6, fn: u => { lid.rotation.z = -2.2 + u * 2.2; }, done: () => Audio_.slam() }); } });
    } });
  },
  scareSkeleton() {
    const sk = this.skeleton; sk.visible = true; const p = this.inFront(1.8, 0); sk.position.set(p.x, 4.8, p.z); sk.lookAt(Walk.pos.x, 0, Walk.pos.z); Audio_.bones(); this.addLight(this.inFront(1.5, 2), 0x66ff88, 0.9);
    this.anims.push({ t: 0, dur: 2.8, fn: (u, t) => { const fall = Math.min(1, u * 4.5); sk.position.y = 4.8 - fall * 4.8 + (fall >= 1 ? Math.abs(Math.sin(t * 12)) * 0.15 * (1 - u) : 0); sk.rotation.z = Math.sin(t * 14) * 0.15 * (1 - u); this.jaw.position.y = 1.38 - Math.abs(Math.sin(t * 16)) * 0.12; if (u > 0.2 && u < 0.23) { Audio_.scream(); this.flash(130); this.jump(0.6); } if (u > 0.82) sk.position.y -= (u - 0.82) * 0.6; }, done: () => sk.visible = false });
  },
  scareBoo() {
    const g = this.boo; g.visible = true; g.material.opacity = 1; const start = this.inFront(10, 1.8); const end = this.inFront(1.0, 1.6); g.position.copy(start);
    this.blackout = 0.7; Audio_.boo(); this.addLight(end, 0xff3060, 1.4, 8);
    this.anims.push({ t: 0, dur: 2.2, fn: (u, t) => { const k = Math.min(1, u * 1.7); g.position.lerpVectors(start, end, k * k); g.position.y = 1.6 + Math.sin(t * 6) * 0.1; const s = 3 + (u > 0.55 ? (u - 0.55) * 6 : 0); g.scale.set(s, s, 1); g.material.rotation = Math.sin(t * 12) * 0.08; if (u > 0.5 && u < 0.53) { Audio_.scream(); Audio_.boo(); this.flash(260); this.jump(0.9); toast('👻 BOO!!!', 900); } g.material.opacity = u > 0.8 ? (1 - u) / 0.2 : 1; }, done: () => { g.visible = false; g.scale.set(3, 3, 1); this.exitGlow.intensity = 4; this.anims.push({ t: 0, dur: 1.0, fn: u => { this.door.rotation.y = Math.PI / 2 + u * 1.6; } }); Audio_.creak(); toast('🚪 The exit door creaks open… RUN!', 2500, 'gold'); } });
  },
  reachExit() { setTimeout(() => this.exit(true), 200); },
};
