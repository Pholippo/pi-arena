// QA fuer ninja.html: Level-Generator + Physik aus der echten Datei extrahieren, A*-Bot ueber Eingaben.
// Aufruf (vom Repo-Ordner):  node tests/ninja_qa.mjs [arena/web/ninja.html] [Anzahl Seeds, Standard 30]
import fs from 'fs';
import os from 'os';
import path from 'path';
import { fileURLToPath } from 'url';
const HIER = path.dirname(fileURLToPath(import.meta.url));
const HTML = process.argv[2] || path.join(HIER, '..', 'arena', 'web', 'ninja.html');
const SEEDS = +(process.argv[3] || 30);
const src = fs.readFileSync(HTML, 'utf8');
const a = src.indexOf('// ================= Level'), b = src.indexOf('// ================= Zustand, Netz, Eingabe');
if (a < 0 || b < 0) throw new Error('Marker nicht gefunden');
const sect = src.slice(a, b);
const stubs = `const st={phase:'spiel'}, TV=false, id='bot'; function ton(){}\n`;
const exp = `\nreturn {baue,neu,schritt,fest,kachel,taste,T,ROWS,PW,PH,
 get ich(){return ich}, set ich(v){ich=v}, set sprungNeu(v){sprungNeu=v}, get sprungNeu(){return sprungNeu},
 get zielZeit(){return zielZeit}, set zielZeit(v){zielZeit=v}, get COLS(){return COLS}, get karte(){return karte},
 get checkpoints(){return checkpoints}, get ZIEL_X(){return ZIEL_X}};`;
fs.writeFileSync(path.join(os.tmpdir(), 'ninja_extract.js'), '(function(){\n' + stubs + sect + exp + '\n})();\n');
const M = new Function(stubs + sect + exp)();
const DT = 1 / 120, K = 4; // Makroschritt = 4 Physikschritte
const ACTS = []; for (const d of [-1, 0, 1]) for (const j of [false, true]) ACTS.push({ d, j });

function ueberlappt(p) { // steckt der Spieler in Stein?
  const x0 = Math.floor(p.x / M.T), x1 = Math.floor((p.x + M.PW - 1) / M.T), y0 = Math.floor(p.y / M.T), y1 = Math.floor((p.y + M.PH - 1) / M.T);
  for (let cx = x0; cx <= x1; cx++) for (let cy = y0; cy <= y1; cy++) if (M.fest(cx, cy)) return true; return false;
}
function simuliere(state, act) {
  M.ich = { ...state.ich }; M.zielZeit = null;
  M.taste.l = act.d < 0; M.taste.r = act.d > 0;
  M.sprungNeu = act.j && !state.j; M.taste.j = act.j;
  let fehler = null;
  for (let i = 0; i < K; i++) {
    M.schritt(DT);
    if (!M.ich.lebt) return { tot: true };
    if (ueberlappt(M.ich)) fehler = 'steckt in Wand';
    if (M.zielZeit !== null) return { ziel: true, ich: { ...M.ich }, j: act.j };
  }
  return { ich: { ...M.ich }, j: act.j, fehler };
}
function loese(maxKnoten = 3e6) {
  M.neu(0); M.zielZeit = null;
  const zx = M.ZIEL_X, start = { ich: { ...M.ich }, j: false, t: 0 };
  // Binaerheap nach f
  const heap = []; const push = (n) => { heap.push(n); let i = heap.length - 1; while (i > 0) { const p = (i - 1) >> 1; if (heap[p].f <= heap[i].f) break; [heap[p], heap[i]] = [heap[i], heap[p]]; i = p; } };
  const pop = () => { const top = heap[0], last = heap.pop(); if (heap.length) { heap[0] = last; let i = 0; for (;;) { const l = 2 * i + 1, r = l + 1; let m = i; if (l < heap.length && heap[l].f < heap[m].f) m = l; if (r < heap.length && heap[r].f < heap[m].f) m = r; if (m === i) break; [heap[m], heap[i]] = [heap[i], heap[m]]; i = m; } } return top; };
  const h = (s) => Math.abs(zx - s.ich.x) / 330 * 1.6; // leicht gierig
  start.f = h(start); push(start);
  const besucht = new Set(); let n = 0, maxX = 0, steck = 0;
  while (heap.length && n < maxKnoten) {
    const s = pop(); n++;
    for (const act of ACTS) {
      const r = simuliere(s, act);
      if (r.tot) continue;
      const t = s.t + K * DT;
      if (r.ziel) return { ok: true, t, knoten: n, steck };
      if (r.fehler) steck++;
      const p = r.ich; if (p.x > maxX) maxX = p.x;
      const key = `${Math.round(p.x / 4)},${Math.round(p.y / 4)},${Math.round(p.vx / 60)},${Math.round(p.vy / 90)},${p.amBoden ? 1 : 0},${r.j ? 1 : 0}`;
      if (besucht.has(key)) continue; besucht.add(key);
      const k = { ich: p, j: r.j, t }; k.f = t + h(k); push(k);
    }
  }
  return { ok: false, maxX, knoten: n, steck, col: Math.floor(maxX / M.T) };
}
function statisch() {
  const f = [];
  // Spawn je Checkpoint: auf Boden, nicht in Wand
  for (const cp of M.checkpoints) {
    M.neu(cp); const p = M.ich;
    if (ueberlappt(p)) f.push(`Spawn cp=${cp} in Wand`);
    const cx0 = Math.floor(p.x / M.T), cx1 = Math.floor((p.x + M.PW - 1) / M.T), cy = Math.floor((p.y + M.PH) / M.T);
    if (!M.fest(cx0, cy) && !M.fest(cx1, cy)) f.push(`Spawn cp=${cp} in der Luft`);
    const cc = cp / M.T; let ok = false; for (let y = 0; y < M.ROWS - 1; y++) if (M.kachel(cc, y) === 3 && M.fest(cc, y + 1)) ok = true;
    if (cp > 0 && !ok) f.push(`Checkpoint ${cc} ohne Boden`);
  }
  // Fallgeschwindigkeit/Tunneling: 1100px/s*dt
  if (1100 * DT >= M.T) f.push('Tunneling moeglich');
  return f;
}
let alleOk = true; const zeiten = [];
for (let s = 1; s <= SEEDS; s++) {
  M.baue(s);
  const f = statisch();
  const r = loese();
  if (!r.ok || f.length || r.steck) alleOk = false;
  if (r.ok) zeiten.push(r.t);
  console.log(`seed ${String(s).padStart(2)}  COLS=${M.COLS}  ${r.ok ? 'LOESBAR ' + r.t.toFixed(1) + 's' : 'NICHT LOESBAR bis Spalte ' + r.col}  knoten=${r.knoten}${r.steck ? ' steck=' + r.steck : ''}${f.length ? '  ' + f.join('; ') : ''}`);
}
if (zeiten.length) console.log(`Bot-Zeit: min ${Math.min(...zeiten).toFixed(1)}s, max ${Math.max(...zeiten).toFixed(1)}s, Schnitt ${(zeiten.reduce((a, b) => a + b) / zeiten.length).toFixed(1)}s`);
console.log(alleOk ? 'ALLE OK' : 'FEHLER GEFUNDEN');
process.exit(alleOk ? 0 : 1);
