const T=40, ROWS=15, WH=ROWS*T, BODEN=13;
function zufall(seed){let a=seed>>>0;return()=>{a|=0;a=a+0x6D2B79F5|0;let t=Math.imul(a^a>>>15,1|a);
  t=t+Math.imul(t^t>>>7,61|t)^t;return((t^t>>>14)>>>0)/4294967296}}
let seed=-1, karte=null, COLS=0, checkpoints=[], ZIEL_X=0;
// Kacheln: 0 leer, 1 Stein, 2 Stacheln, 3 Checkpoint-Fahne, 4 Ziel
function baue(s){
  const r=zufall(s*7919+13), ri=(a,b)=>a+Math.floor(r()*(b-a+1));
  const spalten=[]; // jede Spalte: Array ROWS
  const leer=()=>new Array(ROWS).fill(0);
  let h=BODEN; // aktuelle Bodenhoehe (Zeile der Oberkante)
  const boden=(n,hoehe=h)=>{for(let i=0;i<n;i++){const c=leer();for(let y=hoehe;y<ROWS;y++)c[y]=1;spalten.push(c)}};
  const cp=()=>{const c=spalten[spalten.length-2];for(let y=0;y<ROWS;y++)if(c[y]===1){c[y-1]=3;break}checkpoints.push((spalten.length-2)*T)};
  checkpoints=[0];
  boden(10);
  const segmente=['luecke','treppe','schacht','stacheln','plattformen','luecke','schacht','abwaerts','stacheln','plattformen'];
  let anz=0;
  while(spalten.length<330){
    const seg=segmente[Math.floor(r()*segmente.length)];
    const schwer=Math.min(1,spalten.length/330);
    if(seg==='luecke'){ boden(ri(3,5)); for(let i=0;i<ri(2,3+Math.round(schwer));i++)spalten.push(leer()); boden(ri(3,6)); }
    else if(seg==='treppe'){ for(let i=0;i<ri(2,4)&&h>6;i++){ boden(ri(2,3)); h-=ri(1,2);} boden(ri(3,5)); }
    else if(seg==='abwaerts'){ for(let i=0;i<ri(2,4)&&h<BODEN;i++){ boden(ri(2,3)); h=Math.min(BODEN,h+ri(1,2));} boden(3); }
    else if(seg==='stacheln'){ boden(3); const n=ri(1,2+Math.round(schwer)); for(let i=0;i<n;i++){const c=leer();
        for(let y=h;y<ROWS;y++)c[y]=1; c[h-1]=2; spalten.push(c);} boden(ri(3,5)); }
    else if(seg==='plattformen'){ boden(2); const unten=Math.min(ROWS-1,h+1); // Abgrund mit Plattformen
        let ph=h; for(let i=0;i<ri(2,4);i++){ for(let k=0;k<ri(1,2);k++)spalten.push(leer());
          ph=Math.max(5,Math.min(BODEN,ph+ri(-2,1))); for(let k=0;k<ri(2,3);k++){const c=leer();c[ph]=1;spalten.push(c);} }
        for(let k=0;k<ri(1,2);k++)spalten.push(leer()); h=Math.max(6,Math.min(BODEN,ph)); boden(4); }
    else if(seg==='schacht' && h>=10){ // Walljump-Kamin: haengende Saeule links, hohe Wand rechts
        boden(4); const oben=Math.max(3,h-ri(6,7)), breit=ri(2,3);
        const saeule=leer(); for(let y=Math.max(0,oben-2);y<=h-3;y++)saeule[y]=1; for(let y=h;y<ROWS;y++)saeule[y]=1; spalten.push(saeule);
        for(let i=0;i<breit;i++){const c=leer();for(let y=h;y<ROWS;y++)c[y]=1;spalten.push(c);}
        h=oben; boden(ri(4,6)); }
    else boden(3);
    if(++anz%3===0){ boden(2); cp(); }
  }
  boden(6); const z=spalten[spalten.length-3]; z[h-1]=4; ZIEL_X=(spalten.length-3)*T; boden(10);
  COLS=spalten.length; karte=spalten;
}
function kachel(cx,cy){ if(cx<0||cx>=COLS) return 1; if(cy<0) return 0; if(cy>=ROWS) return 0; return karte[cx][cy]; }
const fest=(cx,cy)=>kachel(cx,cy)===1;
// ================= Spieler-Physik
const PW=24, PH=34, G=2300, LAUF=330, BESCHL=3200, BREMS=2600, SPRUNG=-780, WAND_FALL=150, WJ_X=390, WJ_Y=-720;
let ich, start=0;
function neu(cpX=0){ ich={x:cpX+40,y:(BODEN-2)*T-PH, vx:0,vy:0, amBoden:false, wand:0, coyote:0, puffer:0, lebt:true, tot:0, blick:1, cp:cpX, sprungHalten:false};
  // auf festen Boden ueber dem Checkpoint stellen
  const cx=Math.floor((ich.x+PW/2)/T); for(let y=0;y<ROWS;y++){ if(fest(cx,y)){ ich.y=y*T-PH; break; } } }
