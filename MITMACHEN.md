# Mitmachen – MEGA-PARTY weiterentwickeln

Du willst ein eigenes Minispiel einbauen, einen Fehler beheben oder ein neues Browser-Spiel schreiben?
Super. Diese Seite erklärt, wie das Programm aufgebaut ist und wie du deine Änderung sauber einreichst.

## Aufbau

Drei Programme arbeiten zusammen. Alle liegen in `party/`:

```text
                          Monitor / Beamer
                                │ HDMI
 ┌──────────────────────────────┴──────────────────────────────┐
 │  HOST-PI                                                     │
 │                                                              │
 │  mega.py  (Port 8081, HTTP)          webspiele.py (Port 8082)│
 │  - Lobby, Ansage, Wertung, Grafik    - NINJA / FLAPPY / AUTO │
 │  - Show = Spielablauf (Zustände)     - Party = Positionen    │
 │  - liefert mega_client.py aus (/j)   - liefert *.html aus    │
 │  - eigene Platine = Moderator   ──── POST /spiel /start ───► │
 │                                 ◄─── GET /state (alle 0,5 s) │
 │  UDP-Ruf "MEGA-PARTY 8081" jede Sekunde an Port 8082 (UDP)   │
 └───────▲───────────────────▲──────────────────────▲───────────┘
         │ /join /state /act │ /join /state /act     │ /join /upd /state
         │ (alle 0,3 s)      │                       │ (alle 0,1 s)
 ┌───────┴────────┐  ┌───────┴─────────┐   ┌─────────┴──────────────┐
 │ SCHUELER-PI    │  │ HANDY           │   │ CHROMIUM am Schueler-Pi│
 │ mega_client.py │  │ web_client.html │   │ / Handy-iframe / Laptop│
 │ Platine: LEDs, │  │ = virtuelle     │   │ ninja.html, flappy.html│
 │ Taster, Buzzer │  │   Platine       │   │ auto.html              │
 └────────────────┘  └─────────────────┘   └────────────────────────┘
```

Wichtige Grundidee: **Jedes Minispiel läuft komplett auf dem eigenen Pi.** Der Host schickt nur „Runde
X, Spiel Y, Start in Z Sekunden, Zufalls-Seed S". Weil alle denselben Seed bekommen, blitzen und piepen
alle Boards gleich. Gemessen wird lokal (keine Netzwerk-Verzögerung), am Ende schickt der Client nur
das fertige Ergebnis. Der Host sortiert und vergibt Punkte.

| Datei | Wichtigste Teile |
|---|---|
| `party/mega_client.py` | `Brett` (Platine: `zeige`, `warte`, `ton`, `pause`), die Minispiele `spiel_*`, die Tabelle `SPIELE`, `Client` (Verbindung + LED-Anzeige), `Browser` (öffnet Chromium in Browser-Runden) |
| `party/mega.py` | `Show` (Spielablauf: lobby → ansage → laeuft → auswertung → sieger), `starte_web` (HTTP-Server 8081), `App` (Monitor-Grafik, Bots, Live-GPIO), `selbsttest` |
| `party/webspiele.py` | `Party` (Spieler, Phasen lobby → countdown → spiel → ende), HTTP-Server 8082, `SPIELE` |
| `party/*.html` | Browser-Spiele, Handy-Seite. Reines HTML + JavaScript, keine Bibliotheken. `ninja/flappy/auto.html` werden aus `tools/web-vorlagen/` gebaut (siehe unten) |
| `party/qrgen.py` | QR-Code-Generator ohne Zusatz-Pakete |

## Protokoll

Alles ist einfaches HTTP mit Formular-Daten (`application/x-www-form-urlencoded`) und JSON-Antworten.
Du kannst jede Anfrage mit `curl` ausprobieren.

### Host, Port 8081 (`mega.py`)

