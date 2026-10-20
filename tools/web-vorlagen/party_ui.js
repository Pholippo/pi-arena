// ---------- PARTY-UI-START (gleicher Block in ninja/flappy/auto: Leicht-Modus, Namensschilder, Rangliste, Ende, Hilfe, Touch)
// Erwartet im Spiel: ctx, W, st, id, TV, ton(), ac, groesse()
const UIQ=new URLSearchParams(location.search), UA=navigator.userAgent||'';
// Schwaches Geraet (Raspberry Pi: Linux aarch64/arm ohne Android) oder ?leicht=1 -> Pixeldichte 1, weniger Deko
let LEICHT=UIQ.get('leicht')==='1'||(/Linux (aarch64|arm)/i.test(UA)&&!/Android/i.test(UA));
const TOUCH=('ontouchstart' in window)||(navigator.maxTouchPoints||0)>0;
function pixelRatio(){return LEICHT?1:Math.min(2,window.devicePixelRatio||1);}
function canvasGroesse(cv){ // true, wenn sich die Pixelgroesse wirklich geaendert hat (sonst kein Reset/Neuaufbau)
  const d=pixelRatio(), w=Math.max(1,Math.round(innerWidth*d)), h=Math.max(1,Math.round(innerHeight*d));
  if(cv.width===w&&cv.height===h) return false; cv.width=w; cv.height=h; return true; }
let ftMittel=16, ftAnz=0;
function frameMessen(ms){ // Framezeit dauerhaft > 25 ms -> automatisch in den Leicht-Modus
  if(LEICHT||document.hidden||!(ms>0)||ms>250) return;
  ftMittel+=(ms-ftMittel)*0.05; if(++ftAnz>120&&ftMittel>25){ LEICHT=true; groesse(); } }
addEventListener('pointerdown',()=>{try{ if(ac&&ac.state==='suspended') ac.resume(); }catch(e){}},true);
function hell(f){const m=/^#?([0-9a-f]{6})/i.exec(f||''); if(!m) return false; const n=parseInt(m[1],16);
  return 0.299*(n>>16)+0.587*(n>>8&255)+0.114*(n&255)>150;}
function pfad(x,y,w,h,r){r=Math.min(r,w/2,h/2);ctx.beginPath();ctx.moveTo(x+r,y);ctx.arcTo(x+w,y,x+w,y+h,r);
  ctx.arcTo(x+w,y+h,x,y+h,r);ctx.arcTo(x,y+h,x,y,r);ctx.arcTo(x,y,x+w,y,r);ctx.closePath();}
const tbCache={};
function textBreite(t,font){const k=font+'|'+t; let w=tbCache[k]; if(w===undefined){ctx.font=font; w=tbCache[k]=ctx.measureText(t).width;} return w;}
let belegt=[]; // Schilder dieses Frames (zum Stapeln statt Ueberlappen); schilderNeu() am Frame-Anfang
function schilderNeu(){ belegt=[]; }
function schild(text,x,y,farbe,fs,alpha,eigen,frei){ // Namensschild (Pill in Spielerfarbe); Mitte x, Unterkante y -> Hoehe (+ Versatz nach oben)
  const font='bold '+fs+'px system-ui,sans-serif', h=Math.round(fs*1.45), w=textBreite(text,font)+fs*1.1;
  let auf=0; if(frei){ for(let n=0;n<8&&belegt.some(b=>x-w/2<b[1]&&x+w/2>b[0]&&y-auf-h<b[3]&&y-auf>b[2]);n++) auf+=h+2; y-=auf; belegt.push([x-w/2,x+w/2,y-h,y]); }
  ctx.save(); ctx.globalAlpha=alpha; pfad(x-w/2,y-h,w,h,h/2); ctx.fillStyle=farbe; ctx.fill();
  ctx.lineWidth=eigen?3:1.5; ctx.strokeStyle=eigen?'#fff':'rgba(0,0,0,.55)'; ctx.stroke();
  ctx.font=font; ctx.textAlign='center'; ctx.textBaseline='middle'; ctx.fillStyle=hell(farbe)?'#111':'#fff';
  ctx.fillText(text,x,y-h/2+1); ctx.restore(); return h+auf; }
function duMarker(x,y){ // gelber Pfeil + "DU" ueber dem eigenen Spieler; y = Pfeilspitze
  y+=Math.sin(performance.now()/170)*3;
  ctx.save(); ctx.fillStyle='#ffd23f'; ctx.strokeStyle='#000'; ctx.lineWidth=2.5; ctx.lineJoin='round';
  ctx.beginPath(); ctx.moveTo(x,y); ctx.lineTo(x-11,y-13); ctx.lineTo(x+11,y-13); ctx.closePath(); ctx.stroke(); ctx.fill();
  ctx.font='900 18px system-ui,sans-serif'; ctx.textAlign='center'; ctx.textBaseline='alphabetic'; ctx.lineWidth=4;
  ctx.strokeText('DU',x,y-16); ctx.fillText('DU',x,y-16); ctx.restore(); }
