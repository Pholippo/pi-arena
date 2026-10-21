#!/usr/bin/env python3
"""Fuehrt alle Tests des Projekts aus und zeigt am Ende eine Zusammenfassung.

Aufruf (egal aus welchem Ordner):   python3 tests/run_all.py
Nur bestimmte Tests:                python3 tests/run_all.py browserspiele qrgen vorlagen
Laeuft am Laptop (Windows/Linux/macOS) und am Pi - ohne Platine, ohne Monitor.

Braucht: Python 3.11+ mit pygame. Node.js (fuer die zwei Browser-Spiel-Tests) ist optional:
fehlt es, werden diese Tests als UEBERSPRUNGEN gemeldet.
Die Ports 8081/8082 muessen frei sein (PiArena vorher mit ./stop.sh beenden).
"""
import os
import shutil
import subprocess
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = [sys.executable, "-X", "utf8"]
NODE = shutil.which("node")

# (Kurzname, Befehl, Zeitlimit in s, braucht Node?)
TESTS = [
    ("browserspiele", PY + ["arena/browserspiele.py", "--selbsttest"], 60, False),
    ("host", PY + ["arena/host.py", "--selbsttest", "--sim"], 600, False),
    ("ninja", ["node", "tests/ninja_qa.mjs", "arena/web/ninja.html", "30"], 600, True),
    ("auto", ["node", "tests/auto_test.cjs", "arena/web/auto.html"], 120, True),
    ("webtest", PY + ["tests/webtest.py"], 300, False),
    ("moderator", PY + ["tests/webtest_moderator.py"], 300, False),
    ("qrgen", PY + ["tests/verify_qrgen.py"], 60, False),
    ("vorlagen", PY + ["tools/web-vorlagen/build.py", "--pruefen"], 60, False),
]


def lauf(name, befehl, limit):
    """-> (status, sekunden, Ausgabe-Zeilen, letzte stdout-Zeile)"""
    env = dict(os.environ, SDL_VIDEODRIVER="dummy", SDL_AUDIODRIVER="dummy", PYTHONUTF8="1",
               PYGAME_HIDE_SUPPORT_PROMPT="1")
    t0 = time.monotonic()
    try:
        p = subprocess.run(befehl, cwd=REPO, env=env, capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=limit)
        ausgabe, ok = (p.stdout or "") + (p.stderr or ""), p.returncode == 0
        status = "OK" if ok else f"FEHLER (Code {p.returncode})"
        letzte = [z for z in (p.stdout or "").splitlines() if z.strip()]
    except subprocess.TimeoutExpired as e:
        roh = (e.stdout or b"") + (e.stderr or b"")
        ausgabe = roh.decode("utf-8", "replace") if isinstance(roh, bytes) else str(roh)
        status, letzte = f"FEHLER (Zeitlimit {limit} s)", []
    except OSError as e:
        ausgabe, status, letzte = str(e), "FEHLER (Start)", []
    zeilen = [z for z in ausgabe.splitlines() if z.strip()]
    return status, time.monotonic() - t0, zeilen, (letzte or zeilen or [""])[-1]


def main():
    auswahl = set(sys.argv[1:])
    unbekannt = auswahl - {t[0] for t in TESTS}
    if unbekannt:
        print("Unbekannter Test:", ", ".join(sorted(unbekannt)), "- moeglich:", ", ".join(t[0] for t in TESTS))
        return 2
    ergebnisse = []
    for name, befehl, limit, braucht_node in TESTS:
        if auswahl and name not in auswahl:
            continue
        zeile = ["python3"] + befehl[3:] if befehl[0] == sys.executable else befehl
        print(f"\n=== {name}: {' '.join(zeile)}", flush=True)
        if braucht_node and not NODE:
            ergebnisse.append((name, "UEBERSPRUNGEN (kein node)", 0.0, ""))
            print("  uebersprungen: Node.js nicht installiert")
            continue
        status, dauer, zeilen, letzte = lauf(name, befehl, limit)
        for z in (zeilen if not status.startswith("OK") else zeilen[-4:]):
            print("  " + z)
        ergebnisse.append((name, status, dauer, letzte))
    print("\n" + "=" * 78 + "\nZUSAMMENFASSUNG")
    for name, status, dauer, letzte in ergebnisse:
        print(f"  {name:<10} {status:<28} {dauer:6.1f} s   {letzte[:80]}")
    fehler = [e for e in ergebnisse if e[1].startswith("FEHLER")]
    print("=" * 78)
    print(f"GESAMT: {'OK' if not fehler else 'FEHLER'} - {len(ergebnisse) - len(fehler)}/{len(ergebnisse)} ohne Fehler")
    return 1 if fehler else 0


if __name__ == "__main__":
    sys.exit(main())
