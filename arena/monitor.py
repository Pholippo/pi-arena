"""MONITOR - das Bild am Monitor/Beamer des Hosts (PiArena) und der Host selbst (App).

WAS MACHT DIE DATEI?
  App = der Host: startet Webserver (8081) und Browser-Spiele (8082), die Platine des Moderators,
        die Demo-Bots und zeichnet 30x pro Sekunde den Monitor mit pygame.
  Bildschirme: Lobby (Beitritts-Befehl + QR-Code), Ansage, laufende Runde, Auswertung, Siegerehrung,
  dazu rechts unten "Live-GPIO": das Schaltbild der Host-Platine in Echtzeit.

WER BENUTZT SIE?  arena/host.py erzeugt die App und laesst sie laufen.

FARBE FUER DEIN SPIEL: in SPIEL_FARBE unten einen Eintrag "dein_spiel": (R, G, B) ergaenzen.
"""
import math
import os
import queue
import random
import re
import socket
import subprocess
import sys
import threading
import time
from urllib.parse import urlparse

os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
import pygame  # noqa: E402

import einstellungen as E  # noqa: E402
import minispiele  # noqa: E402
import spieler as schueler_pi  # noqa: E402
from ablauf import (DirektVerbindung, Show, info_von, ist_web, rotation, sauberer_name,  # noqa: E402
                    starte_webspiele, web_zuordnung)
from einstellungen import HOST_BROWSER_VORLAUF_S, MAX_RUNDEN, PORT, WEB_PORT, ZIEL_PUNKTE  # noqa: E402
from webserver import TV, leuchtfeuer, netz_adressen, spieler_programm, starte_web  # noqa: E402

HIER = os.path.dirname(os.path.abspath(__file__))
sys.path.append(os.path.join(os.path.dirname(HIER), "extras"))  # chiptune.py (HDMI-Sound), falls vorhanden

# ---------------------------------------------------------------- Farben
B, H = 1280, 720
WEISS, GRAU, DUNKEL = (240, 244, 255), (130, 130, 160), (60, 60, 85)
ROT, GRUEN, GELB, GOLD = (255, 60, 60), (60, 230, 120), (255, 220, 40), (255, 190, 40)
CYAN, PINK = (0, 229, 255), (255, 43, 214)
SPIEL_FARBE = {"reaktion": GELB, "lauflicht": CYAN, "simon": GRUEN, "tap": (255, 130, 40),
               "piep": PINK, "binaer": (170, 120, 255),
               "ninja": (255, 90, 60), "flappy": (255, 210, 63), "auto": (80, 200, 255),
               "morse": (255, 120, 200)}
ART_FARBE = {"pi": WEISS, "sim": WEISS, "web": (120, 200, 255), "bot": GRAU}
BOT_NAMEN = ["Bot Ohm", "Bot Volt", "Bot Ampere", "Bot Tesla", "Bot Watt", "Bot Hertz"]
MENU_LIED = minispiele.lied("C4 E4 G4 E4 A3 C4 E4 C4 F3 A3 C4 A3 G3 B3 D4 G4", 0.17)
T_ANSAGE = minispiele.lied("C5 E5 G5 C6 G5 C6:2", 0.08)
T_RUNDE = minispiele.lied("C6 E6 G6 C7:3", 0.06)


# ---------------------------------------------------------------- QR-Code (Baustein qrgen.py, zur Laufzeit geladen)


