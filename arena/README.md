# arena/ – welche Datei macht was?

Alle Programme von PiArena liegen in diesem Ordner. Gestartet wird nur **`host.py`** (am Pi mit Monitor)
und **`spieler.py`** (an jedem Schüler-Pi, normalerweise per `curl http://<HOST-IP>:8081/j | python3`).

| Datei | Was drin steht |
|---|---|
| `host.py` | **Startprogramm des Hosts.** Liest die Start-Optionen (`--fenster`, `--nur`, `--sim` …) und startet alles. |
| `einstellungen.py` | Rundenzahl, Siegpunkte, Dauer der Browser-Runden und **`DEAKTIVIERT`** (Spiele, die gerade nicht mitspielen). |
| `minispiele.py` | **Die Taster-Minispiele** (`spiel_*`) und die Tabelle `SPIELE`. Hier baust du eigene Spiele. Beispiel: `spiel_morse`. |
| `spieler.py` | Programm für jeden Schüler-Pi: Platine (`Brett`: LEDs, Taster, Buzzer, GPIO-Pins), Verbindung zum Host, Browser öffnen. |
| `ablauf.py` | Spielablauf ohne Grafik: Lobby → Ansage → Runde → Auswertung → Sieger, Punkte, Moderator-Taster. |
| `monitor.py` | Das Bild am Monitor/Beamer (pygame), Demo-Bots, Live-GPIO-Schaltbild, Farben der Spiele (`SPIEL_FARBE`). |
| `webserver.py` | Netzwerk (Port 8081): Anfragen der Pis und Handys, Download `/j`, Handy-Seite, Live-Bild `/live`. |
| `browserspiele.py` | Server für die Browser-Spiele (Port 8082). Startet der Host selbst mit. |
| `selbsttest.py` | Spielt eine ganze Partie ohne Menschen durch (`python3 arena/host.py --selbsttest --sim`). |
| `qrgen.py` | Erzeugt den QR-Code für die Lobby (ohne Zusatz-Pakete). |
| `web/` | Die Browser-Spiele `ninja.html`, `flappy.html`, `auto.html` (gebaut aus `tools/web-vorlagen/`) und die Handy-Seite `handy.html`. |

## Du willst …

| … | Datei |
|---|---|
| ein eigenes Taster-Spiel bauen | `minispiele.py` (Vorlage `spiel_morse`), dann in `einstellungen.py` aus `DEAKTIVIERT` nehmen |
| dein Spiel sofort testen | `python3 arena/host.py --fenster --nur morse` (Pfeil links = Bots, Leertaste = Start) |
| ein Spiel aus den Runden nehmen | `einstellungen.py` → Namen in `DEAKTIVIERT` eintragen |
| mehr/weniger Runden oder Punkte zum Sieg | `einstellungen.py` → `MAX_RUNDEN`, `ZIEL_PUNKTE` (oder `--runden`, `--ziel`) |
| die Farbe eines Spiels am Monitor ändern | `monitor.py` → `SPIEL_FARBE` |
| andere GPIO-Pins für LEDs/Taster/Buzzer | `spieler.py` → `LED_PINS`, `TASTER`, `BUZZER_PIN` |
| einen Ton oder eine Melodie ändern | `minispiele.py` → `T_SUPER`, `T_FEHL`, `FANFARE` … |
| ein Browser-Spiel ändern | `tools/web-vorlagen/` und danach `python3 tools/web-vorlagen/build.py` (siehe `MITMACHEN.md`) |
