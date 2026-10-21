#!/usr/bin/env python3
"""SPIELER - das Programm fuer JEDEN Schueler-Pi (PiArena).

WAS MACHT DIE DATEI?
  Du spielst auf deiner EIGENEN Platine gegen alle anderen. Der Host (arena/host.py am Pi mit Monitor)
  startet die Minispiele bei allen gleichzeitig, sammelt die Ergebnisse und vergibt Punkte.
    - 3 Taster  = Eingabe (links / mitte / rechts)
    - Buzzer    = Rueckmeldung (Treffer, Fehler, Countdown, Sieg)
    - 10 LEDs   = DEIN PUNKTESTAND: so viele LEDs leuchten, so viele Punkte hast du. 10 LEDs = gewonnen!
      Waehrend einer Runde gehoeren die LEDs dem Spiel, danach zeigen sie wieder den Punktestand.
  Browser-Runden (NINJA/FLAPPY/AUTO): das Spiel geht von selbst im Browser auf (Name schon drin).

  Die Minispiele selbst stehen in minispiele.py (gleicher Ordner). Beim Download vom Host
  (curl .../j) setzt der Host minispiele.py hier ein -> es kommt EINE fertige Datei an.

LED-Signale ausserhalb der Runden:
  LED 1 und 10 blinken abwechselnd  -> suche Host / Verbindung weg (verbindet sich selbst neu)
  ein Licht wandert ueber den Score -> verbunden, warte auf den Start

WIE STARTEN?
  curl http://<HOST-IP>:8081/j | python3          (der Befehl steht gross am Monitor des Hosts)
  python3 arena/spieler.py --host <HOST-IP>       (aus dem Projektordner, z.B. nach eigenen Aenderungen)

Optionen:
  --name Max        Anzeigename am Monitor (sonst wird gefragt)
  --host <IP>       Host-IP direkt angeben (sonst eingetragene Adressen, dann Suche per UDP)
  --sim             ohne Platine (Laptop): Tasten a / s / d, LEDs im Terminal
  --bot             spielt selbst (zum Testen)
  Umgebungsvariable ARENA_BROWSER="firefox --kiosk"  -> anderer Browser fuer die Browser-Runden

AUFBAU: Einstellungen (Pins) -> Brett (Platine) -> Countdown -> Verbindung zum Host -> Browser -> Client -> main()
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

LED_PINS = [4, 17, 27, 22, 5, 6, 13, 19, 26, 21]  # GPIO-Nummern der 10 LEDs, links -> rechts
TASTER = {"links": 18, "mitte": 23, "rechts": 24}  # GPIO-Nummern der Taster (pull_up, gegen GND)
BUZZER_PIN = 25  # passiver Buzzer
HOST_PORT = 8081  # TCP: arena/host.py (Handy-Seite, /j, Spiel-API)
WEB_PORT = 8082  # TCP: arena/browserspiele.py (Browser-Runden)
SUCH_PORT = 8082  # UDP: der Host ruft jede Sekunde "PI-ARENA <port>" ins Netz
STANDARD_HOSTS = []  # traegt der Host beim Ausliefern (/j) ein: zuerst die Adresse aus dem curl-Befehl, dann alle anderen
POLL = 0.3  # Sekunden zwischen zwei Anfragen an den Host

# Die Minispiele (spiel_*, SPIELE, Toene, balken, N, TASTEN). Beim Download /j steht hier stattdessen minispiele.py.
from minispiele import *  # noqa: E402,F401,F403  BUNDLE-MARKE: diese Zeile ersetzt der Host durch minispiele.py

assert len(LED_PINS) == N, "LED_PINS und N (minispiele.py) passen nicht zusammen"


class Abbruch(Exception):
    """Runde wurde vom Host abgebrochen (Moderator hat uebersprungen)."""


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
            if len(teile) == 2 and teile[0] == "PI-ARENA" and teile[1].isdigit():
                return adr[0], int(teile[1])
    except OSError as e:
        print("UDP-Suche nicht moeglich:", e)
    finally:
        s.close()
    return None


class Browser:
    """Browser-Runden (NINJA/FLAPPY/AUTO): oeffnet das Spiel selbst im Vollbild, mit dem Arena-Namen (?name=).
    Wird vom Client UND vom Host (Moderator spielt mit) benutzt. Pro Runde geht der Browser hoechstens
    einmal auf - wer ihn selbst zumacht, bekommt ihn nicht sofort wieder vor die Nase.
    Chromium: eigenes Profil -> eigener Prozess, den wir nach der Runde wieder schliessen koennen;
    Software-Rendering (--disable-gpu), weil Chromium am Pi-5-Desktop sonst flackert.
    ARENA_BROWSER="befehl args" ersetzt Chromium (die URL kommt als letztes Argument dazu)."""

    def __init__(self, host, log, port=WEB_PORT):
        self.host, self.port, self.log = host, port, log
        self.proc = None
        self.offen_fuer = None  # Runde, fuer die der Browser schon aufging
        self.eigener = os.environ.get("ARENA_BROWSER", "").strip()
        self.exe = shutil.which("chromium-browser") or shutil.which("chromium")
        self.profil = os.path.join(tempfile.gettempdir(), f"pi-arena-browser-{os.getpid()}")

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
    """Antwortet dort ein PI-ARENA-Host?"""
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
        name = simpledialog.askstring("PI-ARENA", "Wie heisst du?") or ""
        fenster.destroy()
        return name.strip()
    except Exception:
        return ""


def main():
    ap = argparse.ArgumentParser(description="PiArena - Programm fuer jeden Schueler-Pi mit der Platine")
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
