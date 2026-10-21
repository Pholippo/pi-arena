// Extrahiert JS aus auto.html, node --check, und simuliert die Loesbarkeit des Verkehrs:
// alle Schwierigkeitsstufen einzeln + gemischt (benachbarte Reihen aus verschiedenen Stufen),
// Hoechsttempo (VMAX + VMAX_PLUS + TURBO) wird aus der Datei gelesen.
// Aufruf (vom Repo-Ordner):  node tests/auto_test.cjs [arena/web/auto.html] [Seeds, Standard 20]
const fs = require('fs'), path = require('path'), cp = require('child_process'), os = require('os');
const html = fs.readFileSync(process.argv[2] || path.join(__dirname, '..', 'arena', 'web', 'auto.html'), 'utf8');
const SEEDS = +(process.argv[3] || 20);
const js = html.match(/<script>([\s\S]*)<\/script>/)[1];
const out = path.join(os.tmpdir(), 'auto_extracted.js');
fs.writeFileSync(out, js);
cp.execFileSync(process.execPath, ['--check', out]);
console.log('node --check OK');
const zahl = (n) => +js.match(new RegExp('\\b' + n + '=(\\d+)'))[1];
const VMAX = zahl('VMAX'), VMAX_PLUS = zahl('VMAX_PLUS'), TURBO = zahl('TURBO'), ALEN = zahl('ALEN');
const block = js.match(/\/\/ VERKEHR-START([\s\S]*)\/\/ VERKEHR-ENDE/)[1];
const api = new Function(block + '; return {reihe, reihePos, ABST, U, STUFEN, setSeed(s){seed=s;reihenCache={}}, setStufe(s){stufe=s}};')();
const COLS = 4, VMAX_TURBO = VMAX + VMAX_PLUS + TURBO;
let reihenGeprueft = 0, leer = 0, voll = 0, schlecht = 0, maxAutos = 0;
const proStufe = [];
for (let n = 0; n < SEEDS; n++) {
  const s = 1 + Math.floor(Math.random() * 1e6);
  // gemischt: jede Reihe zufaellig mit einer anderen Stufe erzeugt (so wie im Spiel, wenn Reihen zu verschiedenen Zeiten entstehen)
  for (const modus of ['gemischt', ...Array.from({ length: api.STUFEN }, (_, k) => k)]) {
    api.setSeed(s);
    const iMin = -Math.ceil(api.U * 600 / api.ABST) - 5, iMax = Math.ceil(VMAX_TURBO * 180 / api.ABST) + 5;
    let autos = 0, reihen = 0;
    for (let i = iMin; i <= iMax + 1; i++) { api.setStufe(modus === 'gemischt' ? Math.floor(Math.random() * api.STUFEN) : modus); api.reihe(i); }
    for (let i = iMin; i <= iMax; i++) {
      const a = api.reihe(i), b = api.reihe(i + 1);
      reihenGeprueft++; reihen++; autos += a.length;
      const occA = new Set(a.map(c => c.spur)), occB = new Set(b.map(c => c.spur));
      if (occA.size !== a.length) schlecht++;
      maxAutos = Math.max(maxAutos, a.length);
      if (a.length === 0) leer++;
      if (occA.size >= COLS) voll++;
      for (let l = 0; l < COLS; l++) {
        if (occA.has(l)) continue;
        if (![l - 1, l, l + 1].some(k => k >= 0 && k < COLS && !occB.has(k))) schlecht++;
      }
    }
    if (typeof modus === 'number') { proStufe[modus] = (proStufe[modus] || 0) + autos / reihen; }
    const r1 = JSON.stringify(api.reihe(42)); api.setSeed(s); api.setStufe(typeof modus === 'number' ? modus : 0);
    if (typeof modus === 'number' && JSON.stringify(api.reihe(42)) !== r1) schlecht++;
  }
}
const luecke = api.ABST - ALEN - ALEN + 20, rel = VMAX_TURBO - api.U;
console.log(`${SEEDS} Seeds x (${api.STUFEN} Stufen + gemischt): ${reihenGeprueft} Reihen, max ${maxAutos} Autos/Reihe, ${voll} Reihen ohne freie Spur, ${schlecht} Verstoesse, ${leer} leere Reihen`);
console.log('Autos pro Reihe je Stufe: ' + proStufe.map((v, k) => `S${k + 1}=${(v / SEEDS).toFixed(2)}`).join(' ') +
  `  (pro 1000 px: ${(proStufe[0] / SEEDS / api.ABST * 1000).toFixed(2)} -> ${(proStufe[api.STUFEN - 1] / SEEDS / api.ABST * 1000).toFixed(2)}; alt 4.48)`);
console.log(`Ausweichfenster bei Hoechsttempo ${VMAX + VMAX_PLUS}+Turbo ${TURBO}: ${(luecke / rel * 1000).toFixed(0)} ms fuer 1 Spurwechsel (${(1000 / 9).toFixed(0)} ms)`);
if (voll || schlecht || luecke / rel < 1 / 9) { console.log('FEHLER'); process.exit(1); }
console.log('LOESBARKEIT OK');
