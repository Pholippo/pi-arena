#!/usr/bin/env python3
"""LED-Arcade fuer die geloetete Raspberry-Pi-Platine (HTL 3AHEL, Werkstaette).

Spiele (alle nur mit LEDs + Tastern, optional Buzzer):
  1 Lauflicht-Stopp  - Licht laeuft hin und her, Aktion druecken genau in der Mitte. Wird immer schneller.
  2 Pac-Man 1D       - Du (schnell blinkend) frisst Punkte (leuchtet fix), der Geist (langsam blinkend) jagt dich.
  3 Simon            - LED-Folge merken und mit Links/Aktion/Rechts nachspielen.
  4 Reaktions-Duell  - 2 Spieler: Links gegen Rechts, wer zuerst drueckt, wenn alles aufleuchtet.
Punkte werden am Ende BINAER auf den LEDs angezeigt.

Steuerung gleichzeitig ueber: Taster auf der Platine, Tastatur (a/d/Leertaste, q = Ende)
und Handy-Browser (http://<IP-vom-Pi>:8080 -> virtuelle LEDs + grosse Knoepfe).

Aufrufe:
  python3 ledarcade.py            Menue (Links/Rechts waehlen, Aktion startet)
  python3 ledarcade.py finden     Pins der Platine herausfinden -> pins.json
  python3 ledarcade.py 2          direkt Spiel 2 starten
  python3 ledarcade.py --sim      ohne Raspberry testen (LEDs im Terminal)
  python3 ledarcade.py autostart  startet das Menue kuenftig automatisch beim Booten (sudo)
"""
import json
import os
import queue
import random
import socket
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HIER = os.path.dirname(os.path.abspath(__file__))
CONFIG = os.path.join(HIER, "pins.json")
# Standard = die PiArena-Platine (10 LEDs, Taster 18/23/24, passiver Buzzer 25).
# Andere Platine? "python3 ledarcade.py finden" legt pins.json mit den eigenen Pins an.
STANDARD = {
    "leds": [4, 17, 27, 22, 5, 6, 13, 19, 26, 21],
    "taster": {"links": 18, "rechts": 24, "aktion": 23},
    "pull_up": True,
    "buzzer": 25,
    "buzzer_passiv": True,
}
WEB_PORT = 8080
SPIELE = ["Lauflicht-Stopp", "Pac-Man 1D", "Simon", "Reaktions-Duell", "PAC-PI (Monitor)"]


class Ende(Exception):
    """q gedrueckt -> zurueck ins Menue bzw. beenden."""


def lade_config():
    if os.path.exists(CONFIG):
        with open(CONFIG, encoding="utf-8") as f:
            cfg = json.load(f)
        for k, v in STANDARD.items():
            cfg.setdefault(k, v)
        return cfg
    return dict(STANDARD)


def speichere_config(cfg):
    tmp = CONFIG + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)
    os.replace(tmp, CONFIG)


# ---------------------------------------------------------------- Buzzer-Musik

NOTEN = {"C": 0, "C#": 1, "D": 2, "D#": 3, "E": 4, "F": 5, "F#": 6, "G": 7, "G#": 8, "A": 9, "A#": 10, "B": 11}


def frequenz(note):
    """'A4' -> 440.0, '-' -> None (Pause)."""
    if not note or note == "-":
        return None
    name, okt = note[:-1], int(note[-1])
    return 440.0 * 2 ** ((12 * (okt + 1) + NOTEN[name] - 69) / 12)


