#!/usr/bin/env python3
"""TURBO-BLITZ - schnelles, lautes LED+Buzzer-Reaktionsspiel fuer die HTL-Platine.

Nutzt die ECHTE Platine: 10 LEDs, 3 Taster (links/mitte/rechts), passiver Buzzer auf GPIO 25.
Baut auf ledarcade.py auf (Hardware, Tastatur, Handy-Browser, Buzzer-Musik).

Modi (im Menue mit Links/Rechts waehlen, Aktion startet):
  1 Maulwurf-Blitz  - Eine LED leuchtet. Druecke den passenden Taster (links/mitte/rechts)
                      BEVOR sie ausgeht. Treffer = heller Ton, wird immer schneller. 3 Leben.
  2 Reaktion        - Die LED-Leiste fuellt sich, dann blitzt bei Zufallszeitpunkt ALLES auf
                      -> so schnell wie moeglich Aktion druecken. Zeit wird binaer + als Ton gezeigt.
  3 Synth           - Freies Spiel: 3 Taster = 3 Toene, LEDs als VU-Meter. Einfach Krach machen.

Aufrufe:
  python3 turbo.py            Menue
  python3 turbo.py 1          direkt Modus 1
  python3 turbo.py --sim      ohne Raspberry testen (LEDs im Terminal, Ton per winsound/stumm)
  python3 turbo.py --selbsttest  headless-Selbsttest (spielt sich kurz selbst, fuer CI)
"""
import os
import random
import sys
import time

import ledarcade as la

# Toene (Notennamen wie in ledarcade.frequenz)
T_HOCH = [("C6", 0.05), ("E6", 0.05), ("G6", 0.07)]      # Treffer
T_SUPER = [("C6", 0.04), ("E6", 0.04), ("G6", 0.04), ("C7", 0.1)]
T_TIEF = [("A3", 0.12), ("F3", 0.18)]                      # Fehler
T_START = [("C5", 0.08), ("E5", 0.08), ("G5", 0.08), ("C6", 0.12)]
T_TICK = [("E5", 0.03)]
FANFARE = [("C6", 0.12), ("C6", 0.12), ("G5", 0.12), ("C6", 0.12), ("E6", 0.12), ("C6", 0.25)]
SYNTH_TON = {"links": "C5", "aktion": "E5", "rechts": "G5"}


def lauflicht(p, runden=1, dt=0.03):
    """kurze LED-Welle hin und zurueck."""
    seq = list(range(p.n)) + list(range(p.n - 2, 0, -1))
    for _ in range(runden):
        for i in seq:
            m = [0] * p.n
            m[i] = 1
            p.zeige(m)
            p.pause(dt)
    p.aus()


def zahl_binaer(p, wert, zeit=2.0):
    """zeigt eine Zahl binaer auf den LEDs (LED0 = niederwertigstes Bit)."""
    muster = [(wert >> i) & 1 for i in range(p.n)]
    p.zeige(muster)
    p.pause(zeit)
    p.aus()


# ------------------------------------------------------------------ Modus 1

def zone(led_index, n):
    """ordnet eine LED einem Taster zu: linkes Drittel -> links, Mitte -> aktion, rechts -> rechts."""
    drittel = n / 3.0
    if led_index < drittel:
        return "links"
    if led_index < 2 * drittel:
        return "aktion"
    return "rechts"


def maulwurf(p, auto=False, dauer=0.0):
    p.text = "Maulwurf-Blitz"
    p.musik.stop()
    p.leeren()
    lauflicht(p, 1)
    p.musik.effekt(T_START)
    p.pause(0.6)
    leben = 3
    punkte = 0
    zeit = 1.1  # Zeitfenster pro Maulwurf, wird knapper
    ende = time.time() + dauer if dauer else None
    while leben > 0:
        if ende and time.time() > ende:
            break
        ziel = random.randrange(p.n)
        soll = zone(ziel, p.n)
        m = [0] * p.n
        m[ziel] = 1
        p.zeige(m)
        p.leeren()
        if auto:
            # Selbsttest: meistens richtig, manchmal daneben
            p.pause(0.02)
            eingabe = soll if random.random() < 0.75 else random.choice(["links", "aktion", "rechts"])
        else:
            eingabe = p.warte(zeit)
        if eingabe == soll:
            punkte += 1
            schnell = T_SUPER if punkte % 10 == 0 else T_HOCH
            p.musik.effekt(schnell)
            # kurzer Treffer-Blitz
            p.zeige([1] * p.n)
            p.pause(0.05)
            p.zeige(m)
            p.pause(0.05)
            zeit = max(0.33, zeit * 0.96)
        else:
            leben -= 1
            p.musik.effekt(T_TIEF)
            # LED an der Zielstelle blinkt zur Strafe
            for _ in range(3):
                p.zeige(m)
                p.pause(0.08)
                p.aus()
                p.pause(0.08)
        p.aus()
        p.pause(0.12)
    p.text = f"Punkte {punkte}"
    p.musik.effekt(FANFARE)
    lauflicht(p, 2)
    zahl_binaer(p, punkte, 2.5)
    return punkte


