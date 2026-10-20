#!/usr/bin/env python3
"""MEGA-PARTY Client - laeuft auf JEDEM Schueler-Pi mit der gleichen geloeteten Platine.

WAS MACHT DIE DATEI?
  Jede/r spielt auf dem EIGENEN Board gegen alle anderen. Der Host (mega.py auf dem Pi mit Monitor)
  startet die Minispiele gleichzeitig, sammelt die Ergebnisse und vergibt Punkte nach Platz.
    - 3 Taster  = Eingabe (links / mitte / rechts)
    - Buzzer    = Rueckmeldung (Treffer, Fehler, Countdown, Sieg)
    - 10 LEDs   = DEIN SCORE: so viele LEDs leuchten, so viele Punkte hast du. 10 LEDs = gewonnen!
      Waehrend einer Runde gehoeren die LEDs dem Spiel, danach zeigen sie wieder den Score.
  Browser-Runden (NINJA/FLAPPY/AUTO): der Client oeffnet das Spiel selbst im Browser (Name schon drin)
  und schliesst es danach wieder.
  Die Datei ist gleichzeitig eine Bibliothek fuer mega.py: Platine (Brett), Minispiele (SPIELE), Client.

LED-Signale ausserhalb der Runden:
  LED 1 und 10 blinken abwechselnd  -> suche Host / Verbindung weg (verbindet sich selbst neu)
  ein Licht wandert ueber den Score -> verbunden, warte auf den Start

WIE STARTEN? (EIN Befehl, der Host zeigt ihn mit seiner IP am Monitor an; fragt dann nach deinem Namen)
  curl http://<HOST-IP>:8081/j | python3
  Der Host traegt dabei seine Adressen ein (STANDARD_HOSTS); klappt keine, sucht der Client per UDP.

Optionen:
  --name Max        Anzeigename am Monitor (Standard: Hostname)
  --host <IP>       Host-IP direkt angeben (sonst eingetragene Adressen, dann UDP-Suche)
  --sim             ohne Platine (Laptop): Tasten a / s / d, LEDs im Terminal
  --bot             spielt selbst (zum Testen)
  Umgebungsvariable MEGA_BROWSER="firefox --kiosk"  -> anderer Browser fuer die Browser-Runden

NEUES BOARD-MINISPIEL DAZUBAUEN:
  1. Funktion spiel_xyz(b, p, rng) schreiben (Vorlage: spiel_tap). b = Brett (b.warte, b.zeige, b.ton),
     p = Parameter vom Host, rng = gemeinsamer Zufall. Rueckgabe {"wert": Zahl, "ok": bool, "text": str}.
  2. Eintrag in SPIELE unten (Name, Regeltext, "besser" hoch/tief, Dauer, Taster-Beschriftung).
  3. In mega.py: Farbe in SPIEL_FARBE, optional eigenes Bild in App._laeuft. Fertig - die Rotation
     nimmt es automatisch, ausser es steht in mega.DEAKTIVIERT.
"""
import argparse
import json
import math
import os
import queue
import random
import shlex
import shutil
import subprocess
import socket
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

# ---------------------------------------------------------------- Einstellungen

LED_PINS = [4, 17, 27, 22, 5, 6, 13, 19, 26, 21]  # links -> rechts
TASTER = {"links": 18, "mitte": 23, "rechts": 24}  # pull_up, gegen GND
BUZZER_PIN = 25  # passiver Buzzer
N = len(LED_PINS)
TASTEN = ("links", "mitte", "rechts")
HOST_PORT = 8081  # TCP: mega.py (Handy-Seite, /j, Spiel-API)
WEB_PORT = 8082  # TCP: webspiele.py (Browser-Runden)
SUCH_PORT = 8082  # UDP: der Host ruft jede Sekunde "MEGA-PARTY <port>" ins Netz
STANDARD_HOSTS = []  # traegt der Host beim Ausliefern (/j) ein: zuerst die Adresse aus dem curl-Befehl, dann alle anderen
POLL = 0.3  # Sekunden zwischen zwei Anfragen an den Host


class Abbruch(Exception):
    """Runde wurde vom Host abgebrochen (Moderator hat uebersprungen)."""


# ---------------------------------------------------------------- Toene

NOTEN = {"C": 0, "C#": 1, "D": 2, "D#": 3, "E": 4, "F": 5, "F#": 6, "G": 7, "G#": 8, "A": 9, "A#": 10, "B": 11}


def frequenz(note):
    """'A4' -> 440.0, '-' -> None (Pause)."""
    if not note or note == "-":
        return None
    name, okt = note[:-1], int(note[-1])
    return 440.0 * 2 ** ((12 * (okt + 1) + NOTEN[name] - 69) / 12)


def lied(text, tempo=0.1):
    """'C5 E5 G5:2 -' -> [(note, sekunden)], ':2' = doppelt so lang."""
    out = []
    for teil in text.split():
        note, _, mal = teil.partition(":")
        out.append((note, tempo * float(mal or 1)))
    return out


def kurz(note, dauer=0.07):
    return [(note, dauer)]


