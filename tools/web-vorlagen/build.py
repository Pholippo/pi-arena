#!/usr/bin/env python3
"""Baut die drei Browser-Spiele arena/web/ninja.html, arena/web/flappy.html, arena/web/auto.html aus den Vorlagen.

Der PARTY-UI-Block (Namensschild "DU", Rangliste, Countdown, Optik) steht in allen drei Spielen
identisch. Er wird NUR hier geaendert:
    party_ui.js / party_ui.css   gemeinsamer Teil fuer alle drei Spiele
    <spiel>.tpl.html             das eigentliche Spiel, mit Platzhaltern @@CSS@@ @@UI@@ (@@LEVEL@@)
    ninja_level.js               Level-Generator + Physik von NINJA-RACE (tests/ninja_qa.mjs prueft genau diesen Code)

Aufrufe (aus dem Repo-Ordner):
    python3 tools/web-vorlagen/build.py               schreibt arena/web/*.html (atomar)
    python3 tools/web-vorlagen/build.py --pruefen     schreibt nichts, meldet nur, ob arena/web/*.html aktuell ist
    python3 tools/web-vorlagen/build.py --ziel DIR    schreibt nach DIR statt nach arena/web/
"""
import os
import re
import sys

HIER = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HIER))
ZIEL = os.path.join(REPO, "arena", "web")
SPIELE = ("ninja", "flappy", "auto")


def lies(name):
    with open(os.path.join(HIER, name), encoding="utf-8") as f:
        return f.read()


def baue(spiel):
    ui = lies("party_ui.js").rstrip("\n")
    css = lies("party_ui.css").rstrip("\n")
    level = lies("ninja_level.js")
    s = lies(f"{spiel}.tpl.html").replace("@@CSS@@", css).replace("@@UI@@", ui).replace("@@LEVEL@@", level)
    if "@@" in s:
        sys.exit(f"{spiel}: Platzhalter uebrig")
    if re.search(r"https?://|\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b|<script src|<link", s):
        sys.exit(f"{spiel}: externe URL/IP gefunden - die Spiele muessen ohne Internet laufen")
    return s


def main():
    args = sys.argv[1:]
    pruefen = "--pruefen" in args
    ziel_dir = args[args.index("--ziel") + 1] if "--ziel" in args[:-1] else ZIEL
    veraltet = 0
    for spiel in SPIELE:
        s = baue(spiel)
        ziel = os.path.join(ziel_dir, f"{spiel}.html")
        if pruefen:
            try:
                with open(ziel, encoding="utf-8", newline="") as f:
                    gleich = f.read() == s
            except OSError:
                gleich = False
            print(f"{spiel}.html", "aktuell" if gleich else "WEICHT AB (neu bauen: python3 tools/web-vorlagen/build.py)")
            veraltet += not gleich
            continue
        os.makedirs(ziel_dir, exist_ok=True)
        tmp = ziel + ".tmp"
        with open(tmp, "w", encoding="utf-8", newline="\n") as f:
            f.write(s)
        os.replace(tmp, ziel)
        print(f"{spiel}.html", len(s), "Bytes ->", ziel)
    return 1 if veraltet else 0


if __name__ == "__main__":
    sys.exit(main())
