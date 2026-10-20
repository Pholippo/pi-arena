// Hilfswerkzeug (kein automatischer Test): Screenshot einer Spielseite ueber das Chrome-DevTools-Protokoll.
//   1) Chrome/Chromium mit Debug-Port starten, z.B.:  chromium --remote-debugging-port=9222 --user-data-dir=/tmp/cdp
//   2) node tests/cdp_shot.mjs <port> <url> <out.png> [keys]
//      keys: "join" = Namen "CDPtest" eintragen und beitreten, "lauf" = ein paar Pfeil/Leertaste-Eingaben
//   Beispiel: node tests/cdp_shot.mjs 9222 http://127.0.0.1:8082/ ninja.png join,lauf
// Neuer Tab, 2,5 s warten, optional Tasten, Screenshot (1280x720), Tab wieder zu. Braucht Node 22+ (WebSocket eingebaut).
import fs from "fs";
const [port, url, out, keys = ""] = process.argv.slice(2);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const tab = await (await fetch(`http://127.0.0.1:${port}/json/new?${encodeURI(url)}`, { method: "PUT" })).json();
const ws = new WebSocket(tab.webSocketDebuggerUrl);
await new Promise((r) => (ws.onopen = r));
let id = 0; const w = new Map();
ws.onmessage = (ev) => { const m = JSON.parse(ev.data); if (m.id && w.has(m.id)) { w.get(m.id)(m); w.delete(m.id); } };
const send = (method, params = {}) => new Promise((res) => { const i = ++id; w.set(i, res); ws.send(JSON.stringify({ id: i, method, params })); });
await send("Emulation.setFocusEmulationEnabled", { enabled: true });
await send("Emulation.setDeviceMetricsOverride", { width: 1280, height: 720, deviceScaleFactor: 1, mobile: false });
await sleep(2500);
const ev = async (e) => (await send("Runtime.evaluate", { expression: e, returnByValue: true })).result?.result?.value;
if (keys.includes("join")) { await ev(`document.getElementById('name').value='CDPtest';document.getElementById('los').click()`); await sleep(1200); }
if (keys.includes("lauf")) {
  for (let i = 0; i < 18; i++) {
    await send("Input.dispatchKeyEvent", { type: "keyDown", key: "ArrowRight", code: "ArrowRight", windowsVirtualKeyCode: 39 });
    if (i % 4 === 0) { await send("Input.dispatchKeyEvent", { type: "keyDown", key: " ", code: "Space", windowsVirtualKeyCode: 32 });
      await sleep(150); await send("Input.dispatchKeyEvent", { type: "keyUp", key: " ", code: "Space", windowsVirtualKeyCode: 32 }); }
    await sleep(100);
  }
}
console.log("info", JSON.stringify(await ev(`({fehler: window.__err||null, x: typeof ich!=='undefined'?Math.round(ich.x):null, lebt: typeof ich!=='undefined'?ich.lebt:null, phase: st.phase, cols: COLS})`)));
const shot = await send("Page.captureScreenshot", { format: "png" });
fs.writeFileSync(out, Buffer.from(shot.result.data, "base64"));
ws.close();
await fetch(`http://127.0.0.1:${port}/json/close/${tab.id}`);
console.log("ok", out);