T_KLICK = lied("E6", 0.03)
T_ZAEHL = lied("A5", 0.08)
T_LOS = lied("A6:2", 0.09)
T_TREFFER = lied("C6 G6", 0.04)
T_SUPER = lied("C6 E6 G6 C7:2", 0.035)
T_FEHL = lied("A3 F3:2", 0.08)
T_FOUL = lied("C4 - C4 - C4", 0.06)
T_VERBUNDEN = lied("C5 G5 C6", 0.07)
FANFARE = lied("C6 C6 G5 C6 E6:2 - C6 E6 G6:3", 0.11)
SIMON_TON = ["C5", "E5", "G5"]
SIMON_LEDS = [(0, 1, 2), (3, 4, 5, 6), (7, 8, 9)]  # links / mitte / rechts als LED-Gruppen
TAP_TOENE = "C5 D5 E5 G5 A5 C6 D6 E6 G6 A6 C7".split()


# ---------------------------------------------------------------- Platine


class Brett:
    """Die Platine: 10 LEDs, 3 Taster, Buzzer. Jeder Pin einzeln probiert -> belegter Pin = uebersprungen.
    Ohne Hardware (sim) bzw. als virtuelles Brett fuer Handy-Spieler/Bots laeuft alles gleich, nur ohne GPIO."""

    def __init__(self, sim=False, bot=False, tastatur=False, ausgabe=False):
        self.zustand = [0] * N
        self.events = queue.Queue()
        self.abbruch = threading.Event()
        self.bot = random.Random() if bot else None
        self.skill = self.bot.uniform(0.8, 1.25) if bot else 1.0  # >1 = langsamer/schlechter
        self.leds = [None] * N
        self.knoepfe = {}
        self.zuletzt = {k: 0.0 for k in TASTEN}
        self.dev = None
        self.f_jetzt = 0.0  # aktuelle Buzzer-Frequenz (fuer die Live-GPIO-Anzeige)
        self.ton_log = []  # (nr, [[hz, sek], ...]) -> Handy spielt die Toene im Browser nach
        self.ton_nr = 0
        self.status = ""
        self.ausgabe = ausgabe
        self._neu = None
        self._lock = threading.Lock()
        if not sim:
            self._hardware()
        threading.Thread(target=self._buzzer, daemon=True).start()
        if tastatur:
            threading.Thread(target=self._tastatur, daemon=True).start()

    def _hardware(self):
        """Jeden Pin einzeln holen. Belegt (z.B. Thonny laeuft noch) oder kaputt -> Pin weglassen, nie abstuerzen."""
        try:
            from gpiozero import LED, Button, PWMOutputDevice
        except Exception as e:
            print("gpiozero nicht verfuegbar -> ohne Platine:", e)
            return
        for i, pin in enumerate(LED_PINS):
            try:
                self.leds[i] = LED(pin)
            except Exception as e:  # z.B. anderes Programm benutzt den Pin
                print(f"LED GPIO {pin} nicht nutzbar, uebersprungen: {e}")
        for name, pin in TASTER.items():
            try:
                b = Button(pin, pull_up=True, bounce_time=0.02)
                b.when_pressed = lambda n=name: self.druck(n)
                self.knoepfe[name] = b
            except Exception as e:
                print(f"Taster '{name}' GPIO {pin} nicht nutzbar, uebersprungen: {e}")
        try:
            self.dev = PWMOutputDevice(BUZZER_PIN, frequency=440, initial_value=0)
        except Exception as e:
            print(f"Buzzer GPIO {BUZZER_PIN} nicht nutzbar, laufe ohne Ton: {e}")
        ok = sum(1 for x in self.leds if x)
        print(f"Platine: {ok}/{N} LEDs, {len(self.knoepfe)}/3 Taster, Buzzer {'ja' if self.dev else 'nein'}")

    # Eingabe
    def druck(self, k):
        jetzt = time.monotonic()
        self.zuletzt[k] = jetzt
        self.events.put((k, jetzt))  # Zeitstempel direkt beim Druecken -> Reaktionszeit ohne Netzwerk-Verzoegerung

    def gedrueckt(self, k):
        b = self.knoepfe.get(k)
        if b is not None:
            try:
                return b.is_pressed
            except Exception:
                pass
        return time.monotonic() - self.zuletzt[k] < 0.15

    def leeren(self):
        while not self.events.empty():
            try:
                self.events.get_nowait()
            except queue.Empty:
                break

    def warte(self, timeout):
        """Naechster Tastendruck (taste, zeitpunkt) oder None nach timeout Sekunden."""
        ende = time.monotonic() + max(0.0, timeout)
        while True:
            if self.abbruch.is_set():
                raise Abbruch()
            rest = ende - time.monotonic()
            if rest <= 0:
                return None
            try:
                return self.events.get(timeout=min(0.05, rest))
            except queue.Empty:
                pass

    def pause(self, sekunden):
        """Wartet und verwirft Eingaben (bricht aber bei Abbruch ab)."""
        ende = time.monotonic() + sekunden
        while time.monotonic() < ende:
            self.warte(ende - time.monotonic())

    def bot_drueck(self, k, nach):
        """Bot: Taste k in 'nach' Sekunden druecken (laeuft nebenher)."""
        if self.bot:
            t = threading.Timer(max(0.0, nach), self.druck, (k,))
            t.daemon = True
            t.start()

    # Ausgabe
    def zeige(self, muster):
        muster = [1 if x else 0 for x in muster][:N] + [0] * max(0, N - len(muster))
        if muster == self.zustand:
            return
        self.zustand = muster
        for led, an in zip(self.leds, muster):
            if led is not None:
                try:
                    led.value = an
                except Exception:
                    pass
        if self.ausgabe:
            sys.stdout.write("\r  " + " ".join("●" if a else "○" for a in muster) + f"   {self.status[:34]:<34}")
            sys.stdout.flush()

    def ton(self, melodie):
        """Neuester Ton verdraengt den alten -> jede Eingabe ist sofort hoerbar."""
        with self._lock:
            self._neu = melodie
            self.ton_nr += 1
            self.ton_log.append((self.ton_nr, [[round(frequenz(n) or 0), d] for n, d in melodie]))
            del self.ton_log[:-30]

    def _buzzer(self):
        while True:
            with self._lock:
                mel, self._neu = self._neu, None
            if not mel:
                time.sleep(0.004)
                continue
            try:
                for note, dauer in mel:
                    if self._neu:
                        break
                    f = frequenz(note)
                    self.f_jetzt = f or 0.0
                    if self.dev:
                        if f:
                            self.dev.frequency = f
                            self.dev.value = 0.5  # 50 % Tastgrad = am lautesten
                        else:
                            self.dev.value = 0
                    time.sleep(dauer)
                self.f_jetzt = 0.0
                if self.dev:
                    self.dev.value = 0
            except Exception as e:
                print("Buzzer-Fehler:", e)
                time.sleep(0.5)

    def _tastatur(self):
        tasten = {"a": "links", "s": "mitte", "d": "rechts", " ": "mitte", "j": "links", "k": "mitte", "l": "rechts"}
        if not sys.stdin or not sys.stdin.isatty():
            return
        try:
            if os.name == "nt":
                import msvcrt
                while True:
                    k = msvcrt.getwch().lower()
                    if k == "q":
                        os._exit(0)
                    if k in tasten:
                        self.druck(tasten[k])
            else:
                import atexit
                import termios
                import tty
                fd = sys.stdin.fileno()
                alt = termios.tcgetattr(fd)
                atexit.register(termios.tcsetattr, fd, termios.TCSADRAIN, alt)
                tty.setcbreak(fd)
                while True:
                    k = sys.stdin.read(1).lower()
                    if k == "q":
                        termios.tcsetattr(fd, termios.TCSADRAIN, alt)
                        os._exit(0)
                    if k in tasten:
                        self.druck(tasten[k])
        except Exception as e:  # Tastatur ist nur Zusatz
            print("Tastatur nicht verfuegbar:", e)

    def schliessen(self):
        self.zeige([0] * N)
        for d in self.leds + list(self.knoepfe.values()) + [self.dev]:
            if d is not None:
                try:
                    d.close()
                except Exception:
                    pass


