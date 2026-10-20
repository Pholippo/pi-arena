#!/usr/bin/env python3
"""PAC-PI - Pac-Man-artiges Spiel am Monitor, mit Platine:
LEDs = Fortschritt / Power-Countdown / Leben, Buzzer = Soundtrack + Effekte, Taster = Steuerung.

Steuerung: Pfeiltasten/WASD (absolut) · Handy-Steuerkreuz (absolut) · Platinen-Taster:
links/rechts = abbiegen (aus Sicht von Pac-Pi), Aktion = umdrehen / Start.
F = Vollbild an/aus, M = Musik an/aus, P = Pause, Esc = zurueck.

Direkt starten:  python3 pacpi.py [--sim] [--fenster]
Ohne Monitor testen (fuer Entwicklung): python3 pacpi.py --sim --selbsttest
"""
import json
import math
import os
import random
import sys
import time
from collections import deque

import ledarcade as la

# eigenes Labyrinth: # Wand, . Punkt, o Power-Pille, - Geistertuer, G Geisterhaus, P Start
LABYRINTH = [
    "#####################",
    "#.........#.........#",
    "#o###.###.#.###.###o#",
    "#...................#",
    "#.###.#.#####.#.###.#",
    "#.....#...#...#.....#",
    "#####.### # ###.#####",
    "    #.#       #.#    ",
    "#####.# ##-## #.#####",
    "     .  #GGG#  .     ",
    "#####.# ##### #.#####",
    "    #.#       #.#    ",
    "#####.# ##### #.#####",
    "#.........#.........#",
    "#.###.###.#.###.###.#",
    "#o..#.....P.....#..o#",
    "###.#.#.#####.#.#.###",
    "#.....#...#...#.....#",
    "#.#######.#.#######.#",
    "#...................#",
    "#####################",
]
B, H = len(LABYRINTH[0]), len(LABYRINTH)
TUER_RAUS = (10, 7)  # Feld ueber der Geistertuer
RICHTUNG = {"links": (-1, 0), "rechts": (1, 0), "oben": (0, -1), "unten": (0, 1)}
HIGHSCORE = os.path.join(la.HIER, "highscore.json")

# ---- Soundtrack (eigene Kompositionen, Buzzer-tauglich)
INTRO = la.lied("C5 E5 G5 C6:2 B5 G5 E5:2 - D5 F5 A5 D6:2 C6 A5 F5:2 - E5 G5 B5 E6 D6 C6 B5 G5 C6:4", 0.11)
THEMA = la.lied(
    "A3 A4 E4 A4 A3 A4 E4 A4 G3 G4 D4 G4 G3 G4 D4 G4 "
    "F3 F4 C4 F4 F3 F4 C4 F4 E3 E4 B3 E4 G#3 G#4 B3 E4 "
    "A4 C5 E5 A5 G5 E5 C5 E5 G4 B4 D5 G5 F5 D5 B4 D5 "
    "F4 A4 C5 F5 E5 C5 A4 C5 E4 G#4 B4 E5 D5 B4 G#4 B4", 0.13)
ANGST = la.lied("C6 G5 C6 G5 D6 A5 D6 A5", 0.07)
WAKA = [la.lied("E5 A4", 0.035), la.lied("A4 E5", 0.035)]
POWER = la.lied("E6 C6 E6 G6", 0.05)
GEIST_WEG = la.lied("G4 C5 E5 G5 C6 E6", 0.035)
TOD = la.lied("B5 A#5 A5 G#5 G5 F#5 F5 E5 D#5 D5 C#5 C5 - C4:3", 0.07)
LEVEL = la.lied("C5 E5 G5 C6 - G5 C6:4", 0.1)
GAMEOVER = la.lied("G4:2 E4:2 C4:4", 0.15)
BLITZ = la.lied("C4 G4 C5 G5 C6 E6 G6 C7 - C7 G6 C6", 0.03)      # LED-Blitz entladen
LADEN_VOLL = la.lied("E6 G6 C7", 0.04)                            # Leiste gerade voll geworden

FARBE = {"wand": (33, 66, 255), "wand_innen": (6, 10, 40), "punkt": (255, 200, 170), "pac": (255, 225, 0),
         "angst": (40, 60, 255), "text": (240, 240, 240), "gelb": (255, 225, 0), "grau": (150, 150, 170)}