function krone(x,y,s){ // y = Unterkante
  ctx.save(); ctx.fillStyle='#ffd700'; ctx.strokeStyle='#000'; ctx.lineWidth=1.5; ctx.lineJoin='round'; ctx.beginPath();
  ctx.moveTo(x-s,y); ctx.lineTo(x-s,y-s*0.9); ctx.lineTo(x-s*0.5,y-s*0.45); ctx.lineTo(x,y-s*1.15); ctx.lineTo(x+s*0.5,y-s*0.45);
  ctx.lineTo(x+s,y-s*0.9); ctx.lineTo(x+s,y); ctx.closePath(); ctx.stroke(); ctx.fill(); ctx.restore(); }
function fuehrender(){ const p=st.spieler&&st.spieler[0]; return p&&(st.phase==='spiel'||st.phase==='ende')&&(p.best>0||p.ziel)?p.id:null; }
function beschriftung(p,x,y,eigen){ // Schild (+Krone fuer den Fuehrenden, +DU-Pfeil) ueber einer Figur; y = Oberkante der Figur
  const fs=TV?22:(eigen?17:14); let top=y-5;
  top-=schild(p.name+(p.ziel?' ✔':''),x,top,p.farbe,fs,eigen||TV?1:0.82,eigen,true);
  if(p.id===fuehrender()){ const s=TV?14:9; krone(x,top-3,s); top-=s*1.15+4; }
  if(eigen) duMarker(x,top-3);
}
function ich_p(){ return st.spieler.find(p=>p.id===id)||{id,name:meinName||'?',farbe:'#ffd23f',best:0}; }
function rangliste(x,y,br,titel,tfarbe,max,wert){ // eigene Zeile hervorgehoben; ausserhalb der Top-N wird sie angehaengt
  if(!TV&&W<600){ max=Math.min(max,3); br=Math.min(br,Math.max(150,W*0.58)); x=W-br-8; } // Handy hochkant: kompakt
  const eng=!TV&&W<600, zh=TV?32:(eng?21:24), fs=TV?20:(eng?13:15), alle=st.spieler, liste=alle.slice(0,max).map((p,i)=>[p,i+1]);
  const mi=alle.findIndex(p=>p.id===id); if(!TV&&mi>=max) liste.push([alle[mi],mi+1]);
  ctx.save(); ctx.fillStyle='rgba(0,0,0,.62)'; ctx.fillRect(x,y,br,32+liste.length*zh);
  ctx.textBaseline='alphabetic'; ctx.font='bold '+fs+'px system-ui,sans-serif'; ctx.textAlign='left'; ctx.fillStyle=tfarbe; ctx.fillText(titel,x+12,y+22);
  liste.forEach(([p,rang],k)=>{ const yy=y+24+(k+1)*zh, eigen=!TV&&p.id===id;
    if(eigen){ ctx.globalAlpha=0.4; ctx.fillStyle=p.farbe; ctx.fillRect(x+4,yy-zh+7,br-8,zh-2); ctx.globalAlpha=1;
      ctx.strokeStyle='#fff'; ctx.lineWidth=2; ctx.strokeRect(x+4,yy-zh+7,br-8,zh-2);
      ctx.fillStyle='#ffd23f'; ctx.textAlign='right'; ctx.fillText('DU ▶',x-6,yy); }
    pfad(x+12,yy-fs*0.82,fs*0.85,fs*0.85,3); ctx.fillStyle=p.farbe; ctx.fill(); ctx.strokeStyle='#0008'; ctx.lineWidth=1; ctx.stroke();
    ctx.textAlign='left'; ctx.fillStyle=rang===1&&p.id===fuehrender()?'#ffd700':(eigen?'#fff':'#e8e8e8');
    ctx.fillText(rang+'. '+p.name,x+fs+20,yy);
    ctx.textAlign='right'; ctx.fillText(wert(p),x+br-12,yy); });
  ctx.restore(); }