def balken(wert):
    return [i < wert for i in range(N)]


def blinke(b, muster, mal=3, t=0.1):
    for _ in range(mal):
        b.zeige(muster)
        b.pause(t)
        b.zeige([0] * N)
        b.pause(t)


# ---------------------------------------------------------------- Minispiele
# Jedes Spiel laeuft komplett auf dem eigenen Board (keine Netzwerk-Verzoegerung) und liefert
# {"wert": Zahl, "ok": gueltig?, "text": fuer den Monitor}. rng ist fuer alle gleich (gleicher Seed)
# -> alle Boards blitzen/piepen gleichzeitig. Zufall fuer Bots kommt aus b.bot (eigener Zufall).


def spiel_reaktion(b, p, rng):
    zeiten = []
    for versuch in range(3):
        b.zeige([0] * N)
        b.leeren()
        b.status = f"Reaktion {versuch + 1}/3 - warten..."
        warte = rng.uniform(1.0, 2.8)
        if b.bot and b.bot.random() < 0.06:
            b.bot_drueck("mitte", warte * 0.7)  # Bot macht auch mal einen Fruehstart
        if b.warte(warte):
            zeiten.append(1000)  # Fruehstart = Strafe 1000 ms
            b.status = "FRUEHSTART! +1000 ms"
            b.ton(T_FOUL)
            for _ in range(3):
                b.zeige([i % 2 for i in range(N)])
                b.pause(0.1)
                b.zeige([(i + 1) % 2 for i in range(N)])
                b.pause(0.1)
            b.zeige([0] * N)
            b.pause(0.4)
            continue
        b.zeige([1] * N)  # BLITZ!
        t0 = time.monotonic()
        b.ton(T_LOS)
        if b.bot:
            b.bot_drueck("mitte", b.bot.uniform(0.17, 0.42) * b.skill)
        e = b.warte(1.5)
        ms = 1500 if e is None else int((e[1] - t0) * 1000)
        zeiten.append(ms)
        b.status = f"{ms} ms"
        b.ton(T_TREFFER if ms < 350 else T_KLICK)
        b.zeige(balken(max(1, min(N, (650 - ms) // 45))))  # schnell = viele LEDs
        b.pause(0.8)
    schnitt = sum(zeiten) / len(zeiten)
    return {"wert": round(schnitt), "ok": True, "text": f"{schnitt:.0f} ms (" + "/".join(map(str, zeiten)) + ")"}


def spiel_lauflicht(b, p, rng):
    summe, einzeln = 0, []
    for tempo in (0.11, 0.075, 0.05):  # wird jede Runde schneller
        b.leeren()
        pos, richtung = 0, 1
        b.status = "Stopp in der Mitte (LED 5/6)!"
        ende = time.monotonic() + 8
        bot_ziel = b.bot.choice([4, 5, 4, 5, 3, 6, 2, 7]) if b.bot else None
        bot_vorbei, bot_runden = 0, (b.bot.randint(1, 2) if b.bot else 0)
        gestoppt = None
        while time.monotonic() < ende:
            b.zeige([i == pos for i in range(N)])
            if b.bot and pos == bot_ziel:
                bot_vorbei += 1
                if bot_vorbei > bot_runden:
                    b.druck("mitte")
            if b.warte(tempo):
                gestoppt = pos
                break
            pos += richtung
            if pos in (0, N - 1):
                richtung = -richtung
        weg = 5 if gestoppt is None else min(abs(gestoppt - 4), abs(gestoppt - 5))
        summe += weg
        einzeln.append(weg)
        if weg == 0:
            b.ton(T_SUPER)
            blinke(b, [i in (4, 5) for i in range(N)], 3, 0.08)
        else:
            b.ton(T_TREFFER if weg == 1 else T_FEHL)
            blinke(b, [i == gestoppt for i in range(N)], 2, 0.12)
        b.pause(0.3)
    return {"wert": summe, "ok": True, "text": f"{summe} daneben (" + "/".join(map(str, einzeln)) + ")"}


def spiel_simon(b, p, rng):
    folge = [rng.randrange(3) for _ in range(16)]
    ende = time.monotonic() + p.get("dauer", 50) - 3
    stufen, eingabe_zeit = 0, 0.0
    for laenge in range(3, 17):
        b.status = f"Simon: merken ({laenge})"
        b.zeige([0] * N)
        b.pause(0.5)
        tempo = max(0.22, 0.5 - 0.02 * laenge)
        for s in folge[:laenge]:
            b.zeige([i in SIMON_LEDS[s] for i in range(N)])
            b.ton(kurz(SIMON_TON[s], tempo * 0.9))
            b.pause(tempo)
            b.zeige([0] * N)
            b.pause(0.1)
        b.leeren()
        b.status = "jetzt du!"
        t0 = time.monotonic()
        verzoegerung = 0.0
        for s in folge[:laenge]:
            if b.bot:
                richtig = b.bot.random() < 0.95
                verzoegerung = b.bot.uniform(0.3, 0.6) * b.skill
                b.bot_drueck(TASTEN[s] if richtig else TASTEN[(s + 1) % 3], verzoegerung)
            e = b.warte(3.0)
            if e is None or TASTEN.index(e[0]) != s:
                b.ton(T_FEHL)
                blinke(b, [1] * N, 3, 0.1)
                return {"wert": stufen * 100 - min(99, eingabe_zeit), "ok": stufen > 0, "text": f"{stufen} Stufen"}
            b.zeige([i in SIMON_LEDS[s] for i in range(N)])  # bleibt an bis zum naechsten Druck
            b.ton(kurz(SIMON_TON[s], 0.12))
        eingabe_zeit += time.monotonic() - t0
        stufen = laenge
        b.ton(T_TREFFER)
        for i in range(N):
            b.zeige([j == i for j in range(N)])
            b.pause(0.02)
        if time.monotonic() > ende:
            break
    return {"wert": stufen * 100 - min(99, eingabe_zeit), "ok": stufen > 0, "text": f"{stufen} Stufen"}


def spiel_tap(b, p, rng):
    dauer = 10.0
    b.leeren()
    start = time.monotonic()
    ende = start + dauer
    zahl = 0
    rate = b.bot.uniform(5.5, 9.0) / b.skill if b.bot else 0
    naechster = start + 0.25
    while True:
        jetzt = time.monotonic()
        if jetzt >= ende:
            break
        if b.bot and jetzt >= naechster:
            b.druck(b.bot.choice(TASTEN))
            naechster += 1 / rate
        if b.warte(min(0.02, ende - jetzt)):
            zahl += 1
            b.ton(kurz(TAP_TOENE[min(len(TAP_TOENE) - 1, zahl // 7)], 0.025))
            b.status = f"{zahl} Taps"
        b.zeige(balken(min(N, zahl // 7)))
    b.ton(T_LOS)
    return {"wert": zahl, "ok": True, "text": f"{zahl} Taps ({zahl / dauer:.1f}/s)"}


def spiel_piep(b, p, rng):
    n = int(p["n"])
    start = time.monotonic()  # Zeit zaehlt ab Spielstart - gleich wie beim Handy-Spieler
    b.zeige([0] * N)
    b.status = "Zaehl die Pieps!"
    b.pause(0.6)
    for _ in range(n):
        b.ton(kurz(rng.choice(["C6", "E6", "G6", "A5"]), 0.09))
        b.pause(rng.uniform(0.22, 0.6))
    b.pause(0.4)
    b.leeren()
    b.status = "Rechts +1, Links -1, Mitte = fertig"
    if b.bot:
        antwort = n if b.bot.random() < 0.8 else max(1, n + b.bot.choice([-1, 1]))
        t = 0.3
        for _ in range(antwort):
            t += b.bot.uniform(0.18, 0.35) * b.skill
            b.bot_drueck("rechts", t)
        b.bot_drueck("mitte", t + 0.4)
    zahl = 0
    t0 = time.monotonic()
    ende = t0 + 15
    while True:
        rest = ende - time.monotonic()
        if rest <= 0:
            b.ton(T_FEHL)
            return {"wert": 99, "ok": False, "text": f"keine Antwort (es waren {n})"}
        e = b.warte(rest)
        if not e:
            continue
        if e[0] == "rechts":
            zahl = min(N, zahl + 1)
            b.ton(kurz("E6", 0.04))
        elif e[0] == "links":
            zahl = max(0, zahl - 1)
            b.ton(kurz("C5", 0.04))
        else:
            break
        b.zeige(balken(zahl))
    dt = time.monotonic() - start
    if zahl == n:
        b.ton(T_SUPER)
        blinke(b, balken(zahl), 3, 0.1)
        return {"wert": round(dt, 2), "ok": True, "text": f"richtig ({n}) in {dt:.1f} s"}
    b.ton(T_FEHL)
    blinke(b, [1] * N, 2, 0.15)
    return {"wert": 99, "ok": False, "text": f"{zahl} statt {n}"}


def spiel_binaer(b, p, rng):
    ziel = int(p["zahl"])  # steht gross am Monitor, 8 Bit auf LED 3..10
    bits = [0] * 8
    cursor = 7  # startet beim niederwertigsten Bit (ganz rechts)
    b.status = f"Stelle {ziel} binaer ein"
    b.leeren()
    t0 = time.monotonic()
    ende = t0 + p.get("dauer", 25) - 1
    if b.bot:  # Bot faehrt von rechts nach links und schaltet die noetigen Bits
        t, cur = 0.3, 7
        for idx in range(7, -1, -1):
            if (ziel >> (7 - idx)) & 1:
                for _ in range(cur - idx):
                    t += b.bot.uniform(0.15, 0.3) * b.skill
                    b.bot_drueck("links", t)
                cur = idx
                t += b.bot.uniform(0.2, 0.4) * b.skill
                b.bot_drueck("mitte", t)
    while True:
        wert = sum(bit << (7 - i) for i, bit in enumerate(bits))
        if wert == ziel:
            dt = time.monotonic() - t0
            b.ton(T_SUPER)
            blinke(b, [0, 0] + bits, 3, 0.1)
            return {"wert": round(dt, 2), "ok": True, "text": f"{ziel} = {ziel:08b} in {dt:.1f} s"}
        jetzt = time.monotonic()
        if jetzt > ende:
            b.ton(T_FEHL)
            return {"wert": 99, "ok": False, "text": f"{wert} statt {ziel}"}
        m = [0, 0] + bits
        if int(jetzt * 6) % 2:  # Cursor blinkt
            m[2 + cursor] = 1 - m[2 + cursor]
        b.zeige(m)
        e = b.warte(0.05)
        if e:
            if e[0] == "links":
                cursor = max(0, cursor - 1)
                b.ton(kurz("C6", 0.03))
            elif e[0] == "rechts":
                cursor = min(7, cursor + 1)
                b.ton(kurz("C6", 0.03))
            else:
                bits[cursor] ^= 1
                b.ton(kurz("G6" if bits[cursor] else "G5", 0.05))


# Spiel-Tabelle (der Host liest Name, Regeln, Wertung daraus). besser: "hoch" oder "tief".
# trost: Punkte fuer alle mit gueltigem Ergebnis ausserhalb der Top 3.
# handy: auch mit dem Handy spielbar (Lauflicht/Simon brauchen die echten LEDs -> nur ohne Handy-Spieler).
SPIELE = {
    "reaktion": {"handy": True, "name": "REAKTIONS-BLITZ", "fn": spiel_reaktion, "besser": "tief", "trost": 0, "dauer": 16,
                 "kurz": "Alle LEDs blitzen -> sofort druecken! 3 Versuche, Fruehstart = +1000 ms.",
                 "tasten": ("", "DRUECKEN", "")},
    "lauflicht": {"handy": False, "name": "LAUFLICHT-STOPP", "fn": spiel_lauflicht, "besser": "tief", "trost": 0, "dauer": 32,
                  "kurz": "Stopp das Lauflicht genau in der Mitte (LED 5/6). 3x, immer schneller.",
                  "tasten": ("", "STOPP", "")},
    "simon": {"handy": False, "name": "SIMON", "fn": spiel_simon, "besser": "hoch", "trost": 1, "dauer": 55,
              "kurz": "LED+Ton-Folge merken und nachdruecken. Jede Stufe wird laenger.",
              "tasten": ("LINKS", "MITTE", "RECHTS")},
    "tap": {"handy": True, "name": "TAP-MARATHON", "fn": spiel_tap, "besser": "hoch", "trost": 0, "dauer": 11,
            "kurz": "10 Sekunden lang so oft druecken wie moeglich!",
            "tasten": ("TAP", "TAP", "TAP")},
    "piep": {"handy": True, "name": "ZAEHL DIE PIEPS", "fn": spiel_piep, "besser": "tief", "trost": 1, "dauer": 26,
             "kurz": "Zaehl die Pieptoene! Dann Rechts +1 / Links -1, Mitte = fertig. Schnell + richtig gewinnt.",
             "tasten": ("-1", "FERTIG", "+1")},
    "binaer": {"handy": True, "name": "BINAER-BLITZ", "fn": spiel_binaer, "besser": "tief", "trost": 1, "dauer": 26,
               "kurz": "Stell die Zahl vom Monitor binaer auf LED 3-10 ein. Cursor blinkt.",
               "tasten": ("CURSOR <", "BIT 0/1", "CURSOR >")},
}


def countdown(b, start, score):
    """Bis zum gemeinsamen Start: Score zeigen, letzte 3 s piepen + LEDs von aussen nach innen."""
    b.leeren()
    letzte = None
    while True:
        rest = start - time.monotonic()
        if rest <= 0:
            break
        if rest <= 3:
            sek = math.ceil(rest)
            if sek != letzte:
                letzte = sek
                b.ton(T_ZAEHL)
            k = min(5, int((3 - rest) / 3 * 5) + 1)
            b.zeige([i < k or i >= N - k for i in range(N)])
        else:
            b.zeige(balken(score))
        b.pause(min(0.04, rest))
    b.zeige([0] * N)
    b.ton(T_LOS)
    b.leeren()


# ---------------------------------------------------------------- Verbindung zum Host


class HttpVerbindung:
    """Dasselbe Protokoll wie die Handy-Seite: POST /join, GET /state, POST /act."""

    def __init__(self, host, port=HOST_PORT):
        self.basis = f"http://{host}:{port}"

    def _anfrage(self, pfad, query=None, body=None):
        url = self.basis + pfad + ("?" + urllib.parse.urlencode(query) if query else "")
        daten = urllib.parse.urlencode(body).encode() if body is not None else None
        with urllib.request.urlopen(url, data=daten, timeout=3) as r:  # data -> POST
            return json.loads(r.read().decode("utf-8"))

    def join(self, name, art, kennung):
        return self._anfrage("/join", body={"name": name, "art": art, "kennung": kennung})

    def poll(self, sid):
        return self._anfrage("/state", {"id": sid})

    def ergebnis(self, sid, rid, res):
        return self._anfrage("/act", {"id": sid}, {"action": "answer", "value": res["wert"], "rid": rid,
                                                   "ok": int(bool(res["ok"])), "text": res["text"],
                                                   "client_ms": int(time.monotonic() * 1000)})


def finde_host(sekunden=3.0):
    """Lauscht auf den UDP-Ruf des Hosts. -> (ip, port) oder None."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        if hasattr(socket, "SO_REUSEPORT"):
            try:
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
            except OSError:
                pass
        s.bind(("", SUCH_PORT))
        s.settimeout(0.5)
        ende = time.monotonic() + sekunden
        while time.monotonic() < ende:
            try:
                daten, adr = s.recvfrom(64)
            except socket.timeout:
                continue
            teile = daten.decode("ascii", "replace").split()
            if len(teile) == 2 and teile[0] == "MEGA-PARTY" and teile[1].isdigit():
                return adr[0], int(teile[1])
    except OSError as e:
        print("UDP-Suche nicht moeglich:", e)
    finally:
        s.close()
    return None


class Browser:
    """Browser-Runden (NINJA/FLAPPY/AUTO): oeffnet das Spiel selbst im Vollbild, mit dem MEGA-Namen (?name=).
    Wird vom Client UND vom Host (Moderator spielt mit) benutzt. Pro Runde geht der Browser hoechstens
    einmal auf - wer ihn selbst zumacht, bekommt ihn nicht sofort wieder vor die Nase.
    Chromium: eigenes Profil -> eigener Prozess, den wir nach der Runde wieder schliessen koennen;
    Software-Rendering (--disable-gpu), weil Chromium am Pi-5-Desktop sonst flackert.
    MEGA_BROWSER="befehl args" ersetzt Chromium (die URL kommt als letztes Argument dazu)."""

    def __init__(self, host, log, port=WEB_PORT):
        self.host, self.port, self.log = host, port, log
        self.proc = None
        self.offen_fuer = None  # Runde, fuer die der Browser schon aufging
        self.eigener = os.environ.get("MEGA_BROWSER", "").strip()
        self.exe = shutil.which("chromium-browser") or shutil.which("chromium")
        self.profil = os.path.join(tempfile.gettempdir(), f"mega-party-browser-{os.getpid()}")

    def auf(self, name, runde):
        if runde == self.offen_fuer:
            return
        self.offen_fuer = runde
        url = f"http://{self.host}:{self.port}/?name={urllib.parse.quote(name)}"
        if self.eigener:
            befehl = shlex.split(self.eigener) + [url]
        elif self.exe and (os.environ.get("WAYLAND_DISPLAY") or os.environ.get("DISPLAY")):
            befehl = [self.exe, f"--user-data-dir={self.profil}", "--no-first-run", "--noerrdialogs",
                      "--disable-session-crashed-bubble", "--password-store=basic", "--disable-gpu",
                      "--autoplay-policy=no-user-gesture-required", "--start-fullscreen", f"--app={url}"]
        else:
            self.log(f"  >>> Browser-Runde! Oeffne im Browser: {url}")
            return
        try:
            self.proc = subprocess.Popen(befehl, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                         stderr=subprocess.DEVNULL)
            self.log("  >>> Browser-Runde: Spiel geht gleich von selbst auf (Name schon eingetragen).")
        except OSError as e:
            self.proc = None
            self.log(f"  Browser ging nicht auf ({e}) - selbst oeffnen: {url}")

    def zu(self):
        """Browser schliessen, ohne zu blockieren (Warten/Abschiessen laeuft nebenher)."""
        self.offen_fuer = None
        p, self.proc = self.proc, None
        if p and p.poll() is None:
            p.terminate()

            def warte():
                try:
                    p.wait(3)
                except subprocess.TimeoutExpired:
                    p.kill()
            threading.Thread(target=warte, daemon=True).start()

    def laeuft(self):
        return bool(self.proc and self.proc.poll() is None)


class Client:
    """Haelt die Verbindung zum Host, startet die Runden synchron und zeigt sonst den Score auf den LEDs."""

    def __init__(self, brett, verbindung, name, art="pi", kennung=None, moderator=None, log=True):
        self.b = brett
        self.v = verbindung
        self.name, self.art = name, art
        self.kennung = kennung or f"{socket.gethostname()}/{name}"
        self.moderator = moderator  # Host-Pi: Taster ausserhalb der Runden = Moderator-Steuerung
        self.log_an = log
        self.id = None
        self.d = {}
        self.score = 0
        self.verbunden = False
        self.fehler = 0
        self.zustand, self.seit = "", time.monotonic()
        self.spiel = None  # laufender Spiel-Thread
        self.spiel_rid = None
        self.erledigt = set()
        self.offen = None  # Ergebnis, das noch zum Host muss
        self.naechster_poll = 0.0
        self.naechstes_senden = 0.0
        host = getattr(verbindung, "basis", "").split("//")[-1].rsplit(":", 1)[0]
        self.browser = Browser(host, self.log) if host else None  # nur mit echter Netz-Verbindung zum Host

    def log(self, text):
        if self.log_an:
            print("\n" + text if self.b.ausgabe else text, flush=True)

    def lauf(self, stop=None):
        while not (stop and stop.is_set()):
            jetzt = time.monotonic()
            if jetzt >= self.naechster_poll:
                self._poll()
                self.naechster_poll = jetzt + (POLL if self.verbunden else 1.0)
            if self.offen and jetzt >= self.naechstes_senden:
                self._sende()
            if self.spiel is None:
                self._anzeige(jetzt)
                while not self.b.events.empty():  # Taster ausserhalb einer Runde
                    try:
                        k, _ = self.b.events.get_nowait()
                    except queue.Empty:
                        break
                    if self.moderator:
                        self.moderator(k)
                    else:
                        self.b.ton(T_KLICK)
            time.sleep(0.03)

    def _poll(self):
        try:
            if not self.id:
                r = self.v.join(self.name, self.art, self.kennung)
                if not r.get("id"):
                    raise RuntimeError(r.get("fehler", "Host nimmt keine Spieler"))
                self.id, self.name = r["id"], r["name"]
                self.b.ton(T_VERBUNDEN)
                self.log(f"Verbunden als '{self.name}' - LEDs zeigen ab jetzt deinen Score.")
            antwort = self.v.poll(self.id)
            if antwort.get("neu") or "phase" not in antwort:  # Host neu gestartet -> neu anmelden
                self.id = None
                return
            self.verbunden, self.fehler = True, 0
            d = dict(antwort.get("pi", {}), phase=antwort["phase"])
            self.d = d
            self.score = min(N, int(antwort.get("your_score", 0)))
            z = d["phase"]
            if z != self.zustand:
                self._neuer_zustand(z, d)
            r = d.get("runde")
            if self.browser:  # Browser-Runde = Ansage/Runde ohne "runde" fuer das Board
                if z in ("countdown", "round") and not r and antwort.get("round_name"):
                    self.browser.auf(self.name, antwort.get("round"))
                elif z not in ("countdown", "round"):
                    self.browser.zu()
            if r and z in ("countdown", "round") and r["rid"] not in self.erledigt and self.spiel is None:
                if r["start_in"] < -1.0:  # zu spaet dazugekommen -> naechste Runde
                    self.erledigt.add(r["rid"])
                else:
                    self.spiel_rid = r["rid"]
                    self.spiel = threading.Thread(target=self._spiele, args=(r,), daemon=True)
                    self.spiel.start()
            if self.spiel is not None and (not r or r["rid"] != self.spiel_rid or z not in ("countdown", "round")):
                self.b.abbruch.set()  # Moderator hat die Runde uebersprungen
        except Exception as e:
            self.fehler += 1
            if self.verbunden or self.fehler == 1:
                self.log(f"Keine Verbindung zum Host ({e}) - versuche es weiter...")
            self.verbunden = False

    def _neuer_zustand(self, z, d):
        self.zustand, self.seit = z, time.monotonic()
        if z == "result" and d.get("gewinn"):
            self.b.ton(FANFARE if d.get("platz") == 1 else lied(" ".join(["C6", "E6", "G6", "C7"][:d["gewinn"]]), 0.09))
            self.log(f"Platz {d.get('platz')}: +{d['gewinn']} Punkte -> Score {d.get('punkte')}")
        elif z == "done":
            if d.get("sieger"):
                self.b.ton(FANFARE)
                self.log("*** DU HAST GEWONNEN! ***")
            else:
                self.log(f"Spielende: {d.get('text', '')}")
        elif z == "lobby":
            self.log(d.get("text", "Lobby"))

    def _spiele(self, r):
        b, rid = self.b, r["rid"]
        try:
            start = time.monotonic() + r["start_in"]
            info = SPIELE[r["spiel"]]
            self.log(f"Runde {r['nr']}{' (FINALE x2)' if r.get('finale') else ''}: {info['name']} - {info['kurz']}")
            countdown(b, start, self.score)
            if r["spiel"] == "binaer":
                self.log(f"  >>> Stelle {r['param']['zahl']} binaer ein (links/rechts = Cursor, Mitte = Bit)")
            res = info["fn"](b, r.get("param", {}), random.Random(r["seed"]))
            res["text"] = str(res["text"])[:60]
            self.offen = (rid, res)
            b.status = res["text"]
            self.log(f"  Ergebnis: {res['text']}")
        except Abbruch:
            self.log("  Runde abgebrochen.")
        except Exception as e:  # Fehler im Spiel darf den Client nicht beenden
            self.log(f"  Spielfehler: {e}")
            self.offen = (rid, {"wert": 0, "ok": False, "text": "Fehler"})
        finally:
            b.abbruch.clear()
            self.erledigt.add(rid)
            self.spiel = None

    def _sende(self):
        rid, res = self.offen
        try:
            self.v.ergebnis(self.id, rid, res)
            self.offen = None
        except Exception:
            self.naechstes_senden = time.monotonic() + 0.5  # spaeter nochmal, Ergebnis geht nicht verloren

    def _anzeige(self, jetzt):
        b = self.b
        if not self.verbunden:
            an = int(jetzt * 2) % 2
            b.zeige([i == (0 if an else N - 1) for i in range(N)])
            return
        alter = jetzt - self.seit
        z, d = self.zustand, self.d
        m = balken(self.score)
        if z == "lobby":
            m[int(jetzt * 4) % N] = 1  # wanderndes Licht = verbunden, warte
        elif z == "result" and d.get("gewinn") and alter < 3:
            if int(jetzt * 8) % 2:  # die neuen Punkte blinken
                for i in range(max(0, self.score - d["gewinn"]), self.score):
                    m[i] = 0
        elif z == "done":
            if d.get("sieger"):
                i = int(jetzt * 12) % (2 * N - 2)
                m = [j == (i if i < N else 2 * N - 2 - i) for j in range(N)]
                if int(jetzt * 2) % 2:
                    m = [1 - x for x in m]
            elif int(jetzt * 1.5) % 2:
                m = [0] * N
        b.zeige(m)


def erreichbar(host, port):
    """Antwortet dort ein MEGA-PARTY-Host?"""
    try:
        with urllib.request.urlopen(f"http://{host}:{port}/state?id=probe", timeout=2):
            return True
    except urllib.error.HTTPError:
        return True  # Server antwortet (auch mit Fehlercode) -> Host lebt
    except (OSError, ValueError):
        return False


def frage_name():
    """Name im Terminal fragen (auch bei 'curl ... | python3', dann ueber /dev/tty), sonst Popup-Fenster."""
    try:
        with open("/dev/tty", "r+") as tty:
            tty.write("Wie heisst du? ")
            tty.flush()
            return tty.readline().strip()
    except OSError:
        pass
    if sys.stdin and sys.stdin.isatty():
        try:
            return input("Wie heisst du? ").strip()
        except EOFError:
            pass
    try:
        import tkinter
        from tkinter import simpledialog
        fenster = tkinter.Tk()
        fenster.withdraw()
        name = simpledialog.askstring("MEGA-PARTY", "Wie heisst du?") or ""
        fenster.destroy()
        return name.strip()
    except Exception:
        return ""


def main():
    ap = argparse.ArgumentParser(description="MEGA-PARTY Client fuer die HTL-Platine")
    ap.add_argument("--name", default=None)
    ap.add_argument("--host", default=None)
    ap.add_argument("--port", type=int, default=HOST_PORT)
    ap.add_argument("--sim", action="store_true", help="ohne Platine, Tasten a/s/d")
    ap.add_argument("--bot", action="store_true", help="spielt automatisch")
    ap.add_argument("--suche", action="store_true", help="erst per UDP suchen, --host nur als Ersatz")
    ap.add_argument("--leise", action="store_true", help="keine LED-Zeile im Terminal")
    a = ap.parse_args()
    roh = a.name if a.name is not None else frage_name()
    name = "".join(c for c in roh if c.isalnum() or c in " _-.")[:12] or socket.gethostname()[:12] or "Spieler"

    brett = Brett(sim=a.sim, bot=a.bot, tastatur=a.sim and not a.bot, ausgabe=a.sim and not a.leise)
    ziel = None
    if a.host and not a.suche:
        ziel, wie = (a.host, a.port), "aus --host"
    while ziel is None:
        for h in ([] if a.suche else STANDARD_HOSTS):  # die Adressen, die der Host beim Ausliefern eingetragen hat
            print(f"Probiere Host {h}:{a.port} ...", flush=True)
            if erreichbar(h, a.port):
                ziel, wie = (h, a.port), "fest eingetragen vom Host"
                break
        if ziel:
            break
        print("Suche Host im WLAN (UDP) ...", flush=True)
        brett.zeige([1] + [0] * (N - 2) + [1])
        gefunden = finde_host(3.0)
        if gefunden:
            ziel, wie = gefunden, "per UDP gefunden"
        elif a.host:
            ziel, wie = (a.host, a.port), "UDP nichts gehoert -> --host"
        a.suche = False  # naechster Durchgang: wieder die festen Adressen probieren
    print(f"Host {ziel[0]}:{ziel[1]} ({wie}). Spieler: {name}. Strg+C = Ende.", flush=True)
    client = Client(brett, HttpVerbindung(*ziel), name, "sim" if a.sim and not a.bot else ("bot" if a.bot else "pi"))
    try:
        client.lauf()
    except KeyboardInterrupt:
        pass
    finally:
        if client.browser:
            client.browser.zu()
        brett.schliessen()
        print("\nTschuess!")


if __name__ == "__main__":
    main()