# ------------------------------------------------------------------ Modus 2

def reaktion(p, auto=False, dauer=0.0):
    p.text = "Reaktion"
    p.musik.stop()
    p.leeren()
    runden = 3
    summe = 0
    ende = time.time() + dauer if dauer else None
    for r in range(runden):
        if ende and time.time() > ende:
            break
        # Fuell-Leiste als Spannung
        for i in range(p.n):
            m = [1] * (i + 1) + [0] * (p.n - i - 1)
            p.zeige(m)
            p.musik.effekt(T_TICK)
            p.pause(random.uniform(0.08, 0.18))
        p.aus()
        p.pause(random.uniform(0.5, 1.8))  # gemeine Zufallspause
        p.leeren()
        start = time.time()
        p.zeige([1] * p.n)  # JETZT!
        if auto:
            p.pause(random.uniform(0.15, 0.35))
            eingabe = "aktion"
        else:
            eingabe = p.warte(2.0)
        ms = int((time.time() - start) * 1000)
        if eingabe is None:
            p.musik.effekt(T_TIEF)
            p.text = "zu langsam"
            p.aus()
            p.pause(0.8)
            continue
        summe += ms
        p.musik.effekt(T_HOCH)
        p.text = f"{ms} ms"
        p.aus()
        zahl_binaer(p, min(255, ms // 8), 1.4)  # grobe Anzeige
    schnitt = summe // max(1, runden)
    p.text = f"~{schnitt} ms"
    p.musik.effekt(FANFARE)
    return schnitt


# ------------------------------------------------------------------ Modus 3

def synth(p, auto=False, dauer=0.0):
    p.text = "Synth - 3 Taster"
    p.musik.stop()
    p.leeren()
    lauflicht(p, 1)
    ende = time.time() + (dauer or 8.0)
    pegel = 0
    while time.time() < ende:
        if auto:
            p.pause(0.1)
            eingabe = random.choice(["links", "aktion", "rechts", None])
        else:
            eingabe = p.warte(0.2)
        if eingabe in SYNTH_TON:
            p.musik.effekt([(SYNTH_TON[eingabe], 0.18)])
            pegel = p.n
        pegel = max(0, pegel - 1)
        p.zeige([1] * pegel + [0] * (p.n - pegel))  # VU-Meter faellt ab
    p.aus()
    return 0


MODI = [("Maulwurf-Blitz", maulwurf), ("Reaktion", reaktion), ("Synth", synth)]


def menue(p):
    i = 0
    while True:
        p.text = f"> {MODI[i][0]}"
        # Auswahl als LED-Markierung zeigen
        m = [0] * p.n
        m[int(i * (p.n - 1) / (len(MODI) - 1))] = 1
        p.zeige(m)
        e = p.warte(0.4)
        if e == "links":
            i = (i - 1) % len(MODI)
            p.musik.effekt(T_TICK)
        elif e == "rechts":
            i = (i + 1) % len(MODI)
            p.musik.effekt(T_TICK)
        elif e == "aktion":
            p.musik.effekt(T_START)
            try:
                MODI[i][1](p)
            except la.Ende:
                pass
            p.musik.stop()


def main():
    args = sys.argv[1:]
    sim = "--sim" in args or os.name == "nt"
    selbsttest = "--selbsttest" in args
    cfg = la.lade_config()
    p = la.Platine(cfg, sim=sim)
    la.starte_web(p)
    # eigene_ip() nimmt das LAN-Kabel -> fuers Handy im WLAN alle Adressen zeigen
    try:
        import subprocess
        ips = subprocess.run(["hostname", "-I"], capture_output=True, text=True, timeout=3).stdout.split()
    except Exception:
        ips = []
    print("TURBO-BLITZ laeuft. Handy: " + ", ".join(f"http://{ip}:{la.WEB_PORT}" for ip in ips if "." in ip))
    if selbsttest:
        maulwurf(p, auto=True, dauer=3)
        reaktion(p, auto=True, dauer=3)
        synth(p, auto=True, dauer=2)
        p.aus()
        print("Selbsttest ok", flush=True)
        os._exit(0)  # Buzzer-Thread ist daemon -> sonst Absturzmeldung beim Python-Shutdown
    direkt = next((a for a in args if a.isdigit()), None)
    try:
        if direkt and 1 <= int(direkt) <= len(MODI):
            MODI[int(direkt) - 1][1](p)
        else:
            menue(p)
    except (KeyboardInterrupt, la.Ende):
        pass
    finally:
        p.aus()
        p.musik.stop()


if __name__ == "__main__":
    main()