class Musik:
    """Spielt Melodien am Buzzer im Hintergrund: eine Endlos-Musik + kurze Effekte, die sich vordraengeln.
    Passiver Buzzer -> echte Toene per PWM. Aktiver Buzzer -> nur der Rhythmus.
    Simulation unter Windows -> Toene ueber den Laptop-Lautsprecher."""

    def __init__(self, pin, passiv=True, sim=False):
        self.dev, self.passiv, self.sim = None, passiv, sim
        self.lautstaerke = 0.5  # PWM-Tastgrad, 0.5 = am lautesten
        if pin is not None:
            try:
                from gpiozero import PWMOutputDevice
                self.dev = PWMOutputDevice(pin, frequency=440, initial_value=0)
            except Exception as e:
                print("Buzzer nicht nutzbar:", e)
        self.an = True
        self._lied, self._idx = None, 0
        self._effekte = queue.Queue()
        self.sink = None  # PAC-PI haengt hier den Monitor-/HDMI-Sound ein (Chiptune)
        threading.Thread(target=self._lauf, daemon=True).start()

    def musik(self, lied):
        if lied is not self._lied:
            self._lied, self._idx = lied, 0
            if self.sink:
                self.sink("musik", lied)

    def stop(self):
        self._lied = None
        if self.sink:
            self.sink("stop", None)

    def effekt(self, lied):
        if self.sink:
            self.sink("effekt", lied)
        if self._effekte.qsize() < 2:  # Effekte am Buzzer nicht aufstauen
            self._effekte.put(lied)

    def _ton(self, note, dauer):
        f = frequenz(note)
        if self.dev:
            if f:
                if self.passiv:
                    self.dev.frequency = f
                    self.dev.value = self.lautstaerke
                else:
                    self.dev.value = 1
            time.sleep(dauer * 0.88)
            self.dev.value = 0
            time.sleep(dauer * 0.12)
        elif self.sim and os.name == "nt" and f and 37 <= f <= 32767:
            import winsound
            winsound.Beep(int(f), max(10, int(dauer * 1000)))
        else:
            time.sleep(dauer)

    def _lauf(self):
        while True:
            try:
                effekt = self._effekte.get_nowait()
                if self.an:
                    for note, dauer in effekt:
                        self._ton(note, dauer)
                continue
            except queue.Empty:
                pass
            lied = self._lied
            if lied and self.an:
                note, dauer = lied[self._idx % len(lied)]
                self._idx += 1
                self._ton(note, dauer)
            else:
                time.sleep(0.02)


def lied(text, tempo=0.12):
    """'C5 E5 G5:2 -' -> [(note, sekunden)], ':2' = doppelt so lang."""
    out = []
    for teil in text.split():
        note, _, mal = teil.partition(":")
        out.append((note, tempo * float(mal or 1)))
    return out


# ---------------------------------------------------------------- Hardware


class Platine:
    def __init__(self, cfg, sim=False):
        self.cfg = cfg
        self.n = len(cfg["leds"])
        self.zustand = [0] * self.n
        self.events = queue.Queue()
        self.sim = sim
        self.text = "Menue"
        self._leds, self._taster = [], []
        if not sim:
            try:
                from gpiozero import LED, Button
            except ImportError:
                print("gpiozero fehlt -> sudo apt install python3-gpiozero   (laufe jetzt im Simulationsmodus)")
                self.sim = True
            else:
                for p in cfg["leds"]:
                    try:
                        self._leds.append(LED(p))
                    except Exception as e:
                        print(f"LED GPIO {p} belegt, uebersprungen: {e}")
                        self._leds.append(None)
                for name, pin in cfg["taster"].items():
                    if pin is None:
                        continue
                    try:
                        b = Button(pin, pull_up=cfg.get("pull_up", True), bounce_time=0.03)
                    except Exception as e:  # belegter Pin darf das Game nicht killen -> Tastatur/Handy bleiben
                        print(f"Taster '{name}' GPIO {pin} belegt, uebersprungen: {e}")
                        continue
                    # "t_" = kommt vom Taster (Pac-Man lenkt damit relativ: links/rechts abbiegen)
                    b.when_pressed = lambda n=name: self.events.put("t_" + n)
                    self._taster.append(b)
                self.n = len(self._leds) or self.n
        self.musik = Musik(None if self.sim else cfg.get("buzzer"), cfg.get("buzzer_passiv", True), self.sim)
        threading.Thread(target=self._tastatur, daemon=True).start()

    # LEDs
    def zeige(self, muster):
        muster = [1 if x else 0 for x in muster][: self.n]
        muster += [0] * (self.n - len(muster))
        if muster == self.zustand:
            return
        self.zustand = muster
        for led, an in zip(self._leds, muster):
            if led is not None:
                led.value = an
        if self.sim:
            sys.stdout.write("\r  " + " ".join("●" if a else "○" for a in muster) + f"   {self.text:<30}")
            sys.stdout.flush()

    def aus(self):
        self.zeige([0] * self.n)

    def piep(self, dauer=0.05, note="A5"):
        self.musik.effekt([(note, dauer)])

    # Eingaben
    def leeren(self):
        while not self.events.empty():
            self.events.get_nowait()

    def warte(self, timeout):
        """Naechste Eingabe ('links'/'rechts'/'aktion') oder None nach timeout Sekunden."""
        try:
            e = self.events.get(timeout=max(0.0, timeout))
        except queue.Empty:
            return None
        if e == "ende":
            raise Ende()
        if e.startswith("t_"):
            e = e[2:]
        return "aktion" if e in ("oben", "unten") else e

    def pause(self, sekunden):
        """Wartet, ignoriert Eingaben, reagiert aber auf q."""
        ende = time.time() + sekunden
        while time.time() < ende:
            self.warte(ende - time.time())

    def _tastatur(self):
        tasten = {"a": "links", "d": "rechts", " ": "aktion", "w": "oben", "s": "unten",
                  "\r": "aktion", "\n": "aktion", "q": "ende"}
        if not sys.stdin or not sys.stdin.isatty():
            return
        try:
            if os.name == "nt":
                import msvcrt
                while True:
                    k = msvcrt.getwch()
                    if k in ("\x00", "\xe0"):
                        k = {"K": "a", "M": "d", "H": "w", "P": "s"}.get(msvcrt.getwch(), "")
                    if k.lower() in tasten:
                        self.events.put(tasten[k.lower()])
            else:
                import termios
                import tty
                fd = sys.stdin.fileno()
                alt = termios.tcgetattr(fd)
                import atexit
                atexit.register(termios.tcsetattr, fd, termios.TCSADRAIN, alt)
                tty.setcbreak(fd)
                puffer = ""
                while True:
                    puffer += sys.stdin.read(1)
                    if puffer.startswith("\x1b"):  # Pfeiltasten
                        if len(puffer) < 3:
                            continue
                        k = {"[D": "a", "[C": "d", "[A": "w", "[B": "s"}.get(puffer[1:3], "")
                    else:
                        k = puffer
                    puffer = ""
                    if k.lower() in tasten:
                        self.events.put(tasten[k.lower()])
        except Exception as e:  # Tastatur ist nur Zusatz, Taster/Handy gehen weiter
            print("Tastatur nicht verfuegbar:", e)


