# extras – die Einzelspiele vom Projektanfang

Bevor es PiArena gab, sind diese Spiele für **eine** Platine entstanden. Sie laufen
unabhängig vom Hauptspiel. Gestartet wird immer aus diesem Ordner:

```bash
cd ~/pi-arena/extras
```

| Datei | Was es ist | Starten |
|---|---|---|
| `ledarcade.py` | **LED-Arcade:** Menü mit Lauflicht-Stopp, Pac-Man 1D, Simon, Reaktions-Duell (2 Spieler: Links gegen Rechts) und PAC-PI. Punkte werden binär auf den LEDs angezeigt. Bedienbar per Platine, Tastatur (`a` `d` `Leertaste`, `q` = Ende) oder Handy (`http://<IP>:8080`). | `python3 ledarcade.py` (Menü), `python3 ledarcade.py 2` (direkt Spiel 2), `--sim` ohne Platine |
| `turbo.py` | **TURBO-BLITZ:** Maulwurf-Blitz (passenden Taster drücken, bevor die LED ausgeht), Reaktion (Zeit binär + als Ton), Synth (3 Taster = 3 Töne). Braucht `ledarcade.py`. | `python3 turbo.py`, `python3 turbo.py 1` (direkt Modus 1), `--sim`, `--selbsttest` |
| `pacpi.py` | **PAC-PI:** Pac-Man am Monitor. LEDs zeigen Fortschritt, Power-Zeit und Leben, der Buzzer spielt den Soundtrack. Pfeiltasten/WASD, Handy-Steuerkreuz oder Taster (links/rechts = abbiegen, Mitte = umdrehen). `F` Vollbild, `M` Musik, `P` Pause, `Esc` zurück. Braucht `ledarcade.py` und pygame. | `python3 pacpi.py` (oder im LED-Arcade-Menü), `--fenster`, `--sim --selbsttest` |
| `chiptune.py` | Baustein, kein Spiel: erzeugt 8-Bit-Musik für den Monitor-Lautsprecher (HDMI). Braucht `python3-numpy`. | wird von `pacpi.py` geladen |
| `anmeldung.py` | **Klassen-Anmeldung:** sammelt Namen am Host-Pi in einer Live-Liste (Browser `http://<HOST>:8090/`). Jede/r meldet sich am eigenen Pi per Fenster oder Terminal an und setzt dabei selbst das Einverständnis-Häkchen. | Host: `python3 anmeldung.py --server`. Schüler-Pi: der Befehl, den der Server anzeigt (`curl -s http://<HOST>:8090/anmelden.py -o anmelden.py && python3 anmelden.py`). Die Host-IP trägt der Server selbst ein; sonst `python3 anmelden.py <HOST-IP>` oder `GAME_HOST=<HOST-IP>` |

**Pins:** `ledarcade.py`, `turbo.py` und `pacpi.py` verwenden standardmäßig dieselbe Platine wie
PiArena (LEDs GPIO 4, 17, 27, 22, 5, 6, 13, 19, 26, 21 · Taster links 18, Mitte 23, rechts 24 ·
passiver Buzzer 25). Eine andere Platine? `python3 ledarcade.py finden` probiert die Pins der Reihe
nach durch und speichert das Ergebnis in `pins.json`.

> `python3 ledarcade.py autostart` richtet einen **systemweiten** Autostart ein (braucht `sudo`,
> schreibt nach `/etc/systemd/system`). Ausschalten: `sudo systemctl disable --now ledarcade`.
> Für PiArena ist stattdessen `./install.sh --autostart` gedacht.

Die Anmeldeliste `anmeldungen.json` entsteht beim ersten Anmelden in diesem Ordner. Sie wird von Git
ignoriert, also nie mit hochgeladen. Nach dem Unterricht löschen.