GEISTER = [("Blinky", (255, 40, 40), 0.0, (B - 2, -2)), ("Pinky", (255, 150, 220), 2.0, (1, -2)),
           ("Inky", (0, 230, 255), 5.0, (B - 1, H)), ("Clyde", (255, 170, 40), 8.0, (0, H))]


def frei(x, y):
    if not 0 <= y < H:
        return False
    return LABYRINTH[y][x % B] in " .oP"


class Figur:
    def __init__(self, x, y, tempo):
        self.x, self.y, self.d, self.p, self.tempo = x, y, (0, 0), 0.0, tempo

    def pos(self):
        return self.x + self.d[0] * self.p, self.y + self.d[1] * self.p

    def umdrehen(self):
        if self.d != (0, 0) and self.p > 0:
            self.x = (self.x + self.d[0]) % B
            self.y += self.d[1]
            self.p = 1 - self.p
        self.d = (-self.d[0], -self.d[1])


class Geist(Figur):
    def __init__(self, name, farbe, warte, ecke, haus_x):
        super().__init__(haus_x, 9, 6.0)
        self.name, self.farbe, self.ecke, self.haus_x = name, farbe, ecke, haus_x
        self.zustand, self.timer = "haus", warte


def bfs_richtung(start, ziele, verboten=()):
    """Erste Richtung des kuerzesten Wegs von start zu einem der ziele (fuer Demo-Modus)."""
    q = deque([(start, None)])
    gesehen = {start}
    while q:
        (x, y), erste = q.popleft()
        if (x, y) in ziele and erste:
            return erste
        for d in RICHTUNG.values():
            n = ((x + d[0]) % B, y + d[1])
            if n not in gesehen and frei(*n) and n not in verboten:
                gesehen.add(n)
                q.append((n, erste or d))
    return None