# ---------------------------------------------------------------- Handy-Steuerung

SEITE = """<!doctype html><html lang=de><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1,user-scalable=no">
<title>LED-Arcade</title><style>
body{margin:0;background:#0b0f14;color:#e8eef5;font-family:system-ui,sans-serif;text-align:center;
user-select:none;-webkit-user-select:none;touch-action:manipulation}
h1{font-size:22px;margin:18px 0 4px}#t{opacity:.75;min-height:22px}
#l{display:flex;justify-content:center;gap:8px;margin:22px 10px;flex-wrap:wrap}
.d{width:30px;height:30px;border-radius:50%;background:#2a1212;transition:background .05s}
.d.on{background:#ff3b3b;box-shadow:0 0 18px #ff3b3b}
#b{display:flex;gap:10px;padding:0 12px;max-width:520px;margin:30px auto}
button{flex:1;height:110px;font-size:22px;border:0;border-radius:18px;background:#1f6feb;color:#fff}
button.a{background:#2ea043}button:active{filter:brightness(1.4)}
</style></head><body><h1>LED-Arcade</h1><div id=t></div><div id=l></div>
<div id=b style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:10px">
<span></span><button data-k=oben>▲</button><span></span>
<button data-k=links>◀</button><button class=a data-k=aktion>●</button><button data-k=rechts>▶</button>
<span></span><button data-k=unten>▼</button><span></span></div>
<script>
const L=document.getElementById('l'),T=document.getElementById('t');
document.querySelectorAll('button').forEach(b=>b.addEventListener('pointerdown',e=>{e.preventDefault();
fetch('/druck?k='+b.dataset.k)}));
async function lauf(){try{const s=await (await fetch('/zustand')).json();
if(L.children.length!=s.leds.length){L.innerHTML='';s.leds.forEach(()=>{const d=document.createElement('div');d.className='d';L.appendChild(d)})}
s.leds.forEach((a,i)=>L.children[i].classList.toggle('on',!!a));T.textContent=s.text}catch(e){T.textContent='keine Verbindung'}
setTimeout(lauf,60)}lauf();
</script></body></html>"""