function kollidiere(achse){
  const x0=Math.floor(ich.x/T), x1=Math.floor((ich.x+PW-1)/T), y0=Math.floor(ich.y/T), y1=Math.floor((ich.y+PH-1)/T);
  for(let cx=x0;cx<=x1;cx++)for(let cy=y0;cy<=y1;cy++){ const k=kachel(cx,cy);
    if(k===2 && ich.y+PH>cy*T+18 && ich.x+PW>cx*T+7 && ich.x<cx*T+T-7){ stirb(); return; } // Stacheln: nur Spitzenbereich, nicht schon beim Streifen der Kante
    if(k===4){ imZiel(); }
    if(k===3){ const px=cx*T; if(px>ich.cp){ ich.cp=px; ton(990,.08,'triangle',.06); setTimeout(()=>ton(1320,.1,'triangle',.06),80);} }
    if(k!==1) continue;
    if(achse==='x'){ if(ich.vx>0) ich.x=cx*T-PW; else if(ich.vx<0) ich.x=(cx+1)*T; ich.vx=0; }
    else { if(ich.vy>0){ ich.y=cy*T-PH; ich.amBoden=true; } else if(ich.vy<0) ich.y=(cy+1)*T; ich.vy=0; }
  }
}
function beruehrtWand(seite){ const x=seite>0?ich.x+PW+1:ich.x-2; const cx=Math.floor(x/T);
  return fest(cx,Math.floor((ich.y+4)/T))||fest(cx,Math.floor((ich.y+PH-6)/T)); }
let zielZeit=null;
function imZiel(){ if(zielZeit===null && st.phase==='spiel'){ zielZeit=(performance.now()-start)/1000; ton(523,.15);setTimeout(()=>ton(659,.15),150);setTimeout(()=>ton(784,.3),300);} }
function stirb(){ if(!ich.lebt) return; ich.lebt=false; ich.tot=0; ich.vy=-500; ton(140,.35,'sawtooth',.08); }
const taste={l:false,r:false,j:false}; let sprungNeu=false;
function schritt(dt){
  const darf=!TV&&id&&(st.phase==='spiel'||st.phase==='lobby') && zielZeit===null;
  if(!ich.lebt){ ich.tot+=dt; ich.vy+=G*dt; ich.y+=ich.vy*dt; if(ich.tot>0.7) neu(ich.cp); return; }
  if(!darf){ ich.vx=0; }
  const rich=darf?(taste.r?1:0)-(taste.l?1:0):0;
  if(rich){ ich.vx+=rich*BESCHL*dt; ich.blick=rich; } else { const b=BREMS*dt; ich.vx=Math.abs(ich.vx)<=b?0:ich.vx-Math.sign(ich.vx)*b; }
  ich.vx=Math.max(-LAUF,Math.min(LAUF,ich.vx));
  ich.coyote=ich.amBoden?0.09:ich.coyote-dt;
  if(sprungNeu&&darf){ ich.puffer=0.12; } sprungNeu=false; ich.puffer-=dt;
  ich.wand=0; if(!ich.amBoden){ if(beruehrtWand(1)&&taste.r) ich.wand=1; else if(beruehrtWand(-1)&&taste.l) ich.wand=-1;
    if(!ich.wand){ if(beruehrtWand(1)) ich.wand=1; else if(beruehrtWand(-1)) ich.wand=-1; } }
  if(ich.puffer>0){
    if(ich.coyote>0){ ich.vy=SPRUNG; ich.coyote=0; ich.puffer=0; ton(520,.07,'square',.04); ich.sprungHalten=true; }
    else if(ich.wand){ ich.vy=WJ_Y; ich.vx=-ich.wand*WJ_X; ich.blick=-ich.wand; ich.puffer=0; ton(700,.07,'square',.05); ich.sprungHalten=true; staub(ich.wand); }
  }
  if(ich.sprungHalten && !taste.j && ich.vy<-250){ ich.vy=-250; ich.sprungHalten=false; } // kurz tippen = kleiner Sprung
  ich.vy+=G*dt; if(ich.wand && ich.vy>WAND_FALL && rich===ich.wand) ich.vy=WAND_FALL; ich.vy=Math.min(1100,ich.vy);
  ich.x+=ich.vx*dt; kollidiere('x'); if(!ich.lebt) return;
  ich.amBoden=false; ich.y+=ich.vy*dt; kollidiere('y');
  if(ich.y>WH+60) stirb();
  if(ich.x<0) ich.x=0;
}
let partikel=[];
function staub(seite){ for(let i=0;i<8;i++) partikel.push({x:ich.x+(seite>0?PW:0),y:ich.y+PH/2,vx:-seite*(60+Math.random()*120),vy:(Math.random()-0.5)*160,t:0.4}); }