| Anfrage | Zweck |
|---|---|
| `GET /j` | liefert `mega_client.py`, die Host-Adressen sind schon in `STANDARD_HOSTS` eingetragen. Darum reicht `curl http://HOST:8081/j \| python3` |
| `POST /join` `name, art, kennung` | beitreten. `art` = `pi`, `web` (Handy), `bot`, `sim`. Gleiche `kennung` (Hostname/Name) = derselbe Spieler kommt zurück, Punkte bleiben. Antwort `{"id", "name"}` |
| `GET /state?id=…` | Zustand für diesen Spieler: `phase` (`lobby`, `countdown`, `round`, `result`, `done`), `round`, `round_name`, `instruction`, `your_score`, `board` (Rangliste), `server_ms`, `deadline_ms`. Pi-Clients bekommen zusätzlich `pi` mit `runde` = `{rid, nr, spiel, seed, param, finale, start_in}`. Unbekannte id → `{"neu": 1}` = neu beitreten |
| `POST /act?id=…` | Pi: `action=answer, rid, value, ok, text` = fertiges Ergebnis. Handy: `action=tap/press/answer, value` |
| `GET /` | Handy-Seite (`web_client.html`) |
| `GET /live` | Live-Bild des Monitors (lädt laufend `/tv.jpg`) |
| `GET /tv.jpg` | aktuelles Monitorbild als JPEG |
| `GET /tv` | Weiterleitung auf das Browser-Spiel (Port 8082) |

Zusätzlich ruft der Host jede Sekunde per **UDP-Broadcast** `MEGA-PARTY 8081` an UDP-Port 8082. So
findet ein Client den Host auch ohne eingetragene Adresse (`--suche`).

### Browser-Spiele, Port 8082 (`webspiele.py`)

| Anfrage | Zweck |
|---|---|
| `GET /` | HTML des **gerade aktiven** Spiels. `?name=Max` → tritt automatisch bei (so öffnet der Client Chromium) |
| `GET /tv` | dasselbe Spiel als Zuschauer-Ansicht mit START-Knopf |
| `POST /join` `name, id` | beitreten, mit alter `id` = gleicher Spieler nach Neuladen. Antwort `{"id"}` |
| `POST /upd` `id, x, y, lebt, ziel` | eigene Position hoch (10× pro Sekunde), Antwort = ganzer Zustand |
| `GET /state` | `phase` (`lobby`, `countdown`, `spiel`, `ende`), `rest`, `seed`, `spieler` (sortiert: Zielzeit, dann Weite), `runde_s`, `spiel` |
| `POST /spiel` `name` | aktives Spiel wechseln (`ninja`, `flappy`, `auto`), zurück in die Lobby |
| `POST /start` `dauer` | Countdown (5 s) + Runde starten |
| `POST /lobby` | Runde abbrechen, zurück in die Lobby |

## Ein neues Taster-Minigame einbauen

Alles passiert in **`party/mega_client.py`**. Der Host liest die Tabelle `SPIELE` von dort und nimmt
dein Spiel automatisch in die Rotation auf.

**1. Spiel-Funktion schreiben** (bei den anderen `spiel_*`-Funktionen):

```python
def spiel_morse(b, p, rng):
    """Beispiel: Die LEDs zeigen 1-5 Blitze, druecke MITTE genauso oft."""
    n = rng.randint(1, 5)          # rng ist auf ALLEN Boards gleich (gleicher Seed)
    for _ in range(n):
        b.zeige([1] * N)
        b.ton(kurz("A5", 0.1))
        b.pause(0.3)
        b.zeige([0] * N)
        b.pause(0.3)
    b.leeren()                     # alte Tastendruecke wegwerfen
    if b.bot:                      # Bots fuer Tests und Demo
        for i in range(n):
            b.bot_drueck("mitte", 0.3 + i * 0.3 * b.skill)
    zahl, t0 = 0, time.monotonic()
    while time.monotonic() - t0 < 4:
        e = b.warte(0.1)           # -> (taste, zeitpunkt) oder None
        if e and e[0] == "mitte":
            zahl += 1
            b.zeige(balken(zahl))
    ok = zahl == n
    b.ton(T_SUPER if ok else T_FEHL)
    return {"wert": zahl, "ok": ok, "text": f"{zahl} von {n}"}
```