def starte_web(platine):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _antwort(self, body, typ):
            daten = body.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", typ)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(daten)))
            self.end_headers()
            self.wfile.write(daten)

        def do_GET(self):
            if self.path.startswith("/zustand"):
                self._antwort(json.dumps({"leds": platine.zustand, "text": platine.text}), "application/json")
            elif self.path.startswith("/druck?k="):
                k = self.path.split("=", 1)[1]
                if k in ("links", "rechts", "aktion", "oben", "unten"):
                    platine.events.put(k)
                self._antwort("ok", "text/plain")
            else:
                self._antwort(SEITE, "text/html; charset=utf-8")

    try:
        srv = ThreadingHTTPServer(("0.0.0.0", WEB_PORT), H)
    except OSError as e:
        print(f"Handy-Steuerung aus (Port {WEB_PORT}: {e})")
        return
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    print(f"Handy-Steuerung: http://{eigene_ip()}:{WEB_PORT}  (Handy im selben WLAN)")


def eigene_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        return "localhost"


# ---------------------------------------------------------------- Effekte


def blinke_alle(p, mal=3, t=0.15):
    for _ in range(mal):
        p.zeige([1] * p.n)
        p.pause(t)
        p.aus()
        p.pause(t)


def welle(p, t=0.04):
    for i in list(range(p.n)) + list(range(p.n - 2, -1, -1)):
        p.zeige([j == i for j in range(p.n)])
        p.pause(t)
    p.aus()


def zeige_punkte(p, punkte, name):
    """Punkte binaer auf den LEDs (LSB rechts), 4 s lang."""
    p.text = f"{name}: {punkte} Punkte = {punkte:0{p.n}b}"
    print(f"\n  {p.text}")
    bits = [(punkte >> (p.n - 1 - i)) & 1 for i in range(p.n)]
    p.zeige(bits)
    p.pause(4)
    p.aus()


# ---------------------------------------------------------------- Spiele


def spiel_lauflicht(p):
    ziel = p.n // 2
    pos, richtung, tempo, punkte = 0, 1, 0.22, 0
    p.text = f"Lauflicht: Aktion bei LED {ziel + 1}!"
    p.leeren()
    while True:
        p.zeige([i == pos for i in range(p.n)])
        e = p.warte(tempo)
        if e == "aktion":
            if pos == ziel:
                punkte += 1
                p.piep()
                p.text = f"Lauflicht: TREFFER {punkte}"
                blinke_alle(p, 1, 0.08)
                tempo = max(0.035, tempo * 0.85)
                p.leeren()
            else:
                p.piep(0.4)
                blinke_alle(p, 3)
                return punkte
        elif e is None:
            pos += richtung
            if pos in (0, p.n - 1):
                richtung = -richtung


def spiel_pacman(p):
    spieler, punkt = 0, p.n - 1
    geist = p.n // 2
    geist_takt, punkte = 0.9, 0
    naechster_geist = time.time() + 1.5
    p.text = "Pac-Man: friss den festen Punkt!"
    p.leeren()
    start = time.time()
    while True:
        jetzt = time.time()
        t = jetzt - start
        muster = [0] * p.n
        muster[punkt] = 1
        if int(t * 2.5) % 2 == 0:  # Geist: langsam blinkend
            muster[geist] = 1
        if int(t * 12) % 2 == 0:  # Du: schnell blinkend (liegt oben)
            muster[spieler] = 1
        elif spieler != punkt:
            muster[spieler] = 0
        p.zeige(muster)

        e = p.warte(0.03)
        if e == "links":
            spieler = (spieler - 1) % p.n
        elif e == "rechts":
            spieler = (spieler + 1) % p.n
        if spieler == punkt:
            punkte += 1
            p.piep()
            p.text = f"Pac-Man: {punkte} gefressen"
            frei = [i for i in range(p.n) if i not in (spieler, geist)]
            punkt = random.choice(frei)
            geist_takt = max(0.25, geist_takt * 0.9)
        if jetzt >= naechster_geist:
            naechster_geist = jetzt + geist_takt
            # kuerzester Weg im Kreis zum Spieler, manchmal ein Fehler, damit es fair bleibt
            vor = (spieler - geist) % p.n
            schritt = 1 if vor <= p.n - vor else -1
            if random.random() < 0.15:
                schritt = -schritt
            geist = (geist + schritt) % p.n
        if geist == spieler:
            p.piep(0.5)
            p.text = "Pac-Man: GEFRESSEN!"
            blinke_alle(p, 4, 0.1)
            return punkte