class Spiel:
    def __init__(self, platine, pygame, bildschirm, vollbild):
        self.p, self.pg, self.vollbild = platine, pygame, vollbild
        self.fenster = bildschirm
        self.highscore = self.lade_highscore()
        self.zustand, self.demo = "titel", False
        self.zeit_im_zustand = 0.0
        self.neues_spiel()
        self.layout()

    # ---------- Daten
    def lade_highscore(self):
        try:
            with open(HIGHSCORE, encoding="utf-8") as f:
                return int(json.load(f).get("highscore", 0))
        except (OSError, ValueError):
            return 0

    def speichere_highscore(self):
        tmp = HIGHSCORE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"highscore": self.highscore}, f)
        os.replace(tmp, HIGHSCORE)

    def neues_spiel(self):
        self.punkte, self.leben, self.level = 0, 3, 1
        self.neues_level()

    def neues_level(self):
        self.punkte_feld = {(x, y): c for y, z in enumerate(LABYRINTH) for x, c in enumerate(z) if c in ".o"}
        self.gesamt = len(self.punkte_feld)
        self.positionen_zuruecksetzen()

    def positionen_zuruecksetzen(self):
        self.pac = Figur(10, 15, 7.5)
        self.wunsch = None
        tempo = 6.0 + 0.4 * (self.level - 1)
        self.geister = [Geist(n, f, w, e, 9 + i % 3) for i, (n, f, w, e) in enumerate(GEISTER)]
        for g in self.geister:
            g.tempo = min(tempo, 8.5)
            g.timer = max(0.5, g.timer - 0.5 * (self.level - 1))
        self.geister[0].zustand = "frei_lassen"
        self.angst_bis, self.combo = 0.0, 0
        self.modus_t, self.waka = 0.0, 0
        # Signatur-Mechanik "LED-BLITZ": Punkte fressen laedt die 8 Platinen-LEDs auf.
        # Volle Leiste + Aktionstaster = Blitz: alle Geister werden kurz fressbar UND durch die
        # Mauern gestossen (Teleport zum Geisterhaus). Das gibt es im Original nicht.
        self.ladung, self.blitz_flash, self.blitz_count = 0.0, 0.0, 0
        self.t = 0.0

    # ---------- Grafik
    def layout(self):
        w, h = self.fenster.get_size()
        self.oben, unten = 56, 44
        self.k = max(8, min(w // B, (h - self.oben - unten) // H))
        self.x0 = (w - B * self.k) // 2
        self.y0 = self.oben + ((h - self.oben - unten) - H * self.k) // 2
        pg = self.pg
        self.schrift = pg.font.Font(None, max(24, self.k))
        self.schrift_gross = pg.font.Font(None, max(48, self.k * 2))
        self.schrift_klein = pg.font.Font(None, max(18, int(self.k * 0.7)))
        self.wand = pg.Surface((B * self.k, H * self.k))
        self.wand.fill((0, 0, 0))
        k = self.k
        for y, zeile in enumerate(LABYRINTH):
            for x, c in enumerate(zeile):
                if c != "#":
                    continue
                r = pg.Rect(x * k, y * k, k, k)
                pg.draw.rect(self.wand, FARBE["wand_innen"], r)
                for dx, dy in RICHTUNG.values():
                    nx, ny = x + dx, y + dy
                    if 0 <= nx < B and 0 <= ny < H and LABYRINTH[ny][nx] != "#":
                        if dx:
                            xx = r.right - 2 if dx > 0 else r.left + 1
                            pg.draw.line(self.wand, FARBE["wand"], (xx, r.top), (xx, r.bottom - 1), 3)
                        else:
                            yy = r.bottom - 2 if dy > 0 else r.top + 1
                            pg.draw.line(self.wand, FARBE["wand"], (r.left, yy), (r.right - 1, yy), 3)
                if c == "#" and zeile[x] == "#" and LABYRINTH[y][x] == "#" and (x, y) == (10, 8):
                    pass
        tx, ty = 10, 8
        pg.draw.line(self.wand, (255, 180, 220), (tx * k, ty * k + k // 2), (tx * k + k, ty * k + k // 2), 4)

    def mitte(self, fx, fy):
        return (self.x0 + int((fx + 0.5) * self.k), self.y0 + int((fy + 0.5) * self.k))

    def text(self, s, farbe, pos, schrift=None, zentriert=True):
        bild = (schrift or self.schrift).render(s, True, farbe)
        r = bild.get_rect()
        r.midtop = pos if zentriert else r.midtop
        if not zentriert:
            r.topleft = pos
        self.fenster.blit(bild, r)

    def zeichne_pac(self, mund_auf=True, schrumpf=1.0):
        pg = self.pg
        cx, cy = self.mitte(*self.pac.pos())
        r = int(self.k * 0.45 * schrumpf)
        if r <= 1:
            return
        d = self.pac.d if self.pac.d != (0, 0) else (1, 0)
        winkel = math.atan2(d[1], d[0])
        mund = (abs(math.sin(self.t * 14)) * 0.8 + 0.05) if mund_auf else 0.05
        if schrumpf < 1:
            mund = math.pi * (1 - schrumpf) + 0.05
        punkte = [(cx, cy)]
        for i in range(31):
            a = winkel + mund + (2 * math.pi - 2 * mund) * i / 30
            punkte.append((cx + r * math.cos(a), cy + r * math.sin(a)))
        pg.draw.polygon(self.fenster, FARBE["pac"], punkte)

    def zeichne_geist(self, g):
        pg = self.pg
        if g.zustand == "haus" or g.zustand == "frei_lassen":
            cx, cy = self.mitte(g.haus_x, 9 + 0.15 * math.sin(self.t * 6 + g.haus_x))
        else:
            cx, cy = self.mitte(*g.pos())
        r = int(self.k * 0.45)
        rest = self.angst_bis - self.t
        if g.zustand == "angst":
            farbe = (240, 240, 255) if rest < 2 and int(self.t * 6) % 2 else FARBE["angst"]
        else:
            farbe = g.farbe
        if g.zustand != "augen":
            pg.draw.circle(self.fenster, farbe, (cx, cy - r // 4), r)
            pg.draw.rect(self.fenster, farbe, (cx - r, cy - r // 4, 2 * r, r + r // 4))
            for i in range(3):  # Wellen-Fuesse
                fx = cx - r + i * (2 * r // 3)
                welle = int(r * 0.25 * (1 + math.sin(self.t * 12 + i)))
                pg.draw.polygon(self.fenster, (0, 0, 0),
                                [(fx, cy + r + 1), (fx + r // 3, cy + r - welle - 2), (fx + 2 * r // 3, cy + r + 1)])
        if g.zustand == "angst":
            for ox in (-r // 3, r // 3):
                pg.draw.circle(self.fenster, (255, 200, 200), (cx + ox, cy - r // 4), max(2, r // 6))
            return
        dx, dy = g.d
        for ox in (-r // 3, r // 3):
            pg.draw.circle(self.fenster, (255, 255, 255), (cx + ox, cy - r // 4), max(3, r // 3))
            pg.draw.circle(self.fenster, (20, 40, 200),
                           (cx + ox + dx * r // 7, cy - r // 4 + dy * r // 7), max(2, r // 6))

    def zeichne(self):
        pg, f = self.pg, self.fenster
        f.fill((0, 0, 0))
        f.blit(self.wand, (self.x0, self.y0))
        level_blink = self.zustand == "level" and int(self.t * 8) % 2
        if level_blink:
            f.fill((255, 255, 255), (self.x0, self.y0, B * self.k, H * self.k), special_flags=pg.BLEND_RGB_ADD)
        if self.blitz_flash > self.t:  # LED-Blitz: greller Puls uebers Spielfeld
            g = int(max(0, (self.blitz_flash - self.t) / 0.9) * 230)
            f.fill((g, g, min(255, g + 40)), (self.x0, self.y0, B * self.k, H * self.k), special_flags=pg.BLEND_RGB_ADD)
        for (x, y), c in self.punkte_feld.items():
            m = self.mitte(x, y)
            if c == ".":
                pg.draw.circle(f, FARBE["punkt"], m, max(2, self.k // 10))
            elif int(self.t * 4) % 2 or self.zustand != "spiel":
                pg.draw.circle(f, FARBE["punkt"], m, max(4, self.k // 3))
        if self.zustand in ("spiel", "bereit", "titel", "level"):
            for g in self.geister:
                self.zeichne_geist(g)
        if self.zustand == "tod":
            self.zeichne_pac(schrumpf=max(0.0, 1 - self.zeit_im_zustand / 1.6))
        elif self.zustand != "over":
            self.zeichne_pac(mund_auf=self.zustand == "spiel" and self.pac.d != (0, 0))

        w = f.get_width()
        self.text(f"PUNKTE {self.punkte}", FARBE["text"], (self.x0, 8), zentriert=False)
        self.text(f"HIGHSCORE {self.highscore}", FARBE["gelb"], (w // 2, 8))
        self.text(f"LEVEL {self.level}", FARBE["text"], (self.x0 + B * self.k - 6 * self.k // 2 - 40, 8), zentriert=False)
        for i in range(self.leben):
            pg.draw.circle(f, FARBE["pac"], (self.x0 + 14 + i * 28, f.get_height() - 22), 10)
        self.text("Platine geloetet & programmiert: Philipp Grabner · 3AHEL", FARBE["grau"],
                  (w // 2 + 40, f.get_height() - 32), self.schrift_klein)
        # LED-BLITZ-Ladeleiste am oberen Rand, spiegelt die 8 Platinen-LEDs
        if self.zustand in ("spiel", "bereit"):
            n = self.p.n
            bw = max(10, self.k // 2)
            x0 = w - n * (bw + 4) - 16
            voll = self.ladung >= n
            for i in range(n):
                an = i < int(self.ladung)
                if voll:
                    an = ((int(self.t * 10) + i) % n) <= i
                farbe = (255, 230, 0) if voll else (0, 220, 90) if an else (40, 48, 60)
                pg.draw.rect(f, farbe, (x0 + i * (bw + 4), 34, bw, 12), border_radius=3)
            self.text("BLITZ ● BEREIT!" if voll else "LED-BLITZ", FARBE["gelb"] if voll else FARBE["grau"],
                      (x0 + n * (bw + 4) // 2, 48), self.schrift_klein)

        mitte_x = self.x0 + B * self.k // 2
        tafel_y = self.y0 + 11 * self.k
        if self.zustand == "titel":
            self.box("PAC-PI", FARBE["gelb"], "Druecke  ●  oder  ENTER" if int(self.t * 2) % 2 else "",
                     mitte_x, self.y0 + 3 * self.k)
            self.text("Punkte fressen laedt die 8 LEDs  ·  volle Leiste + ●  =  LED-BLITZ", FARBE["gelb"],
                      (mitte_x, self.y0 + 6 * self.k), self.schrift_klein)
            self.text("LEDs = Ladung & Power   ·   Buzzer + Monitor-Sound   ·   Handy = Gamepad", FARBE["grau"],
                      (mitte_x, self.y0 + 7 * self.k), self.schrift_klein)
        elif self.zustand == "bereit":
            self.text("BEREIT!", FARBE["gelb"], (mitte_x, tafel_y))
        elif self.zustand == "pause":
            self.box("PAUSE", FARBE["text"], "P = weiter", mitte_x, self.y0 + 6 * self.k)
        elif self.zustand == "over":
            self.box("GAME OVER", (255, 60, 60),
                     f"{self.punkte} Punkte" + ("  -  NEUER HIGHSCORE!" if self.neuer_rekord else ""),
                     mitte_x, self.y0 + 6 * self.k)
        if self.demo and self.zustand == "spiel":
            self.text("DEMO  -  druecke ● zum Spielen", FARBE["gelb"], (mitte_x, tafel_y))
        pg.display.flip()

    def box(self, titel, farbe, unter, x, y):
        pg = self.pg
        breite = int(B * self.k * 0.8)
        r = pg.Rect(0, 0, breite, int(self.k * 4))
        r.midtop = (x, y)
        pg.draw.rect(self.fenster, (0, 0, 0), r, border_radius=12)
        pg.draw.rect(self.fenster, farbe, r, 3, border_radius=12)
        self.text(titel, farbe, (x, r.top + self.k // 2), self.schrift_gross)
        self.text(unter, FARBE["text"], (x, r.top + int(self.k * 2.6)))

    # ---------- LEDs
    def leds(self):
        n, t = self.p.n, self.t
        if self.zustand == "titel":
            i = int(t * 10) % (2 * n - 2)
            i = i if i < n else 2 * n - 2 - i
            muster = [j == i for j in range(n)]
        elif self.blitz_flash > t:  # Blitz eben ausgeloest -> LED-Kaskade
            k = int((t - (self.blitz_flash - 0.6)) * 30) % (2 * n)
            muster = [abs(j - (k if k < n else 2 * n - 1 - k)) <= 1 for j in range(n)]
        elif self.zustand == "spiel" and self.angst_bis > t:  # Power laeuft -> Countdown
            rest = (self.angst_bis - t) / self.angst_dauer
            an = math.ceil(rest * n)
            blink = rest * self.angst_dauer < 2 and int(t * 8) % 2
            muster = [j < an and not blink for j in range(n)]
        elif self.zustand == "spiel" and self.ladung >= n:  # Blitz geladen -> alle lauffeuern
            i = int(t * 14) % n
            muster = [j <= i for j in range(n)]
        elif self.zustand == "spiel":  # Ladeleiste
            muster = [j < int(self.ladung) for j in range(n)]
        elif self.zustand == "bereit":
            muster = [j < self.leben for j in range(n)]
        elif self.zustand in ("tod", "over"):
            muster = [int(t * 6) % 2] * n
        elif self.zustand == "level":
            muster = [(j + int(t * 12)) % 2 for j in range(n)]
        else:
            muster = [0] * n
        self.p.zeige(muster)

    # ---------- Logik
    def setze(self, zustand):
        self.zustand, self.zeit_im_zustand = zustand, 0.0
        m = self.p.musik
        if zustand == "titel":
            m.musik(THEMA)
        elif zustand == "bereit":
            m.stop()
            m.effekt(INTRO)
        elif zustand == "spiel":
            m.musik(THEMA)
        elif zustand == "tod":
            m.stop()
            m.effekt(TOD)
        elif zustand == "level":
            m.stop()
            m.effekt(LEVEL)
        elif zustand == "over":
            m.stop()
            m.effekt(GAMEOVER)
        elif zustand == "pause":
            m.stop()

    def eingabe(self, e):
        """Gibt True zurueck, wenn das Spiel verlassen werden soll."""
        if e == "ende":
            return True
        start = e in ("aktion", "t_aktion")
        if self.zustand == "titel":
            if start or e in RICHTUNG:
                self.demo = False
                self.neues_spiel()
                self.setze("bereit")
            return False
        if self.demo and (start or e in RICHTUNG or e.startswith("t_")):
            self.demo = False
            self.neues_spiel()
            self.setze("bereit")
            return False
        if self.zustand == "over" and start and self.zeit_im_zustand > 1.0:
            self.setze("titel")
            return False
        if start and self.zustand == "spiel" and self.ladung >= self.p.n:
            self.blitz_feuern()
            return False
        d = self.pac.d if self.pac.d != (0, 0) else (self.wunsch or (-1, 0))
        if e in RICHTUNG:
            self.wunsch = RICHTUNG[e]
        elif e == "t_links":
            self.wunsch = (d[1], -d[0])
        elif e == "t_rechts":
            self.wunsch = (-d[1], d[0])
        elif e == "t_aktion" and self.zustand == "spiel":
            self.wunsch = (-d[0], -d[1])  # Taster-Aktion ohne Ladung = umdrehen
        return False

    def blitz_feuern(self):
        self.ladung = 0.0
        self.blitz_flash = self.t + 0.9
        self.blitz_count += 1
        self.angst_dauer = max(2.0, 6.0 - 0.6 * (self.level - 1))
        self.angst_bis, self.combo = self.t + self.angst_dauer, 0
        self.p.musik.effekt(BLITZ)
        for g in self.geister:
            if g.zustand == "jagd":
                g.zustand = "angst"
                g.umdrehen()
            elif g.zustand == "angst":  # schon fressbare Geister fliegen heim = Luft zum Atmen
                g.zustand = "augen"

    def ziel(self, g):
        px, py = self.pac.x, self.pac.y
        if g.zustand == "augen":
            return TUER_RAUS
        if (self.modus_t % 27) < 7:  # Verteilen-Phase: jeder in seine Ecke
            return g.ecke
        d = self.pac.d
        if g.name == "Blinky":
            return px, py
        if g.name == "Pinky":
            return px + 4 * d[0], py + 4 * d[1]
        if g.name == "Inky":
            b = self.geister[0]
            return 2 * (px + 2 * d[0]) - b.x, 2 * (py + 2 * d[1]) - b.y
        if (g.x - px) ** 2 + (g.y - py) ** 2 > 64:
            return px, py
        return g.ecke

    def waehle(self, g):
        rueck = (-g.d[0], -g.d[1])
        optionen = [d for d in RICHTUNG.values() if frei(g.x + d[0], g.y + d[1]) and d != rueck]
        if not optionen:
            return rueck if frei(g.x + rueck[0], g.y + rueck[1]) else (0, 0)
        if g.zustand == "angst":
            return random.choice(optionen)
        zx, zy = self.ziel(g)
        return min(optionen, key=lambda d: ((g.x + d[0] - zx) ** 2 + (g.y + d[1] - zy) ** 2, random.random()))

    def bewege_geist(self, g, dt):
        if g.zustand in ("haus", "frei_lassen"):
            g.timer -= dt
            if g.zustand == "frei_lassen" or g.timer <= 0:
                g.x, g.y = TUER_RAUS
                g.d, g.p = random.choice([(-1, 0), (1, 0)]), 0.0
                g.zustand = "angst" if self.angst_bis > self.t else "jagd"
            return
        tempo = {"angst": 3.8, "augen": 15.0}.get(g.zustand, g.tempo)
        if g.y == 9 and (g.x < 5 or g.x > 15):
            tempo *= 0.55  # Tunnel bremst
        if g.d == (0, 0):
            g.d = self.waehle(g)
        g.p += tempo * dt
        while g.p >= 1:
            g.p -= 1
            g.x, g.y = (g.x + g.d[0]) % B, g.y + g.d[1]
            if g.zustand == "augen" and (g.x, g.y) == TUER_RAUS:
                g.zustand, g.timer, g.p = "haus", 1.5, 0.0
                return
            g.d = self.waehle(g)
            if g.d == (0, 0):
                g.p = 0
                break

    def bewege_pac(self, dt):
        pac, w = self.pac, self.wunsch
        if w and pac.d != (0, 0) and w == (-pac.d[0], -pac.d[1]):
            pac.umdrehen()
        if pac.p == 0:
            if w and frei(pac.x + w[0], pac.y + w[1]):
                pac.d = w
            elif not frei(pac.x + pac.d[0], pac.y + pac.d[1]):
                return
        pac.p += pac.tempo * dt
        while pac.p >= 1:
            pac.p -= 1
            pac.x, pac.y = (pac.x + pac.d[0]) % B, pac.y + pac.d[1]
            self.fressen(pac.x, pac.y)
            if w and frei(pac.x + w[0], pac.y + w[1]):
                pac.d = w
            if not frei(pac.x + pac.d[0], pac.y + pac.d[1]):
                pac.p = 0
                break

    def laden(self, menge):
        if self.ladung < self.p.n:
            self.ladung = min(self.p.n, self.ladung + menge)
            if self.ladung >= self.p.n:  # gerade voll -> Blitz bereit
                self.p.musik.effekt(LADEN_VOLL)

    def fressen(self, x, y):
        c = self.punkte_feld.pop((x, y), None)
        m = self.p.musik
        if c == ".":
            self.punkte += 10
            self.waka ^= 1
            m.effekt(WAKA[self.waka])
            self.laden(0.34)
        elif c == "o":
            self.punkte += 50
            self.angst_dauer = max(2.0, 7.0 - 0.7 * (self.level - 1))
            self.angst_bis, self.combo = self.t + self.angst_dauer, 0
            m.effekt(POWER)
            m.musik(ANGST)
            for g in self.geister:
                if g.zustand == "jagd":
                    g.zustand = "angst"
                    g.umdrehen()

    def demo_steuern(self):
        pac = self.pac
        if self.ladung >= self.p.n and self.angst_bis <= self.t:  # Demo zeigt den Blitz her
            self.blitz_feuern()
        if pac.p != 0 and pac.d != (0, 0):
            return
        gefahr = set()
        for g in self.geister:
            if g.zustand == "jagd":
                gefahr |= {(g.x, g.y), ((g.x + g.d[0]) % B, g.y + g.d[1])}
        ziele = set(self.punkte_feld)
        if self.angst_bis > self.t:
            ziele |= {(g.x, g.y) for g in self.geister if g.zustand == "angst"}
        d = bfs_richtung((pac.x, pac.y), ziele, gefahr) or bfs_richtung((pac.x, pac.y), ziele)
        if d:
            self.wunsch = d

    def schritt(self, dt):
        self.t += dt
        self.zeit_im_zustand += dt
        z = self.zustand
        if z == "titel" and self.zeit_im_zustand > 12:
            self.demo = True
            self.neues_spiel()
            self.setze("bereit")
        elif z == "bereit" and self.zeit_im_zustand > (1.0 if self.demo else 2.6):
            self.setze("spiel")
        elif z == "tod" and self.zeit_im_zustand > 2.2:
            self.leben -= 1
            if self.leben <= 0:
                self.neuer_rekord = self.punkte > self.highscore and not self.demo
                if self.neuer_rekord:
                    self.highscore = self.punkte
                    self.speichere_highscore()
                self.setze("titel" if self.demo else "over")
                self.demo = False
            else:
                self.positionen_zuruecksetzen()
                self.setze("bereit")
        elif z == "level" and self.zeit_im_zustand > 2.4:
            self.level += 1
            self.neues_level()
            self.setze("bereit")
        elif z == "over" and self.zeit_im_zustand > 10:
            self.setze("titel")
        elif z == "spiel":
            self.modus_t += dt
            if self.demo:
                self.demo_steuern()
            self.bewege_pac(dt)
            if self.angst_bis and self.t >= self.angst_bis:
                self.angst_bis = 0.0
                self.p.musik.musik(THEMA)
                for g in self.geister:
                    if g.zustand == "angst":
                        g.zustand = "jagd"
            for g in self.geister:
                self.bewege_geist(g, dt)
                if g.zustand in ("jagd", "angst"):
                    gx, gy = g.pos()
                    px, py = self.pac.pos()
                    if (gx - px) ** 2 + (gy - py) ** 2 < 0.45:
                        if g.zustand == "angst":
                            self.combo += 1
                            self.punkte += 100 * 2 ** self.combo
                            g.zustand = "augen"
                            self.p.musik.effekt(GEIST_WEG)
                            self.laden(2.0)  # Geist fressen laedt den Blitz spuerbar
                        else:
                            self.setze("tod")
                            return
            if not self.punkte_feld:
                self.setze("level")


def starte(platine, vollbild=None, selbsttest=0.0):
    """Startet PAC-PI. platine = ledarcade.Platine. Gibt die Punkte des letzten Spiels zurueck."""
    if selbsttest:
        os.environ["SDL_VIDEODRIVER"] = "dummy"
    elif os.name != "nt":
        os.environ.setdefault("DISPLAY", ":0")  # auch per SSH auf dem Pi-Monitor starten
    if selbsttest:
        os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
    import pygame
    pygame.mixer.pre_init(44100, -16, 2, 512)
    pygame.init()
    # Monitor-/HDMI-Soundtrack (Chiptune) parallel zum Buzzer einhaengen
    if not selbsttest:
        try:
            import chiptune
            klang = chiptune.Chiptune()
            platine.musik.sink = (lambda art, lied:
                                  klang.musik(lied) if art == "musik" else
                                  klang.stop() if art == "stop" else klang.effekt(lied))
        except Exception as e:
            print("Monitor-Sound aus:", e)
    if vollbild is None:
        vollbild = os.name != "nt" and not selbsttest
    if vollbild:
        fenster = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
        pygame.mouse.set_visible(False)
    else:
        fenster = pygame.display.set_mode((21 * 32, 21 * 32 + 100), pygame.RESIZABLE)
    pygame.display.set_caption("PAC-PI")
    spiel = Spiel(platine, pygame, fenster, vollbild)
    spiel.setze("titel")
    uhr = pygame.time.Clock()
    tasten = {pygame.K_LEFT: "links", pygame.K_a: "links", pygame.K_RIGHT: "rechts", pygame.K_d: "rechts",
              pygame.K_UP: "oben", pygame.K_w: "oben", pygame.K_DOWN: "unten", pygame.K_s: "unten",
              pygame.K_RETURN: "aktion", pygame.K_SPACE: "aktion", pygame.K_ESCAPE: "ende"}
    if selbsttest:
        spiel.demo = True
        spiel.neues_spiel()
        spiel.setze("bereit")
    gestartet = time.time()
    try:
        while True:
            dt = min(0.05, uhr.tick(0 if selbsttest else 60) / 1000)
            if selbsttest:
                dt = 1 / 60
                if spiel.t >= selbsttest:
                    break
            for ev in pygame.event.get():
                if ev.type == pygame.QUIT:
                    return spiel.punkte
                if ev.type == pygame.VIDEORESIZE and not spiel.vollbild:
                    spiel.fenster = pygame.display.set_mode(ev.size, pygame.RESIZABLE)
                    spiel.layout()
                if ev.type == pygame.KEYDOWN:
                    if ev.key == pygame.K_f:
                        spiel.vollbild = not spiel.vollbild
                        spiel.fenster = (pygame.display.set_mode((0, 0), pygame.FULLSCREEN) if spiel.vollbild
                                         else pygame.display.set_mode((21 * 32, 21 * 32 + 100), pygame.RESIZABLE))
                        spiel.layout()
                    elif ev.key == pygame.K_m:
                        platine.musik.an = not platine.musik.an
                    elif ev.key == pygame.K_p and spiel.zustand in ("spiel", "pause"):
                        spiel.setze("spiel" if spiel.zustand == "pause" else "pause")
                    elif ev.key in tasten and spiel.eingabe(tasten[ev.key]):
                        return spiel.punkte
            while not platine.events.empty():  # Taster, Handy, Terminal
                if spiel.eingabe(platine.events.get_nowait()):
                    return spiel.punkte
            if spiel.zustand != "pause":
                spiel.schritt(dt)
            spiel.leds()
            spiel.zeichne()
    finally:
        platine.musik.stop()
        platine.aus()
        pygame.quit()
        if selbsttest:
            print(f"Selbsttest: {spiel.t:.0f} s Spielzeit in {time.time() - gestartet:.1f} s, "
                  f"Level {spiel.level}, {spiel.punkte} Punkte, Leben {spiel.leben}, "
                  f"Restpunkte {len(spiel.punkte_feld)}/{spiel.gesamt}, Zustand {spiel.zustand}")
    return spiel.punkte


if __name__ == "__main__":
    args = sys.argv[1:]
    p = la.Platine(la.lade_config(), sim="--sim" in args)
    la.starte_web(p)
    test = 0.0
    if "--selbsttest" in args:
        test = 240.0
        p.musik.an = False
    starte(p, vollbild=False if "--fenster" in args else None, selbsttest=test)