- Das Ergebnis ist immer `{"wert": Zahl, "ok": gültig?, "text": für den Monitor}`.
- Nur `b.warte`/`b.pause` zum Warten verwenden, nie `time.sleep`. Sonst funktioniert „Runde
  überspringen" nicht.
- Zufall, der bei allen gleich sein soll → `rng`. Zufall nur für Bots → `b.bot`.

**2. In die Tabelle `SPIELE` eintragen:**

```python
    "morse": {"handy": False, "name": "MORSE-ZAEHLER", "fn": spiel_morse, "besser": "hoch", "trost": 0,
              "dauer": 12, "kurz": "Zaehl die Blitze und druecke MITTE genauso oft!",
              "tasten": ("", "DRUECKEN", "")},
```

- `besser`: `"hoch"` = größter `wert` gewinnt, `"tief"` = kleinster.
- `trost`: Punkte für alle anderen mit `ok`.
- `dauer`: Sekunden, nach denen der Host spätestens auswertet.
- `handy`: `False`, außer du baust auch die Handy-Wertung in `mega.py` (`Show._web_aktion` und `Show._text`).
- `tasten`: Beschriftung der 3 Taster in der Ansage am Monitor.

**3. Farbe am Monitor** (optional): in `party/mega.py` bei `SPIEL_FARBE` `"morse": (R, G, B)` ergänzen.

**4. Testen:** `python3 party/mega.py --sim --fenster`, `LINKS` (Pfeil links) für Demo-Bots, dann
`Leertaste`. Mit `A S D` drückst du die eigenen Taster. Danach `python3 tests/run_all.py`.

Spiele, die der Host gerade nicht spielen soll, stehen in `DEAKTIVIERT` in `party/mega.py`. Der Code
bleibt dabei erhalten.

## Browser-Spiele ändern: Vorlagen in `tools/web-vorlagen/`

> **Der PARTY-UI-Block steht identisch in allen drei Spielen** (Namensschild „DU", Rangliste,
> Countdown, gemeinsame Optik). Geändert wird er **nur** über `tools/web-vorlagen/build.py`,
> nie direkt in `party/*.html`, sonst ist die Änderung beim nächsten Bauen weg.

| Datei in `tools/web-vorlagen/` | Inhalt |
|---|---|
| `party_ui.js`, `party_ui.css` | gemeinsamer Teil für alle drei Spiele |
| `ninja.tpl.html`, `flappy.tpl.html`, `auto.tpl.html` | das eigentliche Spiel mit den Platzhaltern `@@CSS@@`, `@@UI@@` (und `@@LEVEL@@`) |
| `ninja_level.js` | Level-Generator + Physik von NINJA-RACE (genau diesen Code prüft `tests/ninja_qa.mjs`) |
| `build.py` | setzt alles zusammen und schreibt `party/ninja.html`, `party/flappy.html`, `party/auto.html` |

```bash
python3 tools/web-vorlagen/build.py            # party/*.html neu bauen
python3 tools/web-vorlagen/build.py --pruefen  # nur prüfen, ob party/*.html zu den Vorlagen passt
```

`build.py` bricht ab, wenn ein Platzhalter übrig ist oder eine externe Adresse (URL, IP, `<script src>`)
im Spiel steht: Die Spiele müssen ohne Internet laufen. Der Test `vorlagen` in `run_all.py` meldet,
wenn jemand `party/*.html` direkt geändert hat.

## Ein neues Browser-Spiel einbauen