def spiel_simon(p):
    felder = {"links": 0, "aktion": p.n // 2, "rechts": p.n - 1}
    namen = list(felder)
    folge, runde = [], 0
    while True:
        folge.append(random.choice(namen))
        p.text = f"Simon: merken! ({len(folge)})"
        p.pause(0.6)
        tempo = max(0.18, 0.5 - 0.03 * len(folge))
        for k in folge:
            p.zeige([i == felder[k] for i in range(p.n)])
            p.piep(0.05)
            p.pause(tempo)
            p.aus()
            p.pause(0.12)
        p.text = "Simon: jetzt du!"
        p.leeren()
        for k in folge:
            e = p.warte(4)
            if e is not None:
                p.zeige([i == felder[e] for i in range(p.n)])
                p.pause(0.15)
                p.aus()
            if e != k:
                p.piep(0.5)
                p.text = "Simon: falsch!"
                blinke_alle(p, 3)
                return runde
        runde += 1
        welle(p, 0.03)


def spiel_duell(p):
    stand = {"links": 0, "rechts": 0}
    ziel = 3
    while max(stand.values()) < ziel:
        p.text = f"Duell  L {stand['links']} : {stand['rechts']} R  - warten..."
        halb = p.n // 2
        p.zeige([i < stand["links"] or i >= p.n - stand["rechts"] for i in range(p.n)])
        p.pause(1.2)
        p.aus()
        p.leeren()
        e = p.warte(random.uniform(1.5, 4.5))
        if e in stand:  # zu frueh -> Punkt fuer den anderen
            gegner = "rechts" if e == "links" else "links"
            stand[gegner] += 1
            p.text = f"{e} zu FRUEH!"
            seite = range(0, halb) if e == "links" else range(halb, p.n)
            for _ in range(3):
                p.zeige([i in seite for i in range(p.n)])
                p.pause(0.12)
                p.aus()
                p.pause(0.12)
            continue
        p.zeige([1] * p.n)
        p.piep(0.1)
        t0 = time.time()
        e = None
        while e not in stand:
            e = p.warte(3)
            if e is None:
                break
        if e is None:
            continue
        ms = int((time.time() - t0) * 1000)
        stand[e] += 1
        p.text = f"{e} gewinnt die Runde ({ms} ms)"
        print(f"\n  {p.text}")
        seite = range(0, halb) if e == "links" else range(halb, p.n)
        p.zeige([i in seite for i in range(p.n)])
        p.pause(1.0)
    sieger = max(stand, key=stand.get)
    p.text = f"Duell: {sieger.upper()} gewinnt!"
    print(f"\n  {p.text}")
    for _ in range(6):
        welle(p, 0.02)
    return stand[sieger]


def spiel_monitor(p):
    try:
        import pacpi
    except ImportError as e:
        print("Pac-Pi braucht pygame: sudo apt install python3-pygame  (", e, ")")
        blinke_alle(p, 2)
        return 0
    return pacpi.starte(p)


FUNKTIONEN = [spiel_lauflicht, spiel_pacman, spiel_simon, spiel_duell, spiel_monitor]


def spiele(p, nr):
    name = SPIELE[nr]
    print(f"\n>> {name}")
    p.text = name
    welle(p)
    punkte = FUNKTIONEN[nr](p)
    zeige_punkte(p, punkte, name)


def menue(p):
    wahl = 0
    print("Menue: Links/Rechts waehlen, Aktion = Start, q = Ende")
    welle(p)
    while True:
        p.text = f"Spiel {wahl + 1}: {SPIELE[wahl]}"
        p.zeige([i == wahl for i in range(p.n)])
        e = p.warte(0.5)
        if e == "links":
            wahl = (wahl - 1) % len(SPIELE)
        elif e == "rechts":
            wahl = (wahl + 1) % len(SPIELE)
        elif e == "aktion":
            try:
                spiele(p, wahl)
            except Ende:
                p.aus()
                print("\n(abgebrochen, zurueck im Menue - nochmal q = Ende)")
            p.leeren()


# ---------------------------------------------------------------- Pins finden


def pins_finden():
    try:
        from gpiozero import LED, DigitalInputDevice, Buzzer  # noqa: F401
    except ImportError:
        sys.exit("gpiozero fehlt: sudo apt install python3-gpiozero")
    kandidaten = list(range(2, 28))
    cfg = lade_config()
    leds, buzzer = [], None
    from gpiozero import PWMOutputDevice
    print("Schritt 1: Jeder GPIO bekommt kurz einen 880-Hz-Ton (LEDs leuchten dabei, Buzzer piepen).")
    print("  Enter = nichts passiert,  j = eine LED leuchtet,  b = es piept,  f = fertig\n")
    passiv = True
    for pin in kandidaten:
        try:
            dev = PWMOutputDevice(pin, frequency=880)
        except Exception as e:
            print(f"  GPIO {pin:2}: belegt ({e})")
            continue
        dev.value = 0.5
        antwort = input(f"  GPIO {pin:2} ist an - leuchtet/piept was? ").strip().lower()
        dev.value = 0
        if antwort == "b":
            for f in (523, 659, 784, 1047):
                dev.frequency = f
                dev.value = 0.5
                time.sleep(0.18)
            dev.value = 0
            passiv = input("  Hast du eine Melodie (4 verschiedene Toene) gehoert? [j/n] ").strip().lower() != "n"
        dev.close()
        if antwort == "j":
            leds.append(pin)
        elif antwort == "b":
            buzzer = pin
        elif antwort == "f":
            break
    if not leds:
        sys.exit("Keine LED gefunden - Platine richtig aufgesteckt? Nichts gespeichert.")
    print(f"\nLEDs: {leds}  (Reihenfolge = so wie gefunden; links->rechts? sonst in pins.json umsortieren)")

    print("\nSchritt 2: Taster. Halte jeweils den Taster gedrueckt, bis er erkannt ist.")
    rest = [p for p in kandidaten if p not in leds and p != buzzer]
    taster, pull_up = {}, True
    for name in ("links", "rechts", "aktion"):
        gefunden = None
        for pu in ([pull_up] if taster else [True, False]):
            eing = []
            for pin in rest:
                if pin in taster.values():
                    continue
                try:
                    eing.append((pin, DigitalInputDevice(pin, pull_up=pu)))
                except Exception:
                    pass
            ruhe = {pin: d.value for pin, d in eing}
            print(f"  Taster '{name}' druecken ... (15 s)")
            ende = time.time() + 15
            while time.time() < ende and gefunden is None:
                for pin, d in eing:
                    if d.value != ruhe[pin]:
                        gefunden, pull_up = pin, pu
                        break
                time.sleep(0.01)
            for _, d in eing:
                d.close()
            if gefunden is not None:
                break
        if gefunden is None:
            print(f"  '{name}' nicht gefunden -> wird per Handy/Tastatur gesteuert")
        else:
            print(f"  '{name}' = GPIO {gefunden}")
            taster[name] = gefunden
            time.sleep(0.8)  # loslassen
    cfg.update({"leds": leds, "taster": {k: taster.get(k) for k in ("links", "rechts", "aktion")},
                "pull_up": pull_up, "buzzer": buzzer, "buzzer_passiv": passiv})
    speichere_config(cfg)
    print(f"\nGespeichert in {CONFIG}:\n{json.dumps(cfg, indent=2)}\nJetzt: python3 ledarcade.py")


def autostart():
    dienst = f"""[Unit]
Description=LED-Arcade
After=network-online.target

[Service]
ExecStart=/usr/bin/python3 {os.path.abspath(__file__)}
WorkingDirectory={HIER}
Restart=on-failure
User={os.environ.get('SUDO_USER') or os.environ.get('USER', 'pi')}

[Install]
WantedBy=multi-user.target
"""
    pfad = "/etc/systemd/system/ledarcade.service"
    try:
        with open(pfad, "w") as f:
            f.write(dienst)
    except PermissionError:
        sys.exit("Bitte mit sudo: sudo python3 ledarcade.py autostart")
    os.system("systemctl daemon-reload && systemctl enable --now ledarcade.service")
    print("Autostart an. Ausschalten: sudo systemctl disable --now ledarcade")


# ---------------------------------------------------------------- Start


def main():
    args = [a for a in sys.argv[1:]]
    sim = "--sim" in args
    args = [a for a in args if a != "--sim"]
    if args and args[0] == "finden":
        return pins_finden()
    if args and args[0] == "autostart":
        return autostart()
    p = Platine(lade_config(), sim=sim)
    starte_web(p)
    try:
        if args and args[0].isdigit() and 1 <= int(args[0]) <= len(SPIELE):
            spiele(p, int(args[0]) - 1)
        else:
            menue(p)
    except (Ende, KeyboardInterrupt):
        pass
    finally:
        p.aus()
        print("\nTschuess!")


if __name__ == "__main__":
    main()