function endeScreen(titel,hoehe,wert){ // Rundenende: Siegertreppchen Top 3 + eigener Platz
  ctx.save(); ctx.fillStyle='rgba(0,0,0,.82)'; ctx.fillRect(0,0,W,hoehe); ctx.textBaseline='alphabetic'; ctx.textAlign='center';
  ctx.font='bold 54px system-ui,sans-serif'; ctx.lineWidth=6; ctx.strokeStyle='#000'; ctx.fillStyle='#ffd23f';
  ctx.strokeText(titel,W/2,84); ctx.fillText(titel,W/2,84);
  const basis=hoehe-125, med=['#ffd700','#c0c0c0','#cd7f32'], hoch=[165,125,100], bw=Math.min(160,(W-24)/3.4), dx=[0,-bw*1.12,bw*1.12];
  st.spieler.slice(0,3).forEach((p,i)=>{ const x=W/2+dx[i], top=basis-hoch[i];
    ctx.fillStyle=med[i]; ctx.fillRect(x-bw/2,top,bw,hoch[i]); ctx.fillStyle='rgba(0,0,0,.25)'; ctx.fillRect(x-bw/2,top+hoch[i]-10,bw,10);
    ctx.fillStyle='#000'; ctx.font='900 '+(i?40:56)+'px system-ui,sans-serif'; ctx.fillText(String(i+1),x,top+(i?46:62));
    ctx.font='bold 18px system-ui,sans-serif'; ctx.fillText(wert(p),x,top+hoch[i]-16);
    const h=schild(p.name,x,top-8,p.farbe,i?20:24,1,!TV&&p.id===id);
    if(i===0) krone(x,top-14-h,16); });
  if(!st.spieler.length){ ctx.font='bold 22px system-ui,sans-serif'; ctx.fillStyle='#fff'; ctx.fillText('Niemand dabei',W/2,basis-60); }
  ctx.font='bold 22px system-ui,sans-serif'; ctx.fillStyle='#fff';
  const mi=st.spieler.findIndex(p=>p.id===id);
  if(!TV&&mi>=0){ const p=st.spieler[mi]; ctx.fillStyle=mi<3?'#ffd23f':'#fff'; ctx.fillText('Du: Platz '+(mi+1)+' von '+st.spieler.length+'  ·  '+wert(p),W/2,basis+40); }
  ctx.fillStyle='#ccc'; ctx.font='20px system-ui,sans-serif'; ctx.fillText(TV?'START = neue Runde':'Gleich geht\'s weiter...',W/2,basis+80);
  ctx.restore(); }
let cdAlt=0;
function countdownTon(rest){ // Piep pro Sekunde, letzte 3 hoeher; "LOS" spielt der Phasenwechsel
  if(st.phase!=='countdown'){ cdAlt=0; return; } const n=Math.ceil(rest);
  if(n>0&&n!==cdAlt){ cdAlt=n; ton(n<=3?660:440,.14,'triangle',.09); } }
function hilfe(text){ // kurze Steuerungshilfe unten, mit x ausblendbar (merkt sich das), Taste H schaltet um
  if(TV) return; const d=document.createElement('div'); d.id='hilfe';
  d.innerHTML='<span></span><button type=button aria-label="Hilfe ein/aus"></button>'; d.firstChild.textContent=text;
  document.body.appendChild(d); const b=d.querySelector('button'); let zu=false;
  try{ zu=localStorage.getItem('party_hilfe')==='zu'; }catch(e){}
  const setz=(z,merken=true)=>{ zu=z; d.classList.toggle('zu',z); b.textContent=z?'?':'×'; if(merken) try{ localStorage.setItem('party_hilfe',z?'zu':'auf'); }catch(e){} };
  setz(zu,false); if(TOUCH&&!zu) setTimeout(()=>{ if(!zu) setz(true,false); },9000); // am Handy nach 9 s von selbst klein b.addEventListener('pointerdown',e=>{e.preventDefault();e.stopPropagation();setz(!zu);});
  addEventListener('keydown',e=>{ if((e.key==='h'||e.key==='H')&&document.activeElement!==document.getElementById('name')) setz(!zu); }); }
function touchKnoepfe(bei){ // grosse Touch-Knoepfe (#touch button[data-k]) -> bei(k, gedrueckt)
  const t=document.getElementById('touch'); if(TV||!TOUCH||!t) return; t.style.display='flex'; document.body.classList.add('touch');
  t.querySelectorAll('button').forEach(b=>{ const k=b.dataset.k;
    b.addEventListener('pointerdown',e=>{ e.preventDefault(); e.stopPropagation(); try{ b.setPointerCapture(e.pointerId); }catch(_){}
      b.classList.add('on'); bei(k,true); });
    const los=()=>{ if(!b.classList.contains('on')) return; b.classList.remove('on'); bei(k,false); };
    b.addEventListener('pointerup',los); b.addEventListener('pointercancel',los); b.addEventListener('lostpointercapture',los);
    b.addEventListener('contextmenu',e=>e.preventDefault()); }); }
// ---------- PARTY-UI-ENDE