**1. Vorlage anlegen:** `tools/web-vorlagen/flappy.tpl.html` nach `tools/web-vorlagen/meinspiel.tpl.html`
kopieren (das kürzeste Spiel, gute Vorlage), `"meinspiel"` in `SPIELE` in `build.py` ergänzen und
bauen. Das ergibt `party/meinspiel.html` mit dem gemeinsamen PARTY-UI-Block. Was jedes Spiel können muss:

- `?name=` lesen (`QNAME`) und dann ohne Formular beitreten (`POST /join`), damit der Client das
  Spiel fertig öffnen kann.
- 10× pro Sekunde `POST /upd` mit `id, x, y, lebt` (und `ziel` = Sekunden, falls es ein Ziel gibt).
  `x` ist die Strecke: Der Server zählt `best` = größtes `x`, die Anzeige ist `x / 10` in „m".
- **Neu laden, wenn der Host umschaltet:** in der Netz-Schleife
  `if (r.spiel && r.spiel !== 'meinspiel') { location.reload(); return; }`
- Die Phasen `lobby` (üben), `countdown`, `spiel`, `ende` anzeigen. Bei `spiel` die eigene Figur zurücksetzen.
- Die Welt aus `seed` erzeugen, damit alle dieselbe Strecke haben.
- `/tv` (Zuschauer) erkennen: `location.pathname.startsWith('/tv')`, dort nur zuschauen.
- Die anderen Spieler als „Geister" mit Namen zeichnen (`r.spieler`, jede/r hat eine `farbe`).

**2. Im Server eintragen:** in `party/webspiele.py` den Namen in `SPIELE` ergänzen:
`SPIELE = ("ninja", "flappy", "auto", "meinspiel")`

**3. Beim Host eintragen:** in `party/mega.py` in `WEB_SPIELE` z. B.
`"meinspiel": {"name": "MEIN-SPIEL", "kurz": "Im Browser: ..."}` und eine Farbe in `SPIEL_FARBE`.
Der Host nimmt das Spiel nur in die Rotation, wenn `party/meinspiel.html` existiert.

**4. Testen:** `python3 party/webspiele.py --spiel meinspiel` starten und `http://127.0.0.1:8082`
im Browser öffnen (zweiter Tab = zweiter Spieler, `/tv` = Zuschauer mit START-Knopf). Danach
`python3 tests/run_all.py`.

## Tests

```bash
python3 tests/run_all.py            # alle Tests, am Ende eine Zusammenfassung
python3 tests/run_all.py webspiele  # nur einzelne: webspiele mega ninja auto webtest qrgen vorlagen
```

| Test | Prüft |
|---|---|
| `webspiele` | `webspiele.py --selbsttest`: Server + 8 simulierte Spieler über echtes HTTP |
| `mega` | `mega.py --selbsttest --sim`: Host + 5 echte Client-Prozesse (über `/j` geladen) + Handy + Bot spielen eine ganze Partie, mit Reconnect, Last-Test (30 Clients) und kaputten Anfragen |
| `ninja` | `tests/ninja_qa.mjs`: baut 30 Level aus der echten `ninja.html` und lässt einen A*-Bot jedes Level lösen (Node.js) |
| `auto` | `tests/auto_test.cjs`: JavaScript-Syntax von `auto.html`, dann für jede Schwierigkeitsstufe und gemischte Stufen: jede Verkehrs-Reihe hat eine erreichbare freie Spur, auch bei Höchsttempo + Turbo (Node.js) |
| `webtest` | `tests/webtest.py`: Browser-Runde Ende-zu-Ende, Namens-Zuordnung und Punkte |
| `qrgen` | `tests/verify_qrgen.py`: QR-Codes ohne Zusatz-Pakete prüfen. Mit OpenCV/pyzbar/qrcode zusätzlich echt dekodieren |
| `vorlagen` | `tools/web-vorlagen/build.py --pruefen`: `party/*.html` passt genau zu den Vorlagen |