def qr_bild(text, groesse):
    """QR-Code als pygame-Surface (weiss mit 4 Modulen Rand). Fehlt qrgen.py -> Exception -> URL-Text."""
    import qrgen
    m = qrgen.qr_matrix(text)
    n = len(m) + 8
    px = max(2, groesse // n)
    s = pygame.Surface((n * px, n * px))
    s.fill((255, 255, 255))
    for r, zeile in enumerate(m):
        for c, an in enumerate(zeile):
            if an:
                s.fill((0, 0, 0), ((c + 4) * px, (r + 4) * px, px, px))
    return s


# ---------------------------------------------------------------- Grafik-Helfer

_FONTS, _TEXT, _GLOW = {}, {}, {}


def font(groesse, mono=False):
    k = (groesse, mono)
    if k not in _FONTS:
        _FONTS[k] = pygame.font.SysFont("dejavusansmono,liberationmono,consolas,couriernew", groesse, bold=True) if mono \
            else pygame.font.Font(None, groesse)
    return _FONTS[k]


def _render(txt, groesse, farbe, mono=False):
    k = (txt, groesse, farbe, mono)
    b = _TEXT.get(k)
    if b is None:
        if len(_TEXT) > 1500:
            _TEXT.clear()
        b = _TEXT[k] = font(groesse, mono).render(txt, True, farbe)
    return b


def text(s, txt, groesse, farbe, pos, anker="center", schatten=True, mono=False):
    txt = str(txt)
    bild = _render(txt, groesse, farbe, mono)
    rect = bild.get_rect(**{anker: (int(pos[0]), int(pos[1]))})
    if schatten:
        s.blit(_render(txt, groesse, (0, 0, 0), mono), rect.move(2, 2))
    s.blit(bild, rect)
    return rect


def umbruch(txt, groesse, breite):
    f, zeilen, zeile = font(groesse), [], ""
    for wort in txt.split():
        probe = (zeile + " " + wort).strip()
        if f.size(probe)[0] <= breite:
            zeile = probe
        else:
            zeilen.append(zeile)
            zeile = wort
    return zeilen + ([zeile] if zeile else [])


def glow(s, x, y, r, farbe, kern=True):
    r = max(2, int(r))
    g = _GLOW.get((r, farbe))
    if g is None:
        rand = r * 3
        g = pygame.Surface((rand * 2, rand * 2), pygame.SRCALPHA)
        for i in range(12):
            pygame.draw.circle(g, (*farbe, min(255, int(8 + i * i * 1.1))), (rand, rand), max(1, int(rand * (1 - i / 12))))
        _GLOW[(r, farbe)] = g
    s.blit(g, (int(x) - g.get_width() // 2, int(y) - g.get_height() // 2))
    if kern:
        pygame.draw.circle(s, farbe, (int(x), int(y)), r)
        pygame.draw.circle(s, (255, 255, 255), (int(x), int(y)), max(1, r // 2))


def mische(a, b, t):
    t = max(0.0, min(1.0, t))
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


# ---------------------------------------------------------------- Monitor + Spieler-Verwaltung


class App:
    """Der Host: Monitor (pygame), Webserver 8081, browserspiele.py-Unterprozess, Moderator-Board, Demo-Bots."""

    def __init__(self, sim=False, fenster=False, name=None, spielt=True, schnell=False, max_runden=MAX_RUNDEN,
                 ziel=ZIEL_PUNKTE, headless=False, web_starten=True):
        name = sauberer_name(name or socket.gethostname())
        self.show = Show(schnell, max_runden, ziel)
        self.adressen = netz_adressen()  # [(WLAN/KABEL/NETZ, ip, broadcast)]
        self.ips = [ip for _, ip, _ in self.adressen]
        self.web = starte_web(self)  # zuerst: Port belegt -> PortBelegt, bevor irgendein Fenster aufgeht
        self.browserspiele = starte_webspiele() if web_starten and E.WEB_BASIS else None
        pygame.init()
        self.screen = self._bildschirm(fenster or headless)
        pygame.display.set_caption("PI-ARENA")
        pygame.mouse.set_visible(False)
        self.hintergrund = pygame.Surface((B, H))
        for y in range(H):
            self.hintergrund.fill(mische((8, 4, 24), (24, 6, 36), y / H), (0, y, B, 1))
        self.url = f"http://{self.ips[0]}:{PORT}/"
        self.befehle = [(art, f"curl http://{ip}:{PORT}/j | python3") for art, ip, _ in self.adressen]
        try:
            self.qr = qr_bild(self.url, 250)
        except Exception as e:  # Fallback: nur die URL gross
            print("QR-Code nicht moeglich (qrgen.py?) -> URL als Text:", e)
            self.qr = None
        self.ereignisse = queue.Queue()
        self.show.ereignis = self.ereignisse.put
        self.show.bots_umschalten = self.bots_umschalten
        self.brett = schueler_pi.Brett(sim=sim)  # Platine des Moderators am Host
        self.bots = []
        self.partikel = []
        self.zeit = 0.0
        self.laeuft = True
        self.chip = None
        try:
            import chiptune  # HDMI-Sound fuer Jingles (braucht numpy), sonst stumm
            c = chiptune.Chiptune()
            self.chip = c if c.ok else None
        except Exception as e:
            print("HDMI-Sound aus:", e)
        self.stop = threading.Event()
        self.web_urls = [f"http://{ip}:{WEB_PORT}" for ip in self.ips]
        self.show.web_adressen = list(self.web_urls)
        self.web_qr = None
        try:
            self.web_qr = qr_bild(self.web_urls[0], 230)
        except Exception as e:
            print("QR fuer Browser-Spiel nicht moeglich:", e)
        threading.Thread(target=self.show.web_poller, args=(self.stop,), daemon=True).start()
        threading.Thread(target=leuchtfeuer, args=([b for _, _, b in self.adressen], self.stop), daemon=True).start()
        self.spieler_client = None
        self.host_browser = None
        if spielt:  # der Moderator spielt selbst mit - seine Taster sind ausserhalb der Board-Runden Moderator
            self.spieler_client = schueler_pi.Client(self.brett, DirektVerbindung(self.show), name, "pi",
                                            kennung="host/" + name, moderator=self.show.moderator)
            threading.Thread(target=self.spieler_client.lauf, args=(self.stop,), daemon=True).start()
            if E.WEB_BASIS:  # Browser-Runden: das Spiel geht auch am Host auf (wie bei den Clients)
                ziel = urlparse(E.WEB_BASIS)
                self.host_browser = schueler_pi.Browser(ziel.hostname, print, ziel.port or WEB_PORT)
        self._musik(MENU_LIED)
        print(f"PI-ARENA Host laeuft. Moderator: {name if spielt else '(Zuschauer)'}. Handy: {self.url}")
        for art, befehl in self.befehle:
            print(f"  Schueler-Pi ({art}):  {befehl}")

    def _bildschirm(self, fenster):
        try:
            if fenster:
                return pygame.display.set_mode((B, H))
            return pygame.display.set_mode((B, H), pygame.FULLSCREEN | pygame.SCALED)
        except pygame.error as e:  # kein Monitor -> Host laeuft trotzdem (Clients/Handys gehen weiter)
            print("Kein Monitor nutzbar, laufe ohne Bild:", e)
            pygame.display.quit()
            os.environ["SDL_VIDEODRIVER"] = "dummy"
            pygame.display.init()
            return pygame.display.set_mode((B, H))

    def _musik(self, lied):
        if self.chip:
            self.chip.musik(lied) if lied else self.chip.stop()

    def _jingle(self, lied):
        if self.chip:
            self.chip.effekt(lied, "pulse", 0.4)

    def client_hosts(self, adresse=""):
        """Host-Adressen fuer den ausgelieferten Client: zuerst die aus dem curl-Befehl, dann alle anderen."""
        erste = [adresse] if re.fullmatch(r"[A-Za-z0-9.-]{1,64}", adresse or "") else []
        return list(dict.fromkeys(erste + self.ips))[:6]

    def client_code(self, adresse=""):
        """Programm fuer /j (spieler.py + minispiele.py als eine Datei) mit den Host-Adressen."""
        return spieler_programm(self.client_hosts(adresse))

    # ---- Demo-Bots (LINKS in der Lobby)
    def bots_umschalten(self):
        if self.bots:
            for client, stop in self.bots:
                stop.set()
                with self.show.lock:
                    self.show.spieler.pop(client.id, None)
            self.bots = []
        else:
            self.bots_an(4)

    def bots_an(self, anzahl):
        for name in BOT_NAMEN[:anzahl]:
            stop = threading.Event()
            c = schueler_pi.Client(schueler_pi.Brett(sim=True, bot=True), DirektVerbindung(self.show), name, "bot",
                          kennung="bot/" + name, log=False)
            self.bots.append((c, stop))
            threading.Thread(target=c.lauf, args=(stop,), daemon=True).start()

    # ---- Hauptschleife
    def schritt(self, dt, zeichnen=True):
        self.zeit += dt
        for e in pygame.event.get():
            if e.type == pygame.QUIT:
                self.laeuft = False
            elif e.type == pygame.KEYDOWN:
                k = e.key
                if k == pygame.K_ESCAPE:
                    if self.show.zustand == "lobby":
                        self.laeuft = False
                    else:
                        self.show.reset()
                elif k in (pygame.K_SPACE, pygame.K_RETURN):
                    self.show.moderator("mitte")
                elif k == pygame.K_LEFT:
                    self.show.moderator("links")
                elif k in (pygame.K_RIGHT, pygame.K_n):
                    self.show.moderator("rechts")
                elif k in (pygame.K_a, pygame.K_s, pygame.K_d):  # eigene Taster per Tastatur (Laptop/Test)
                    self.brett.druck({pygame.K_a: "links", pygame.K_s: "mitte", pygame.K_d: "rechts"}[k])
        if self.spieler_client is None:  # Zuschauer-Modus: Taster sind nur Moderator
            while not self.brett.events.empty():
                self.show.moderator(self.brett.events.get_nowait()[0])
        self.show.update()
        self._host_browser()
        while not self.ereignisse.empty():
            self._ereignis(self.ereignisse.get_nowait())
        for t in self.partikel:
            t[0] += t[2] * dt
            t[1] += t[3] * dt
            t[3] += 400 * dt
            t[4] -= dt
        self.partikel = [t for t in self.partikel if t[4] > 0]
        if self.show.zustand == "sieger" and random.random() < dt * 5:
            self.funken(random.randint(80, 800), random.randint(120, 380), random.choice([GOLD, CYAN, PINK, WEISS]), 40)
        if zeichnen:
            self.zeichne()

    def _host_browser(self):
        """Moderator spielt Browser-Runden mit: kurz vor Spielstart geht das Spiel auf diesem Bildschirm auf
        (mit seinem Namen), nach der Runde/beim Ueberspringen wieder zu -> zurueck auf den Party-Monitor."""
        if not self.host_browser:
            return
        sh = self.show
        with sh.lock:
            r, z = sh.runde, sh.zustand
            name = self.spieler_client.name if self.spieler_client.id else None
            dran = ist_web(r) and name and (z == "laeuft" or (z == "ansage" and
                                                               time.monotonic() >= r["start"] - HOST_BROWSER_VORLAUF_S))
        if dran:
            self.host_browser.auf(name, r["rid"])
        elif self.host_browser.offen_fuer is not None:
            self.host_browser.zu()

    def _ereignis(self, z):
        if z == "lobby":
            self._musik(MENU_LIED)
        elif z == "ansage":
            self._musik(None)
            self._jingle(T_ANSAGE)
        elif z == "auswertung":
            self._jingle(T_RUNDE)
            self.funken(440, 300, GOLD, 70)
        elif z == "sieger":
            self._jingle(minispiele.FANFARE)

    def funken(self, x, y, farbe, anzahl):
        for _ in range(anzahl):
            w, v = random.uniform(0, math.tau), random.uniform(80, 420)
            leben = random.uniform(0.4, 1.0)
            self.partikel.append([x, y, math.cos(w) * v, math.sin(w) * v - 100, leben, leben, farbe])
        del self.partikel[:-500]

    def lauf(self):
        uhr = pygame.time.Clock()
        while self.laeuft:
            self.schritt(min(0.05, uhr.tick(30) / 1000.0))

    def beenden(self):
        self.stop.set()
        for _, stop in self.bots:
            stop.set()
        if self.host_browser:
            self.host_browser.zu()
        time.sleep(0.1)
        self.brett.schliessen()
        if self.web:
            self.web.shutdown()
            self.web.server_close()
        if self.browserspiele and self.browserspiele.poll() is None:  # selbst gestartetes browserspiele.py mit beenden
            self.browserspiele.terminate()
            try:
                self.browserspiele.wait(3)
            except subprocess.TimeoutExpired:
                self.browserspiele.kill()
        pygame.quit()

    # ---- Zeichnen
    def zeichne(self):
        s = self.screen
        s.blit(self.hintergrund, (0, 0))
        sh = self.show
        with sh.lock:  # Momentaufnahme, damit kein anderer Thread mitten im Zeichnen etwas aendert
            z = sh.zustand
            rang = sh.rangfolge()
            r = dict(sh.runde) if sh.runde else None
            fertig = [sh.spieler[i].name for i in sh.ergebnisse if i in sh.spieler]
            teilnehmer = len(sh.teilnehmer)
            rangliste = list(sh.rangliste)
            sieger = sh.spieler.get(sh.sieger_id)
            web_stand = dict(sh.web_stand) if sh.web_stand else {}
            zuordnung = {}
            if ist_web(r) and z == "laeuft":
                zuordnung = {id(e): sh.spieler[sid].name for sid, e in web_zuordnung(web_stand.get("spieler", []), sh.spieler)}
            hinweis = sh.web_hinweis if time.monotonic() - sh.web_hinweis_t < 20 else ""
        self._kopf(s, z, len(rang))
        if hinweis:
            text(s, hinweis, 24, ROT, (440, 70))
        if z == "lobby":
            self._lobby(s, len(rang))
        elif z == "ansage" and ist_web(r):
            self._web_ansage(s, r)
        elif z == "laeuft" and ist_web(r):
            self._web_laeuft(s, r, web_stand, zuordnung)
        elif z == "ansage":
            self._ansage(s, r)
        elif z == "laeuft":
            self._laeuft(s, r, fertig, teilnehmer)
        elif z == "auswertung":
            self._auswertung(s, r, rangliste)
        else:
            self._sieger(s, rang, sieger)
        self._rangliste(s, rang, z)
        self._gpio(s)
        for x, y, vx, vy, leben, voll, farbe in self.partikel:
            pygame.draw.circle(s, mische((0, 0, 0), farbe, leben / voll + 0.3), (int(x), int(y)),
                               max(1, int(5 * leben / voll)))
        text(s, "Taster: MITTE Start/Weiter  -  RECHTS Runde ueberspringen  -  LINKS Demo-Bots"
             "      Tastatur: Leertaste, Pfeile, N, ESC", 19, GRAU, (16, H - 6), "bottomleft", False)
        pygame.display.flip()
        jetzt = time.monotonic()
        if jetzt - TV["t"] > 0.4 and jetzt - TV["gefragt"] < 5:  # Monitorbild fuer /live, nur wenn jemand zuschaut
            TV["t"] = jetzt
            try:
                import io
                puffer = io.BytesIO()
                pygame.image.save(s, puffer, "tv.jpg")
                TV["jpg"] = puffer.getvalue()
            except Exception as e:  # Bild ist nur Zusatz, das Spiel laeuft weiter
                if not TV.get("fehler"):
                    print("TV-Bild aus:", e)
                TV["fehler"] = True

    def _kopf(self, s, z, anzahl):
        puls = 0.5 + 0.5 * math.sin(self.zeit * 2.5)
        text(s, "PI-ARENA", 58, mische(CYAN, PINK, puls), (20, 34), "midleft")
        sh = self.show
        mitte = {"lobby": "LOBBY", "sieger": "SIEGEREHRUNG"}.get(z, f"RUNDE {sh.nr} / {sh.max_runden}")
        text(s, mitte, 36, WEISS, (560, 34))
        text(s, f"{anzahl} Spieler", 32, GRAU, (B - 16, 34), "midright")

    def _lobby(self, s, anzahl):
        text(s, "MIT DEINEM PI - EIN BEFEHL IM TERMINAL:", 34, WEISS, (24, 88), "midleft")
        befehle = self.befehle[:3]  # mehr passt nicht auf den Monitor (alle stehen im Terminal)
        zeile = 80 if len(befehle) <= 2 else 64
        for i, (netz, befehl) in enumerate(befehle):  # riesig, damit niemand ':' und '.' verwechselt
            box = pygame.Rect(20, 108 + i * zeile, 840, zeile - 10)
            pygame.draw.rect(s, (10, 14, 12), box, border_radius=12)
            pygame.draw.rect(s, GRUEN, box, 3, border_radius=12)
            text(s, netz, 24, GRAU, (box.x + 14, box.centery), "midleft", False)
            groesse = 46 if zeile == 80 else 40
            while groesse > 16 and font(groesse, True).size(befehl)[0] > 720:
                groesse -= 1
            text(s, befehl, groesse, (120, 255, 150), (box.x + 110, box.centery), "midleft", False, mono=True)
        y0 = 108 + len(befehle) * zeile + 12
        if self.qr:
            s.blit(self.qr, (20, y0))
            text(s, "Ohne Pi: Handy scannen", 24, WEISS, (20 + self.qr.get_width() // 2, y0 + self.qr.get_height() + 16))
            x = 40 + self.qr.get_width()
        else:  # qrgen.py fehlt -> URL riesig
            text(s, "Ohne Pi: Handy-Browser", 34, WEISS, (24, y0 + 30), "midleft")
            text(s, self.url, 54, GELB, (24, y0 + 90), "midleft")
            x = 24
            y0 += 130
        if self.qr:
            text(s, "Handy: " + self.url, 30, GELB, (x, y0 + 16), "midleft")
        regeln = ["Deine 10 LEDs = dein Score.", "Alle spielen gleichzeitig am eigenen Board.",
                  "Platz 1/2/3 = 3/2/1 Punkte, Finale doppelt.", "Wer zuerst 10 LEDs hat, gewinnt!"]
        for i, zeile in enumerate(regeln):
            text(s, zeile, 26, WEISS, (x, y0 + 56 + i * 30), "midleft")
        for i, key in enumerate(rotation()):
            r = pygame.Rect(x + (i % 3) * 172, y0 + 180 + (i // 3) * 40, 164, 34)
            farbe = SPIEL_FARBE.get(key, WEISS)
            pygame.draw.rect(s, mische((15, 10, 30), farbe, 0.25), r, border_radius=10)
            pygame.draw.rect(s, farbe, r, 2, border_radius=10)
            text(s, info_von(key)["name"], 19, farbe, r.center, schatten=False)
        puls = 1 + 0.05 * math.sin(self.zeit * 5)
        mitte = (x + 860) // 2
        if anzahl:
            text(s, f"{anzahl} verbunden - MITTE startet!", int(34 * puls), GELB, (mitte, 668))
        else:
            text(s, "Warte auf Spieler ... (LINKS = Demo-Bots)", 30, GELB, (mitte, 668))

    def _web_ansage(self, s, r):
        info, farbe = info_von(r["spiel"]), SPIEL_FARBE.get(r["spiel"], WEISS)
        rest = r["start"] - time.monotonic()
        if r["finale"]:
            text(s, "FINALE - DOPPELTE PUNKTE!", 40, GOLD, (440, 100))
        text(s, f"{info['name']} im Browser!", 74, farbe, (440, 150))
        y = 205
        for url in self.web_urls[:2]:
            groesse = 64
            while groesse > 20 and font(groesse, True).size(url)[0] > 820:
                groesse -= 2
            text(s, url, groesse, GELB, (440, y), mono=True)
            y += groesse + 8
        if self.web_qr:
            q = pygame.transform.smoothscale(self.web_qr, (210, 210)) if self.web_qr.get_width() > 210 else self.web_qr
            s.blit(q, (40, y + 4))
            tx = 40 + q.get_width() + 24
        else:
            tx = 60
        f = 2 if r["finale"] else 1
        zeilen = ["Pis: das Spiel geht von selbst auf.", "Laptop/Handy: Adresse oeffnen und den",
                  "Arena-Namen eingeben (wie rechts in der Rangliste)!",
                  f"Spielzeit {r['dauer']} s. Platz 1/2/3 = {3 * f}/{2 * f}/{f} Punkte"]
        for i, zeile in enumerate(zeilen):
            text(s, zeile, 30, WEISS if i < 3 else GOLD, (tx, y + 30 + i * 38), "midleft")
        if rest <= 5.2:
            text(s, str(max(1, math.ceil(rest))), 120, GELB, (440, 630))
        else:
            text(s, f"Start in {math.ceil(rest)} s", 40, GRAU, (440, 640))

    def _web_laeuft(self, s, r, st, zuordnung):
        info, farbe = info_von(r["spiel"]), SPIEL_FARBE.get(r["spiel"], WEISS)
        rest = st.get("rest", 0) if st.get("phase") in ("countdown", "spiel") else max(0, r["start"] + r["dauer"] - time.monotonic())
        text(s, info["name"], 60, farbe, (440, 104))
        anteil = max(0.0, min(1.0, rest / max(1, r["dauer"])))
        pygame.draw.rect(s, DUNKEL, (60, 140, 760, 14), border_radius=7)
        pygame.draw.rect(s, mische(ROT, GRUEN, anteil), (60, 140, int(760 * anteil), 14), border_radius=7)
        phase = {"countdown": "GLEICH GEHT'S LOS", "spiel": "LAEUFT", "ende": "FERTIG", "lobby": "warte ..."}.get(st.get("phase"), "Verbinde ...")
        text(s, f"{phase}   {math.ceil(rest)} s", 40, WEISS, (440, 186))
        text(s, self.web_urls[0] if self.web_urls else "", 30, GELB, (440, 226), mono=True)
        liste = st.get("spieler", [])
        for i, e in enumerate(liste[:12]):
            y = 270 + i * 34
            arena_name = zuordnung.get(id(e))
            wert = f"Ziel {e['ziel']:.1f} s" if e.get("ziel") is not None else f"{e.get('best', 0)} m"
            text(s, f"{i + 1}.", 28, GRAU, (110, y), "midright")
            text(s, str(e.get("name", ""))[:14], 28, WEISS if arena_name else GRAU, (125, y), "midleft")
            text(s, f"= {arena_name}" if arena_name else "(kein Arena-Name)", 22, GRUEN if arena_name else DUNKEL, (390, y), "midleft")
            text(s, wert, 28, GOLD if e.get("ziel") is not None else WEISS, (820, y), "midright")
        if not liste:
            text(s, "Noch niemand im Browser-Spiel", 36, GRAU, (440, 400))

    def _ansage(self, s, r):
        info = minispiele.SPIELE[r["spiel"]]
        farbe = SPIEL_FARBE[r["spiel"]]
        rest = r["start"] - time.monotonic()
        if r["finale"]:
            glow(s, 440, 112, 40, GOLD, kern=False)
            text(s, "FINALE - DOPPELTE PUNKTE!", 46, GOLD, (440, 112))
        text(s, info["name"], 100, farbe, (440, 190))
        for i, zeile in enumerate(umbruch(info["kurz"], 32, 780)):
            text(s, zeile, 32, WEISS, (440, 262 + i * 34))
        for i, lbl in enumerate(info["tasten"]):  # die 3 Taster mit ihrer Bedeutung
            x = 260 + i * 180
            aktiv = bool(lbl)
            pygame.draw.circle(s, (40, 40, 55), (x, 410), 38)
            pygame.draw.circle(s, farbe if aktiv else DUNKEL, (x, 410), 28)
            text(s, ("LINKS", "MITTE", "RECHTS")[i], 20, GRAU, (x, 462))
            text(s, lbl or "-", 24, farbe if aktiv else DUNKEL, (x, 488))
        f = 2 if r["finale"] else 1
        pkt = f"Platz 1: {3 * f}  -  Platz 2: {2 * f}  -  Platz 3: {f}"
        if info["trost"]:
            pkt += f"  -  alle anderen mit Erfolg: {info['trost'] * f}"
        text(s, pkt, 28, GOLD, (440, 535))
        if rest <= 3.2:
            text(s, str(max(1, math.ceil(rest))), 140, GELB, (440, 625))
        else:
            text(s, f"Start in {math.ceil(rest)} s - Finger auf die Taster!", 34, GRAU, (440, 620))

    def _laeuft(self, s, r, fertig, teilnehmer):
        key, info = r["spiel"], minispiele.SPIELE[r["spiel"]]
        farbe = SPIEL_FARBE[key]
        vergangen = time.monotonic() - r["start"]
        text(s, info["name"], 64, farbe, (440, 100))
        pygame.draw.rect(s, DUNKEL, (60, 138, 760, 14), border_radius=7)
        anteil = max(0.0, 1 - vergangen / r["dauer"])
        pygame.draw.rect(s, mische(ROT, GRUEN, anteil), (60, 138, int(760 * anteil), 14), border_radius=7)
        puls = 0.5 + 0.5 * math.sin(self.zeit * 8)
        if key == "binaer":
            zahl = r["param"]["zahl"]
            text(s, "STELLT DIESE ZAHL BINAER EIN:", 34, WEISS, (440, 200))
            glow(s, 440, 320, 60, (90, 60, 160), kern=False)
            text(s, zahl, 200, GELB, (440, 320))
            for i, w in enumerate((128, 64, 32, 16, 8, 4, 2, 1)):
                text(s, w, 26, GRAU, (205 + i * 67, 440))
                text(s, f"LED{i + 3}", 16, DUNKEL, (205 + i * 67, 462), schatten=False)
        elif key == "piep":
            text(s, "ZAEHLT DIE PIEPS!", 80, PINK, (440, 250))
            if self.brett.f_jetzt:  # Buzzer am Host piept gerade -> Schallwellen
                for i in range(3):
                    pygame.draw.circle(s, PINK, (440, 380), 30 + i * 28, 3)
            pygame.draw.circle(s, WEISS, (440, 380), 22)
            text(s, "Antwort: RECHTS +1, LINKS -1, MITTE fertig", 28, GRAU, (440, 470))
        elif key == "reaktion":
            text(s, "AUGEN AUF EURE LEDs!", 76, mische(GELB, WEISS, puls), (440, 280))
            text(s, "3 Blitze - wer zu frueh drueckt, kassiert +1000 ms", 30, GRAU, (440, 380))
        elif key == "tap":
            text(s, "TAP! TAP! TAP!", int(110 + 20 * puls), (255, 130, 40), (440, 300))
        elif key == "lauflicht":
            text(s, "Stoppt in der Mitte!", 60, CYAN, (440, 230))
            for i in range(minispiele.N):
                x = 215 + i * 50
                ziel = i in (4, 5)
                pygame.draw.circle(s, GOLD if ziel else DUNKEL, (x, 340), 18 if ziel else 14)
            text(s, "ZIEL", 26, GOLD, (440, 385))
        elif key == "simon":
            text(s, "Merken ... und nachdruecken!", 58, GRUEN, (440, 230))
            for i, f in enumerate((ROT, GELB, GRUEN)):
                pygame.draw.circle(s, mische((20, 20, 30), f, 0.6 + 0.4 * puls), (290 + i * 150, 360), 50)
        text(s, f"Fertig: {len(fertig)} / {teilnehmer}", 36, WEISS, (440, 520))
        x, y = 40, 560
        for name in fertig[-24:]:
            w = font(22).size(name)[0] + 22
            if x + w > 850:
                x, y = 40, y + 32
            pygame.draw.rect(s, (30, 70, 45), (x, y, w, 26), border_radius=13)
            text(s, name, 22, WEISS, (x + w // 2, y + 13), schatten=False)
            x += w + 8

    def _auswertung(self, s, r, rangliste):
        if self.show.uebersprungen:
            text(s, "RUNDE UEBERSPRUNGEN", 70, GRAU, (440, 300))
            return
        info = info_von(r["spiel"])
        text(s, f"ERGEBNIS: {info['name']}", 50, SPIEL_FARBE.get(r["spiel"], WEISS), (440, 95))
        podest = [(440, 170, 0), (260, 125, 1), (620, 90, 2)]
        for x, hoehe, i in podest:
            if i >= len(rangliste) or rangliste[i]["platz"] is None:
                continue
            e = rangliste[i]
            rect = pygame.Rect(x - 80, 420 - hoehe, 160, hoehe)
            farbe = (GOLD, (200, 200, 215), (205, 127, 50))[i]
            pygame.draw.rect(s, mische((20, 20, 30), farbe, 0.5), rect, border_radius=8)
            pygame.draw.rect(s, farbe, rect, 3, border_radius=8)
            text(s, f"+{e['pkt']}", 54, WEISS, (x, rect.centery))
            text(s, e["name"], 32, farbe, (x, rect.top - 44))
            text(s, e["text"], 19, GRAU, (x, rect.top - 18))
        for j, e in enumerate(rangliste[3:10]):
            y = 450 + j * 29
            platz = f"{e['platz']}." if e["platz"] else "-"
            text(s, platz, 24, GRAU, (70, y), "midleft")
            text(s, e["name"], 24, ART_FARBE.get(e["art"], WEISS), (115, y), "midleft")
            text(s, e["text"], 22, GRAU, (330, y), "midleft")
            text(s, f"+{e['pkt']}" if e["pkt"] else "", 24, GRUEN, (840, y), "midright")
        if not rangliste:
            text(s, "Niemand hat ein Ergebnis abgegeben", 40, GRAU, (440, 300))
        rest = self.show.AUSWERTUNG - (time.monotonic() - self.show.seit)
        text(s, f"weiter in {max(0, math.ceil(rest))} s  (MITTE = sofort)", 24, GRAU, (440, 670))

    def _sieger(self, s, rang, sieger):
        if sieger:
            puls = 1 + 0.06 * math.sin(self.zeit * 7)
            text(s, f"{sieger.name} GEWINNT!", int(92 * puls), GOLD, (440, 150))
            text(s, f"mit {sieger.punkte} Punkten", 40, WEISS, (440, 220))
        for x, hoehe, i in ((440, 200, 0), (240, 150, 1), (640, 110, 2)):
            if i >= len(rang):
                continue
            sp = rang[i]
            rect = pygame.Rect(x - 90, 600 - hoehe, 180, hoehe)
            farbe = (GOLD, (200, 200, 215), (205, 127, 50))[i]
            pygame.draw.rect(s, mische((20, 20, 30), farbe, 0.5), rect, border_radius=8)
            pygame.draw.rect(s, farbe, rect, 3, border_radius=8)
            text(s, str(i + 1), 80, WEISS, rect.center)
            text(s, sp.name, 34, farbe, (x, rect.top - 40))
            text(s, f"{sp.punkte} Punkte", 24, GRAU, (x, rect.top - 14))
        text(s, "MITTE = neues Spiel (Spieler bleiben verbunden)", 26, GRAU, (440, 650))

    def _rangliste(self, s, rang, z):
        x0 = 878
        pygame.draw.rect(s, (14, 10, 30), (x0, 66, 394, 432), border_radius=12)
        text(s, "RANGLISTE  (LEDs = Score)", 26, WEISS, (x0 + 12, 84), "midleft")
        for i, sp in enumerate(rang[:13]):
            y = 112 + i * 29
            aktiv = sp.aktiv()
            farbe = ART_FARBE.get(sp.art, WEISS) if aktiv else DUNKEL
            text(s, f"{i + 1}.", 22, GRAU, (x0 + 30, y), "midright", False)
            name = sp.name if len(sp.name) <= 10 else sp.name[:9] + "."
            text(s, name, 24, farbe, (x0 + 36, y), "midleft", False)
            for j in range(minispiele.N):  # Mini-Platine: so leuchtet es gerade auf dem Board des Spielers
                lx = x0 + 168 + j * 13
                if j < min(10, sp.punkte):
                    pygame.draw.circle(s, (255, 60, 60), (lx, y), 5)
                else:
                    pygame.draw.circle(s, (60, 20, 25), (lx, y), 5)
            if z in ("auswertung", "sieger") and sp.gewinn:
                text(s, f"+{sp.gewinn}", 22, GRUEN, (x0 + 340, y), "midright", False)
            text(s, sp.punkte, 26, WEISS, (x0 + 384, y), "midright", False)
        if len(rang) > 13:
            text(s, f"... und {len(rang) - 13} weitere", 20, GRAU, (x0 + 197, 487))

    def _gpio(self, s):
        """Live-Schaltbild der Host-Platine: echter Zustand von LEDs, Tastern und Buzzer."""
        b = self.brett
        x0, y0 = 878, 504
        pygame.draw.rect(s, (8, 22, 14), (x0, y0, 394, 196), border_radius=12)
        pygame.draw.rect(s, (40, 110, 70), (x0, y0, 394, 196), 2, border_radius=12)
        text(s, "LIVE-GPIO  (Host-Platine)", 22, (120, 230, 160), (x0 + 12, y0 + 14), "midleft", False)
        gnd = y0 + 104
        pygame.draw.line(s, GRAU, (x0 + 14, gnd), (x0 + 370, gnd), 2)
        text(s, "GND", 16, GRAU, (x0 + 374, gnd), "midleft", False)
        for i, pin in enumerate(schueler_pi.LED_PINS):  # GPIO -> Widerstand -> LED -> GND
            x = x0 + 26 + i * 35
            an = b.zustand[i]
            text(s, pin, 17, WEISS if an else GRAU, (x, y0 + 34), schatten=False)
            pygame.draw.line(s, GRAU, (x, y0 + 42), (x, y0 + 50), 2)
            pygame.draw.rect(s, (200, 170, 110), (x - 4, y0 + 50, 8, 14), 1)
            pygame.draw.line(s, GRAU, (x, y0 + 64), (x, y0 + 72), 2)
            dreieck = [(x - 7, y0 + 72), (x + 7, y0 + 72), (x, y0 + 84)]
            if an:
                glow(s, x, y0 + 78, 8, (255, 50, 50), kern=False)
                pygame.draw.polygon(s, (255, 70, 70), dreieck)
            else:
                pygame.draw.polygon(s, GRAU, dreieck, 1)
            pygame.draw.line(s, (255, 90, 90) if an else GRAU, (x - 7, y0 + 85), (x + 7, y0 + 85), 2)
            pygame.draw.line(s, GRAU, (x, y0 + 85), (x, gnd), 1)
        for j, (name, pin) in enumerate(schueler_pi.TASTER.items()):  # Pull-up: gedrueckt = LOW
            x = x0 + 16 + j * 126
            y = y0 + 132
            gedrueckt = b.gedrueckt(name)
            text(s, f"GPIO{pin} {name}", 16, WEISS, (x, y - 12), "midleft", False)
            pygame.draw.circle(s, GRAU, (x + 4, y + 8), 3)
            pygame.draw.circle(s, GRAU, (x + 34, y + 8), 3)
            ende = (x + 34, y + 8) if gedrueckt else (x + 30, y - 4)
            pygame.draw.line(s, GELB if gedrueckt else GRAU, (x + 4, y + 8), ende, 2)
            text(s, "LOW" if gedrueckt else "HIGH", 18, GELB if gedrueckt else GRAU, (x + 44, y + 8), "midleft", False)
        f = b.f_jetzt
        y = y0 + 176
        text(s, f"GPIO{schueler_pi.BUZZER_PIN} Buzzer (PWM)", 16, WEISS, (x0 + 16, y), "midleft", False)
        if f:
            punkte, periode = [], max(4, int(6000 / f))
            for k in range(0, 120):
                punkte.append((x0 + 170 + k, y - 7 if (k // periode) % 2 else y + 7))
            pygame.draw.lines(s, PINK, False, punkte, 2)
            text(s, f"{f:.0f} Hz", 20, PINK, (x0 + 300, y), "midleft", False)
        else:
            text(s, "aus", 18, GRAU, (x0 + 170, y), "midleft", False)
