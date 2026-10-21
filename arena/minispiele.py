#!/usr/bin/env python3
"""MINISPIELE - HIER baust du deine eigenen Spiele fuer PiArena!

Jedes Minispiel ist EINE Funktion  spiel_xyz(b, p, rng)  plus EIN Eintrag in der Tabelle SPIELE (ganz unten).
Mehr braucht es nicht: Der Host nimmt jedes Spiel aus SPIELE automatisch in die Runden auf
(ausser es steht in DEAKTIVIERT in arena/einstellungen.py).

DIE DREI ZUTATEN JEDER SPIEL-FUNKTION
  b    = das Brett, also DEINE Platine (10 LEDs, 3 Taster, Buzzer)
  p    = Parameter vom Host, z.B. p["dauer"] (meist brauchst du p gar nicht)
  rng  = Zufall, der auf ALLEN Pis gleich ist (gleicher Seed) -> alle Platinen blitzen gleichzeitig.
         Beispiel: rng.randint(1, 5) liefert bei allen Spielern dieselbe Zahl.

DIE BEFEHLE FUER DIE PLATINE (b.)
  b.zeige([1,0,0,0,0,0,0,0,0,1])   LEDs setzen: 1 = an, 0 = aus (10 Stueck, links -> rechts)
  b.zeige(balken(3))               die ersten 3 LEDs an (Balken)
  b.warte(2.0)                     wartet bis zu 2 s auf einen Taster -> ("links"/"mitte"/"rechts", zeitpunkt) oder None
  b.pause(0.5)                     0,5 s warten (Tastendruecke dabei werden ignoriert)
  b.leeren()                       alte Tastendruecke wegwerfen (vor dem Start eines Versuchs)
  b.ton(kurz("A5", 0.1))           einen Ton spielen (Note + Dauer in s), oder fertige Toene wie T_SUPER, T_FEHL
  b.bot                            nur bei Test-Bots gesetzt: dann spielt der Computer selbst mit
  b.bot_drueck("mitte", 0.5)       Bot drueckt in 0,5 s den Taster MITTE
  b.skill                          wie gut der Bot ist (1.0 = normal, groesser = langsamer)

WICHTIG
  - Zum Warten NUR b.warte / b.pause benutzen, nie time.sleep - sonst geht "Runde ueberspringen" nicht.
  - Jedes Spiel gibt am Ende zurueck:  {"wert": Zahl, "ok": True/False, "text": "fuer den Monitor"}
    "wert" vergleicht der Host: In SPIELE steht, ob ein hoher oder tiefer Wert besser ist.
  - Das einfachste Beispiel zum Abschauen ist spiel_morse (MORSE-ZAEHLER) ganz unten.

DEIN SPIEL TESTEN (am Laptop oder Pi, ohne andere Spieler)
  python3 arena/host.py --fenster --nur morse      (statt morse dein Spiel)
  Im Fenster: Pfeil LINKS = Demo-Bots dazu, LEERTASTE = Start, A S D = deine drei Taster.
"""
import time

N = 10  # so viele LEDs hat die Platine (die GPIO-Pins stehen in LED_PINS in spieler.py)
TASTEN = ("links", "mitte", "rechts")


# ---------------------------------------------------------------- Toene
# Noten wie am Klavier: "A4" = 440 Hz, "C6" = hohes C, "-" = Pause. lied("C5 E5 G5:2") = 3 Noten, die letzte doppelt lang.

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


# ---------------------------------------------------------------- Helfer fuer die LEDs


def balken(wert):
    """balken(3) -> die ersten 3 LEDs an, der Rest aus."""
    return [i < wert for i in range(N)]


def blinke(b, muster, mal=3, t=0.1):
    """Muster mal-mal blinken lassen."""
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


# ---------------------------------------------------------------- BEISPIEL ZUM ABSCHAUEN: MORSE-ZAEHLER
# Ist noch in DEAKTIVIERT (arena/einstellungen.py) -> uebe damit: Spiel aktivieren, aendern, testen.


def spiel_morse(b, p, rng):
    """Die LEDs blitzen 1 bis 5 Mal. Danach drueckst du MITTE genau so oft. Richtig + schnell gewinnt."""
    anzahl = rng.randint(1, 5)        # wie oft es blitzt - bei allen Spielern gleich (gemeinsamer Zufall)
    b.zeige([0] * N)                  # alle LEDs aus
    b.pause(1.0)                      # kurz durchatmen

    for _ in range(anzahl):           # anzahl-mal blitzen
        b.zeige([1] * N)              # alle 10 LEDs an
        b.ton(kurz("A5", 0.1))        # kurzer Piep dazu
        b.pause(0.3)
        b.zeige([0] * N)              # alle aus
        b.pause(0.4)

    b.leeren()                        # Druecke von vorhin zaehlen nicht
    if b.bot:                         # nur fuer Test-Bots: der Computer drueckt selbst
        for i in range(anzahl):
            b.bot_drueck("mitte", (0.4 + i * 0.3) * b.skill)

    gedrueckt = 0
    zeit = 0.0                        # wann der letzte Druck war (Sekunden nach dem Start)
    start = time.monotonic()          # Stoppuhr starten
    while time.monotonic() - start < 4:   # 4 Sekunden Zeit zum Druecken
        taste = b.warte(0.1)          # -> ("mitte", zeitpunkt) oder None
        if taste and taste[0] == "mitte":
            gedrueckt += 1
            zeit = taste[1] - start   # taste[1] = Zeitpunkt des Drucks
            b.zeige(balken(gedrueckt))    # so viele LEDs wie schon gedrueckt
            b.ton(kurz("E6", 0.04))

    richtig = gedrueckt == anzahl
    if richtig:
        b.ton(T_SUPER)
        blinke(b, balken(anzahl))
    else:
        b.ton(T_FEHL)
    # "wert" = Zeit bis zum letzten Druck -> kleiner ist besser ("besser": "tief" in SPIELE).
    # Nur wer richtig gezaehlt hat ("ok": True), bekommt Punkte.
    return {"wert": round(zeit, 2), "ok": richtig, "text": f"{gedrueckt} von {anzahl} in {zeit:.1f} s"}


# ================================================================ DIE SPIEL-TABELLE
# Der Host liest hier Name, Regeltext und Wertung. Neues Spiel = neue Zeile (Vorlage: "morse" ganz unten).
#   handy  : True = auch im Handy-Browser spielbar (dann braucht arena/ablauf.py eine Handy-Wertung) - sonst False
#   name   : so steht das Spiel gross am Monitor
#   fn     : deine Spiel-Funktion
#   besser : "hoch" = groesster "wert" gewinnt, "tief" = kleinster "wert" gewinnt
#   trost  : Punkte fuer alle mit "ok" ausserhalb der Plaetze 1-3 (meist 0)
#   dauer  : so viele Sekunden wartet der Host hoechstens auf die Ergebnisse
#   kurz   : Regel in einem Satz (Monitor + Terminal)
#   tasten : Beschriftung von LINKS / MITTE / RECHTS in der Ansage am Monitor
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
    "morse": {"handy": False, "name": "MORSE-ZAEHLER", "fn": spiel_morse, "besser": "tief", "trost": 0,
              "dauer": 14, "kurz": "Zaehl die Blitze und druecke MITTE genau so oft!",
              "tasten": ("", "DRUECKEN", "")},
}