Die Tests laufen auch am Laptop (Windows/Linux/macOS), ohne Platine und ohne Monitor. Die Ports 8081
und 8082 müssen frei sein. Node.js ist optional: Ohne Node werden `ninja` und `auto` übersprungen.

**Hilfswerkzeug:** `tests/cdp_shot.mjs` macht Screenshots einer Spielseite über das Chrome-DevTools-Protokoll
(Anleitung oben in der Datei). Damit sind die Bilder in `docs/bilder/` entstanden.

## Code-Stil

- **Einfach vor clever.** Die Lehrer-Rückmeldung war deutlich: „Das kapiert sonst keiner." Lieber
  drei klare Zeilen als eine schlaue.
- **Deutsche Namen und Kommentare**, wie im restlichen Code. In Texten für Monitor und Terminal
  `ae oe ue ss` statt Umlauten (nicht jede Schrift am Pi hat sie).
- **Keine neuen Pakete.** Standardbibliothek, pygame und gpiozero. Die Schüler-Pis bekommen den Client
  per `curl`, dort kann nichts installiert werden.
- Fehler nie still verschlucken: Mindestens eine Meldung ausgeben. Ein kaputter Pin oder eine
  kaputte Anfrage darf das Spiel aber nicht beenden.
- Dateien atomar schreiben (in `.tmp` schreiben, dann `os.replace`).
- Neue Logik bekommt einen Test oder einen Fall im `selbsttest`.

## Ideen-Liste (aus dem Feedback in der Werkstätte)

- **Code einfacher machen:** `mega.py` in kleinere Dateien teilen (Ablauf, Grafik, Server).
- **Schwierigkeit:** Browser-Spiele mit der Zeit schwerer machen (mehr Autos, schneller, engere Röhren).
- **„Wer ist wer?":** die eigene Figur in den Browser-Spielen noch deutlicher hervorheben.
- **Überspringen in Browser-Runden** und **Flackern** an verschiedenen Pi-Modellen testen und melden.
- Neue Taster-Spiele, z. B. Morse-Zähler, Binär-Quiz, „Hau den Lukas" mit dem Tap-Tempo.
- Team-Modus (zwei Hälften der Klasse gegeneinander).
- Lautstärke/Buzzer-aus-Schalter für ruhige Stunden.

Hast du eine Idee, aber keine Zeit? Leg auf GitHub ein **Issue** an.

## Git-Workflow für Klassen

So arbeiten mehrere Gruppen gleichzeitig, ohne sich gegenseitig etwas kaputt zu machen:

1. **Fork:** Auf GitHub oben rechts **Fork** klicken. Jetzt hast du (oder deine Gruppe) eine eigene Kopie.
2. **Klonen:**
   ```bash
   git clone https://github.com/<DEIN-NAME>/raspi-klassen-party.git
   cd raspi-klassen-party
   git remote add upstream https://github.com/Pholippo/raspi-klassen-party.git
   ```
3. **Branch** pro Änderung, mit sprechendem Namen:
   ```bash
   git switch -c spiel-morse
   ```
4. Ändern, testen (`python3 tests/run_all.py`), dann speichern:
   ```bash
   git add party/mega_client.py
   git commit -m "Neues Minispiel MORSE-ZAEHLER"
   git push -u origin spiel-morse
   ```
5. **Pull Request:** GitHub zeigt danach „Compare & pull request". Kurz beschreiben, *was* du geändert
   hast und *wie* du es getestet hast. Die Lehrkraft oder das Projekt-Team schaut drüber und übernimmt es.
6. **Auf dem neuesten Stand bleiben:**
   ```bash
   git switch main
   git pull upstream main
   git push
   ```

Tipps: Eine Änderung pro Pull Request. Keine fremden Namen, Fotos oder Passwörter einchecken.
`anmeldungen.json`, Logs und Backups ignoriert Git schon von selbst (`.gitignore`).
