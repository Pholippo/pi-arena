# Anleitung für Lehrkräfte – MEGA-PARTY im Unterricht

Diese Anleitung führt Schritt für Schritt von der leeren SD-Karte bis zur fertigen Partie mit der ganzen
Klasse. Programmierkenntnisse braucht es keine. Befehle in grauen Kästen werden genau so im **Terminal**
des Raspberry Pi eingetippt (Terminal öffnen: Symbol `>_` oben in der Leiste oder `Strg + Alt + T`).

**Inhalt**

1. [Was man braucht](#1-was-man-braucht)
2. [Die Platine](#2-die-platine)
3. [Projekt auf den Host-Pi holen](#3-projekt-auf-den-host-pi-holen)
4. [Einrichten mit install.sh](#4-einrichten-mit-installsh)
5. [Host starten](#5-host-starten)
6. [Schülerinnen und Schüler treten bei](#6-schülerinnen-und-schüler-treten-bei)
7. [Moderation mit den 3 Tastern](#7-moderation-mit-den-3-tastern)
8. [Ablauf einer Partie](#8-ablauf-einer-partie)
9. [Die Minispiele](#9-die-minispiele)
10. [Browser-Runden](#10-browser-runden)
11. [Nach einem Neustart des Pi](#11-nach-einem-neustart-des-pi)
12. [Wenn etwas nicht geht](#12-wenn-etwas-nicht-geht)
13. [Datenschutz und Einverständnis](#13-datenschutz-und-einverständnis)

---

## 1. Was man braucht

**Für den Host (einmal, vorne beim Lehrertisch):**

- Raspberry Pi 4 oder 5 mit Netzteil
- microSD-Karte (ab 16 GB) mit Raspberry Pi OS **mit Desktop** (Bookworm oder Trixie)
- Monitor oder Beamer über HDMI, Tastatur (Maus hilft beim Einrichten)
- eine Platine wie unten beschrieben (empfohlen: Damit moderiert man ohne Tastatur)
- Netzwerk: dasselbe WLAN oder LAN wie die Schüler-Pis

**Für jede Schülerin und jeden Schüler:**

- eigener Raspberry Pi mit Raspberry Pi OS mit Desktop, Monitor und **Tastatur**
  (die Tastatur braucht man für die Browser-Runden)
- die gleiche Platine (10 LEDs, 3 Taster, Buzzer)
- **oder** einfach ein Handy mit Browser (ohne Platine, spielt die handytauglichen Runden mit)

**Software:** Python 3.11+, pygame, gpiozero und Chromium sind bei Raspberry Pi OS mit Desktop
normalerweise schon dabei. `install.sh` prüft das und installiert Fehlendes nach.

## 2. Die Platine

Jede Platine hat **10 LEDs**, **3 Taster** und einen **passiven Buzzer** (ein Piezo-Summer, der Töne in
verschiedenen Höhen spielen kann). Alle Teile hängen zwischen einem GPIO-Pin und Masse (GND).

### Pin-Tabelle

| Bauteil | GPIO | Pin an der 40er-Leiste | Anschluss |
|---|---|---|---|
| LED 1 (ganz links) | GPIO 4 | 7 | GPIO → Vorwiderstand → LED → GND |
| LED 2 | GPIO 17 | 11 | wie oben |
| LED 3 | GPIO 27 | 13 | wie oben |
| LED 4 | GPIO 22 | 15 | wie oben |
| LED 5 | GPIO 5 | 29 | wie oben |
| LED 6 | GPIO 6 | 31 | wie oben |
| LED 7 | GPIO 13 | 33 | wie oben |
| LED 8 | GPIO 19 | 35 | wie oben |
| LED 9 | GPIO 26 | 37 | wie oben |
| LED 10 (ganz rechts) | GPIO 21 | 40 | wie oben |
| Taster LINKS | GPIO 18 | 12 | GPIO → Taster → GND (Pull-up im Pi) |
| Taster MITTE | GPIO 23 | 16 | wie oben |
| Taster RECHTS | GPIO 24 | 18 | wie oben |
| Buzzer (passiv) | GPIO 25 | 22 | GPIO → Buzzer (+), Buzzer (−) → GND |
| Masse | GND | z. B. 6, 9, 14, 20, 25, 30, 34, 39 | gemeinsame Masse-Leitung |

- **Vorwiderstand** je LED: 220 Ω bis 330 Ω (begrenzt den Strom, sonst gehen LED oder Pin kaputt).
- **Taster** brauchen keinen eigenen Widerstand: Das Programm schaltet den internen Pull-up-Widerstand
  ein. Nicht gedrückt = HIGH, gedrückt = LOW.
- **Buzzer** muss ein *passiver* sein (ohne eingebaute Elektronik), sonst gibt es nur einen Ton.
  Das Programm erzeugt die Tonhöhe per PWM.

### Schaltbild (vereinfacht)

```text
 Raspberry Pi                          Platine
 ────────────                          ───────
                     220..330 Ω         LED
 GPIO  4 (Pin  7) ───[████]──────────►|─────┐
 GPIO 17 (Pin 11) ───[████]──────────►|─────┤
 GPIO 27 (Pin 13) ───[████]──────────►|─────┤
 GPIO 22 (Pin 15) ───[████]──────────►|─────┤
 GPIO  5 (Pin 29) ───[████]──────────►|─────┤
 GPIO  6 (Pin 31) ───[████]──────────►|─────┤   10 LEDs
 GPIO 13 (Pin 33) ───[████]──────────►|─────┤   (Anode zum Widerstand,
 GPIO 19 (Pin 35) ───[████]──────────►|─────┤    Kathode = kurzes Bein
 GPIO 26 (Pin 37) ───[████]──────────►|─────┤    zur Masse)
 GPIO 21 (Pin 40) ───[████]──────────►|─────┤
                                            │
                       Taster               │
 GPIO 18 (Pin 12) ─────o  o─────────────────┤   LINKS
 GPIO 23 (Pin 16) ─────o  o─────────────────┤   MITTE
 GPIO 24 (Pin 18) ─────o  o─────────────────┤   RECHTS
                                            │
                      Buzzer (passiv)       │
 GPIO 25 (Pin 22) ─────(+)  (−)─────────────┤
                                            │
 GND     (Pin  6) ──────────────────────────┘   gemeinsame Masse
```

**Schnell-Test der Platine:** Den Host im Fenster starten (siehe Abschnitt 5). Rechts unten am Monitor
zeigt das Feld **LIVE-GPIO** jeden Taster (HIGH/LOW) und jede LED in Echtzeit.

## 3. Projekt auf den Host-Pi holen

### SD-Karte vorbereiten (falls noch nicht geschehen)

1. Am Laptop den **Raspberry Pi Imager** installieren (raspberrypi.com/software).
2. Gerät wählen (Pi 4 / Pi 5) → Betriebssystem **Raspberry Pi OS (64-bit)** (die Variante *mit* Desktop).
3. Bei „Einstellungen bearbeiten": Benutzername + Passwort, WLAN (Schul-WLAN) und Zeitzone eintragen.
   Einen **eindeutigen Hostnamen** vergeben, z. B. `klasse-pi-01`. Der Hostname ist später der
   Standard-Spielername.
4. Schreiben, Karte in den Pi, starten. Beim ersten Start die Fragen am Bildschirm beantworten.

### Variante A: mit `git clone` (Pi hat Internet)

```bash
cd ~
git clone https://github.com/Pholippo/raspi-klassen-party.git
cd raspi-klassen-party
```

Wenn ihr mit einem eigenen Fork arbeitet, statt `Pholippo` euren GitHub-Namen einsetzen.
Später auf den neuesten Stand bringen: `cd ~/raspi-klassen-party && git pull`

### Variante B: mit USB-Stick (kein Internet am Pi)

1. Am Laptop auf der GitHub-Seite **Code → Download ZIP** klicken, ZIP auf den USB-Stick kopieren.
2. Stick am Pi anstecken, ZIP im Dateimanager in den **Home-Ordner** entpacken.
3. Den Ordner in `raspi-klassen-party` umbenennen (GitHub hängt oft `-main` an).
4. Im Terminal:

```bash
cd ~/raspi-klassen-party
bash install.sh
```

(`bash` davor, weil beim Kopieren vom USB-Stick die „ausführbar"-Markierung verloren gehen kann.
`install.sh` setzt sie danach wieder.)

> **Die Schüler-Pis brauchen nichts davon.** Sie bekommen ihr Programm beim Beitreten direkt vom Host.

## 4. Einrichten mit install.sh

```bash
cd ~/raspi-klassen-party
./install.sh
```

Das Skript prüft Python, pygame, gpiozero, Chromium und curl. Fehlt etwas, installiert es die Pakete
mit `sudo apt install` und fragt dabei nach dem Passwort des Pi. Es ändert sonst nichts am System und
darf beliebig oft ausgeführt werden.

**Optional – Autostart:** Soll der Host nach jedem Einschalten von selbst starten (praktisch, wenn der
Pi fix am Beamer hängt):

```bash
./install.sh --autostart        # einschalten
./install.sh --kein-autostart   # wieder ausschalten
```

## 5. Host starten

```bash
cd ~/raspi-klassen-party
./start.sh
```

Der Monitor zeigt die **Lobby** im Vollbild: den Beitritts-Befehl für die Schüler-Pis, einen QR-Code
für Handys, die Liste der Minispiele, die Rangliste und das Live-Schaltbild. Die Browser-Spiele
(Port 8082) startet der Host automatisch mit.

Nützliche Varianten:

| Befehl | Wirkung |
|---|---|
| `./start.sh` | normal: Host spielt mit (eigene Platine), Browser-Runden an |
| `./start.sh --zuschauer` | Host spielt nicht mit, die Taster sind nur zum Moderieren |
| `./start.sh --ohne-web` | nur Taster-Spiele, keine Browser-Runden |
| `./start.sh --runden 6` | höchstens 6 Runden (Standard 10, die letzte ist das Finale) |
| `./start.sh --ziel 8` | wer 8 Punkte hat, gewinnt (Standard 10 = alle LEDs) |
| `./start.sh --web-dauer 60` | Browser-Runden dauern 60 s (Standard 90) |
| `./start.sh --name Frau_Mayer` | eigener Spielername (Standard: Hostname des Pi) |
| `./start.sh --fenster` | im Fenster statt Vollbild (zum Ausprobieren) |

**Beenden:** `ESC` in der Lobby (während einer Partie springt `ESC` zurück in die Lobby) oder in einem
zweiten Terminal `./stop.sh`.

## 6. Schülerinnen und Schüler treten bei

### Mit dem eigenen Pi und der Platine

Jede/r tippt am **eigenen** Pi im Terminal genau den Befehl ab, der am Monitor steht, zum Beispiel:

```bash
curl http://192.168.1.50:8081/j | python3
```

- Danach fragt das Programm „Wie heisst du?". Namen eintippen, Enter. Leer lassen = Hostname des Pi.
  Spitznamen sind erlaubt.
- Ein kurzes Melodie-Signal bestätigt die Verbindung, der Name erscheint rechts in der Rangliste.
- **LED-Signale:** LED 1 und LED 10 blinken abwechselnd = sucht den Host. Ein Licht wandert über die
  LEDs = verbunden, wartet auf den Start. Später zeigen die LEDs den Punktestand.
- Beenden: `Strg + C` im Terminal.

Stehen am Monitor zwei Befehle (WLAN und KABEL): den nehmen, der zum Netz des eigenen Pi passt.

### Mit dem Handy

QR-Code am Monitor scannen (oder die angezeigte Adresse `http://…:8081/` im Handy-Browser öffnen),
Namen eingeben, fertig. Das Handy ist eine virtuelle Platine mit großen Knöpfen. Runden, die echte LEDs
brauchen (Lauflicht-Stopp), werden ausgelassen, solange Handy-Spieler dabei sind.

## 7. Moderation mit den 3 Tastern

Die Taster der **Host-Platine** steuern die Show, solange gerade keine Runde läuft. Spielt der Host mit,
gehören die Taster während einer Taster-Runde dem Spiel.

| Wann | LINKS | MITTE | RECHTS |
|---|---|---|---|
| Lobby | Demo-Bots an/aus (zum Vorführen ohne Klasse) | **Partie starten** | – |
| Ansage / Runde läuft | – | – | **Runde überspringen** |
| Ergebnis | – | sofort weiter | – |
| Siegerehrung | – | neue Partie (alle bleiben verbunden) | – |

Dasselbe geht mit der Tastatur am Host: `Leertaste`/`Enter` = MITTE, `Pfeil links` = LINKS,
`Pfeil rechts` oder `N` = RECHTS, `ESC` = zurück in die Lobby bzw. Programm beenden.

## 8. Ablauf einer Partie

1. **Lobby:** Alle treten bei. Sind alle in der Rangliste, MITTE drücken.
2. **Ansage:** Der Monitor zeigt das nächste Minispiel, die Bedeutung der 3 Taster und die Punkte.
   Ein Countdown läuft, die Buzzer piepen die letzten 3 Sekunden mit.
3. **Runde:** Alle spielen gleichzeitig am eigenen Board. Der Monitor zeigt, wer schon fertig ist.
4. **Ergebnis:** Platz 1/2/3 bekommt **3/2/1 Punkte**, im **Finale** (letzte Runde) doppelt. Die neuen
   Punkte blinken auf den LEDs. Nach 10 Sekunden geht es von selbst weiter (MITTE = sofort).
5. Das wiederholt sich, jede Runde mit einem anderen Spiel, bis jemand **10 Punkte** hat oder alle
   Runden gespielt sind.
6. **Siegerehrung** mit Podest und Fanfare. MITTE startet eine neue Partie.

Eine Partie mit 10 Runden dauert etwa 10 bis 15 Minuten (Browser-Runden sind länger als Taster-Runden).

## 9. Die Minispiele

**Taster-Runden** (auf der Platine, gemessen direkt am eigenen Pi):

| Spiel | So geht's | Taster | Wer gewinnt |
|---|---|---|---|
| **REAKTIONS-BLITZ** | Alle LEDs blitzen auf → sofort drücken. 3 Versuche. Zu früh gedrückt = +1000 ms Strafe | MITTE | kleinste Durchschnittszeit |
| **LAUFLICHT-STOPP** | Ein Licht läuft hin und her, genau in der Mitte (LED 5/6) stoppen. 3×, jedes Mal schneller | MITTE | geringste Abweichung |
| **TAP-MARATHON** | 10 Sekunden so oft drücken wie möglich, die LEDs füllen sich | alle 3 | meiste Drücker |
| **ZÄHL DIE PIEPS** | Der Buzzer piept mehrmals. Mitzählen, dann Zahl einstellen (die LEDs zeigen sie an) | RECHTS +1, LINKS −1, MITTE fertig | richtig und am schnellsten; alle anderen Richtigen bekommen 1 Trostpunkt |

**Browser-Runden** (am Bildschirm, alle in derselben Welt):

| Spiel | So geht's | Steuerung | Wer gewinnt |
|---|---|---|---|
| **NINJA-RACE** | Jump'n'Run durch ein Level bis zum Ziel | `◀ ▶` oder `A D` laufen, `Leertaste` / `▲` / `W` springen | schnellste Zielzeit, sonst weiteste Strecke |
| **FLAPPY-PARTY** | Vogel durch die Röhren steuern. Abgestürzt? Nach 1 s geht's weiter, der beste Versuch zählt | `Leertaste`, Klick oder Tippen | weiteste Strecke |
| **AUTO-PARTY** | Auf der Autobahn dem Verkehr ausweichen, es wird immer schneller | `◀ ▶` oder `A D` Spur wechseln, `▲` / `W` Turbo | weiteste Strecke |

Handy-Spieler können REAKTIONS-BLITZ, TAP-MARATHON, ZÄHL DIE PIEPS und alle Browser-Runden mitspielen.

## 10. Browser-Runden

Bei NINJA-RACE, FLAPPY-PARTY und AUTO-PARTY spielen alle im Browser:

- **Schüler-Pi:** Chromium geht während der Ansage **von selbst im Vollbild** auf, der Name ist schon
  eingetragen. Gespielt wird mit der **Tastatur** des Pi. Nach der Runde schließt sich das Fenster
  wieder und die LEDs zeigen den Punktestand.
- **Handy:** Die Handy-Seite blendet das Spiel automatisch ein, gesteuert wird per Touch.
- **Laptop / anderer PC:** Die am Monitor angezeigte Adresse `http://…:8082` öffnen und **genau den
  Namen** eingeben, der in der Rangliste steht. Nur dann werden die Punkte zugeordnet.
- Der Host spielt mit seinem eigenen Namen ebenfalls mit.
- Am Monitor sieht man die Live-Rangliste und hinter jedem Browser-Namen den zugeordneten MEGA-Namen.
- Eine Browser-Runde dauert standardmäßig 90 Sekunden. Mit RECHTS lässt sie sich überspringen.

## 11. Nach einem Neustart des Pi

- **Host-Pi:** Terminal öffnen, `cd ~/raspi-klassen-party && ./start.sh`. Mit eingerichtetem Autostart
  (Abschnitt 4) startet der Host von selbst, sobald der Desktop da ist.
- **Schüler-Pi:** den Beitritts-Befehl noch einmal eintippen (Pfeil-nach-oben-Taste im Terminal holt
  ihn zurück). Mit **gleichem Namen** bleiben die Punkte erhalten.
- **Host neu gestartet, Schüler-Programme liefen weiter:** Die Clients verbinden sich von selbst neu,
  sobald der Host wieder da ist. Die Punkte beginnen dann aber bei 0, weil der Host sie nur im
  Arbeitsspeicher hält.

## 12. Wenn etwas nicht geht

**„LED GPIO … nicht nutzbar" / „GPIO busy"**
Ein anderes Programm benutzt die Pins, meist ein noch laufendes Programm in **Thonny**. In Thonny auf
**Stop** klicken oder Thonny schließen, dann den Beitritts-Befehl neu starten. Auch ein zweites
Spiel-Programm im Hintergrund blockiert die Pins. Abhilfe: `./stop.sh` am Host oder `pkill -f mega_client`
am Schüler-Pi. Das Programm läuft mit den freien Pins weiter, die belegten werden übersprungen.

**„Webserver aus (Port 8081 …)" oder „Address already in use"**
Der Host läuft schon (z. B. per Autostart oder in einem zweiten Terminal). `./stop.sh` beendet alle
Teile, danach `./start.sh`. Kontrolle: `ss -ltnp | grep 808` zeigt, wer die Ports 8081/8082 belegt.

**Bildschirm flackert in den Browser-Runden**
Chromium wird am Schüler-Pi absichtlich ohne Grafikbeschleunigung gestartet (`--disable-gpu`), weil
es am Pi 5 sonst flackern kann. Flackert es trotzdem: andere Browserfenster schließen, Client einmal
neu starten (`Strg + C`, Befehl wiederholen). **LEDs flackern**: Wackelkontakt an der Platine oder
gemeinsame Masse prüfen. Ein kurzes Flackern beim Start ist normal.

**WLAN oder Kabel?**
Host und Schüler-Pis müssen im **gleichen Netz** sein. Viele Schul-WLANs sperren Verbindungen zwischen
Geräten (Client-Isolation). Dann hilft nur LAN-Kabel oder die Schul-IT. Hat der Host WLAN *und* Kabel,
zeigt er beide Befehle an. Jede/r nimmt den passenden.

**Host wird nicht gefunden (LED 1 und 10 blinken weiter)**
1. Am Host im Terminal `hostname -I` eingeben, das ist seine Adresse.
2. Am Schüler-Pi testen: `ping <Adresse>` (mit `Strg + C` beenden). Keine Antwort → Netzproblem (siehe oben).
3. Adresse fest vorgeben:
   `curl http://<Adresse>:8081/j | python3 - --host <Adresse>`

**Kein Ton**
- *Buzzer:* Muss ein **passiver** Buzzer an GPIO 25 sein, Plus- und Minus-Seite beachten. Meldet das
  Programm „Buzzer GPIO 25 nicht nutzbar", ist der Pin belegt (siehe Thonny oben).
- *Musik über den Monitor (HDMI):* braucht das Paket `python3-numpy`. Außerdem am Pi rechts oben mit
  Rechtsklick auf das Lautsprecher-Symbol den HDMI-Ausgang wählen.
- *Browser-Spiele:* Manche Browser spielen Ton erst nach dem ersten Klick oder Tastendruck ins Spiel.

**Alle Tests auf einmal (zum Prüfen nach Änderungen):** `python3 tests/run_all.py`

## 13. Datenschutz und Einverständnis

- **Jede/r startet das Programm am eigenen Pi selbst.** Der Host meldet sich nie auf fremden Pis an und
  steuert sie nicht fern. Er antwortet nur auf Anfragen der Programme, die die Schüler selbst gestartet
  haben. Wer nicht mitspielen will, startet einfach nichts. Beenden geht jederzeit mit `Strg + C`.
- **Welche Daten?** Nur der selbst gewählte Spielname (Spitznamen sind ausdrücklich erlaubt), der
  Hostname des Pi zum Wiedererkennen und die Punkte. Alles liegt **nur im Arbeitsspeicher des Hosts**
  und ist beim Beenden weg. Es gibt kein Konto, keine Cloud und keine Verbindung ins Internet.
- **Handys:** Es wird keine App installiert. Die Seite läuft im Browser und speichert höchstens den
  Namen lokal am Handy, damit man nach einem Neuladen gleich weiterspielt.
- **Sichtbarkeit:** Namen und Punkte stehen am Monitor bzw. Beamer und unter `http://<Host>:8081/live`
  für alle im selben Netz. Das bitte vorher kurz ansagen.
- Fotos oder Videos von der Partie (z. B. für die Schulwebsite) brauchen wie immer das Einverständnis
  der Abgebildeten.
