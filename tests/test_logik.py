#!/usr/bin/env python3
"""Unit-Tests fuer die Spiel-Logik - ohne Platine, ohne Monitor, ohne pygame.

Aufruf:  python3 -m unittest discover -s tests -p "test_*.py"     (oder: python3 tests/run_all.py logik)

Die Hardware wird nicht gebraucht: Brett(sim=True) laeuft ohne gpiozero, die Server lauschen auf einem
freien Zufalls-Port (Port 0), damit sie nicht mit einem laufenden Host auf 8081/8082 kollidieren.
"""
import http.client
import json
import os
import socket
import sys
import threading
import time
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "arena"))
sys.path.insert(0, os.path.join(REPO, "extras"))

import einstellungen as E  # noqa: E402

E.WEB_BASIS = None  # keine Browser-Runden, kein Netz zu 8082
import ablauf  # noqa: E402
import browserspiele  # noqa: E402
import minispiele  # noqa: E402
import spieler  # noqa: E402
import webserver  # noqa: E402


def roh_post(port, pfad, header_laenge, body=b""):
    """POST mit frei gewaehltem Content-Length-Header (auch kaputt/negativ). -> (status, antwort)"""
    s = socket.create_connection(("127.0.0.1", port), timeout=5)
    try:
        s.sendall(f"POST {pfad} HTTP/1.1\r\nHost: x\r\nContent-Length: {header_laenge}\r\n"
                  f"Connection: close\r\n\r\n".encode() + body)
        if not body:
            s.shutdown(socket.SHUT_WR)  # ohne Body: Schreibseite zu (mit Body bleibt sie absichtlich offen)
        daten = b""
        while True:
            teil = s.recv(4096)
            if not teil:
                break
            daten += teil
    finally:
        s.close()
    kopf = daten.split(b"\r\n", 1)[0].decode()
    return int(kopf.split()[1]), daten


# ---------------------------------------------------------------- minispiele.py: Helfer

class TestToene(unittest.TestCase):
    def test_frequenz(self):
        self.assertAlmostEqual(minispiele.frequenz("A4"), 440.0)
        self.assertAlmostEqual(minispiele.frequenz("A5"), 880.0)
        self.assertIsNone(minispiele.frequenz("-"))
        self.assertIsNone(minispiele.frequenz(""))

    def test_lied(self):
        self.assertEqual(minispiele.lied("C5 E5:2 -", 0.1), [("C5", 0.1), ("E5", 0.2), ("-", 0.1)])

    def test_alle_toene_spielbar(self):
        for name in ("T_KLICK", "T_ZAEHL", "T_LOS", "T_TREFFER", "T_SUPER", "T_FEHL", "T_FOUL", "FANFARE"):
            for note, dauer in getattr(minispiele, name):
                minispiele.frequenz(note)  # darf nicht werfen
                self.assertGreater(dauer, 0)

    def test_balken(self):
        self.assertEqual(sum(minispiele.balken(3)), 3)
        self.assertEqual(sum(minispiele.balken(0)), 0)
        self.assertEqual(sum(minispiele.balken(99)), minispiele.N)

    def test_spieltabelle_vollstaendig(self):
        for key, info in minispiele.SPIELE.items():
            for feld in ("handy", "name", "fn", "besser", "trost", "dauer", "kurz", "tasten"):
                self.assertIn(feld, info, f"{key}: {feld} fehlt")
            self.assertIn(info["besser"], ("hoch", "tief"))
            self.assertEqual(len(info["tasten"]), 3)


# ---------------------------------------------------------------- spieler.py: Brett ohne Hardware

class TestBrett(unittest.TestCase):
    def setUp(self):
        self.b = spieler.Brett(sim=True)

    def test_zeige_kuerzt_und_fuellt(self):
        self.b.zeige([1, 1])
        self.assertEqual(self.b.zustand, [1, 1] + [0] * (minispiele.N - 2))
        self.b.zeige([1] * 20)
        self.assertEqual(self.b.zustand, [1] * minispiele.N)

    def test_druck_und_warte(self):
        self.b.druck("mitte")
        k, t = self.b.warte(0.5)
        self.assertEqual(k, "mitte")
        self.assertIsNone(self.b.warte(0.05))

    def test_abbruch(self):
        self.b.abbruch.set()
        with self.assertRaises(spieler.Abbruch):
            self.b.warte(1.0)

    def test_ton_log_begrenzt(self):
        for _ in range(100):
            self.b.ton(minispiele.T_KLICK)
        self.assertLessEqual(len(self.b.ton_log), 30)


class FalscheVerbindung:
    def join(self, *a):
        return {"id": "x", "name": "Test"}

    def poll(self, sid):
        return {"phase": "lobby"}

    def ergebnis(self, *a):
        return {"ok": True}


class TestClientAbbruchRace(unittest.TestCase):
    """Regression: ein Abbruch, der noch fuer die vorige Runde gesetzt wurde, beendete die naechste Runde sofort."""

    def test_altes_abbruch_signal_beendet_neue_runde_nicht(self):
        def spiel_kurz(b, p, rng):
            b.pause(0.05)  # wirft Abbruch, falls das alte Signal noch steht
            return {"wert": 1, "ok": True, "text": "fertig"}

        minispiele_alt = dict(spieler.SPIELE)
        spieler.SPIELE["_test"] = dict(minispiele.SPIELE["morse"], fn=spiel_kurz)
        try:
            b = spieler.Brett(sim=True)
            c = spieler.Client(b, FalscheVerbindung(), "Test", log=False)
            b.abbruch.set()  # "uebrig geblieben" von der vorigen Runde
            c._spiele({"rid": 7, "nr": 1, "spiel": "_test", "seed": 1, "param": {}, "start_in": 0.0})
            self.assertIsNotNone(c.offen, "Runde wurde faelschlich abgebrochen")
            self.assertEqual(c.offen[0], 7)
            self.assertEqual(c.offen[1]["text"], "fertig")
        finally:
            spieler.SPIELE.clear()
            spieler.SPIELE.update(minispiele_alt)


# ---------------------------------------------------------------- ablauf.py: Show (Spielregeln)

class TestShow(unittest.TestCase):
    def setUp(self):
        self.show = ablauf.Show(schnell=True, max_runden=3, ziel=10)

    def test_join_name_wird_bereinigt_und_eindeutig(self):
        a = self.show.api_join("Max<script>", "pi", "pi1/max")
        b = self.show.api_join("max", "pi", "pi2/max")
        self.assertEqual(a["name"], "Maxscript")
        self.assertEqual(b["name"], "max")
        self.assertEqual(self.show.api_join("MAX", "pi", "pi3")["name"], "MAX2")  # Gross/klein egal -> Nummer dran

    def test_rejoin_mit_kennung_behaelt_id(self):
        a = self.show.api_join("Anna", "pi", "pi1/anna")
        self.assertEqual(self.show.api_join("Anna", "pi", "pi1/anna")["id"], a["id"])

    def test_spiel_voll(self):
        for i in range(ablauf.MAX_SPIELER):
            self.show.api_join(f"S{i}", "web", f"k{i}")
        self.assertIn("fehler", self.show.api_join("zuviel", "web", "neu"))

    def _runde_mit(self, ergebnisse, spiel="tap", finale=False):
        ids = []
        for i, (wert, ok) in enumerate(ergebnisse):
            ids.append(self.show.api_join(f"P{i}", "pi", f"k{i}")["id"])
        self.show.runde = {"rid": 1, "nr": 1, "spiel": spiel, "seed": 1, "param": {}, "finale": finale,
                           "start": time.monotonic(), "dauer": 10}
        self.show.zustand = "laeuft"
        for sid, (wert, ok) in zip(ids, ergebnisse):
            self.show.api_ergebnis(sid, 1, float(wert), ok, "t")
        self.show.werte_aus()
        return [self.show.spieler[s] for s in ids]

    def test_punkte_platz_123(self):  # tap: hoch ist besser
        sp = self._runde_mit([(10, True), (30, True), (20, True), (5, True)])
        self.assertEqual(sp[1].punkte, 3)
        self.assertEqual(sp[2].punkte, 2)
        self.assertEqual(sp[0].punkte, 1)
        self.assertEqual(sp[3].punkte, 0)  # tap hat trost 0

    def test_tief_ist_besser_und_ungueltig_bekommt_nichts(self):  # reaktion: tief ist besser
        sp = self._runde_mit([(300, True), (200, True), (100, False)], spiel="reaktion")
        self.assertEqual(sp[1].punkte, 3)
        self.assertEqual(sp[0].punkte, 2)
        self.assertEqual(sp[2].punkte, 0)

    def test_finale_doppelt(self):
        sp = self._runde_mit([(5, True)], finale=True)
        self.assertEqual(sp[0].punkte, 6)

    def test_ergebnis_nan_und_falsche_rid(self):
        sid = self.show.api_join("A", "pi", "a")["id"]
        self.show.runde = {"rid": 5, "nr": 1, "spiel": "tap", "seed": 1, "param": {}, "finale": False,
                           "start": time.monotonic(), "dauer": 10}
        self.show.zustand = "laeuft"
        with self.assertRaises(ValueError):
            self.show.api_ergebnis(sid, 5, float("nan"), True, "x")
        self.show.api_ergebnis(sid, 4, 1.0, True, "falsche Runde")
        self.assertNotIn(sid, self.show.ergebnisse)
        self.show.api_ergebnis(sid, 5, 1.0, True, "ok\x1b[2J")
        self.assertEqual(self.show.ergebnisse[sid]["text"], "ok[2J")  # Steuerzeichen raus

    def test_moderator_ueberspringen(self):
        self.show.api_join("A", "pi", "a")
        self.show.moderator("mitte")  # Start
        self.assertEqual(self.show.zustand, "ansage")
        self.show.moderator("rechts")  # Ueberspringen
        self.assertEqual(self.show.zustand, "auswertung")
        self.assertTrue(self.show.uebersprungen)

    def test_state_fuer_unbekannte_id(self):
        self.assertEqual(self.show.api_state("gibtsnicht").get("neu"), 1)


class TestWebZuordnung(unittest.TestCase):
    def test_exakt_und_praefix(self):
        sp = {"a": ablauf.Spieler("a", "Anna", "pi", ""), "b": ablauf.Spieler("b", "Bernhard", "pi", "")}
        liste = [{"name": "bernh", "best": 5}, {"name": " ANNA ", "best": 3}, {"name": "Fremd", "best": 9},
                 {"name": "Anna", "best": 0, "ziel": None}]  # nicht gespielt -> raus
        self.assertEqual([sid for sid, _ in ablauf.web_zuordnung(liste, sp)], ["b", "a"])


# ---------------------------------------------------------------- browserspiele.py: Party

class TestParty(unittest.TestCase):
    def test_alte_spieler_werden_vergessen(self):
        p = browserspiele.Party()
        alt = p.join("Alt")
        p.spieler[alt]["gesehen"] -= browserspiele.VERGESSEN_S + 1
        neu = p.join("Neu")
        self.assertNotIn(alt, p.spieler)
        self.assertIn(neu, p.spieler)

    def test_reload_behaelt_id(self):
        p = browserspiele.Party()
        sid = p.join("Max")
        self.assertEqual(p.join("Max2", sid), sid)

    def test_ziel_nur_einmal_und_im_rahmen(self):
        p = browserspiele.Party()
        sid = p.join("Max")
        p.start(30)
        p.phase = "spiel"
        p.update(sid, {"x": "50", "ziel": "999"})
        self.assertIsNone(p.spieler[sid]["ziel"])
        p.update(sid, {"x": "50", "ziel": "12.5"})
        p.update(sid, {"x": "50", "ziel": "3"})
        self.assertEqual(p.spieler[sid]["ziel"], 12.5)


# ---------------------------------------------------------------- HTTP: negativer Content-Length

class FalscheApp:
    def __init__(self):
        self.show = ablauf.Show(schnell=True)

    def client_code(self, adresse=""):
        return "print('hallo')"


class TestHttpRobust(unittest.TestCase):
    def test_webserver_negativer_content_length(self):
        alt = webserver.PORT
        webserver.PORT = 0
        try:
            srv = webserver.starte_web(FalscheApp())
        finally:
            webserver.PORT = alt
        try:
            port = srv.server_address[1]
            t0 = time.monotonic()
            # Vorher: read(-1) wartete bis zum Verbindungsende (Body-Limit 4096 ausgehebelt).
            # Wir schicken einen Body und lassen die Verbindung offen -> mit dem Fix kommt sofort eine Antwort.
            status, _ = roh_post(port, "/join", -1, b"name=Max&art=pi&kennung=k1")
            self.assertLess(time.monotonic() - t0, 3)
            self.assertEqual(status, 200)
            status, _ = roh_post(port, "/join", "abc")
            self.assertEqual(status, 400)
            c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
            c.request("POST", "/join", "name=Lisa&art=web&kennung=x",
                      {"Content-Type": "application/x-www-form-urlencoded"})
            antwort = json.loads(c.getresponse().read())
            self.assertEqual(antwort["name"], "Lisa")
        finally:
            srv.shutdown()
            srv.server_close()

    def test_browserspiele_negativer_content_length(self):
        p = browserspiele.Party()
        srv = browserspiele.starte_server(p, 0)
        try:
            port = srv.server_address[1]
            t0 = time.monotonic()
            status, daten = roh_post(port, "/join", -1, b"name=Max")
            self.assertLess(time.monotonic() - t0, 3)
            self.assertEqual(status, 200)
        finally:
            srv.shutdown()
            srv.server_close()


# ---------------------------------------------------------------- extras/anmeldung.py: Live-Liste

class TestAnmeldungHtml(unittest.TestCase):
    def test_namen_werden_escaped(self):
        import anmeldung
        seite = anmeldung.liste_html([{"name": "<script>alert(1)</script>", "pi": "<b>", "ip": "1.2.3.4",
                                       "start_ok": True}], "curl x")
        self.assertNotIn("<script>alert", seite)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", seite)
        self.assertIn("1 dabei", seite)

    def test_gleichzeitige_anmeldungen_gehen_nicht_verloren(self):
        import tempfile
        import anmeldung
        alt = anmeldung.LISTE
        with tempfile.TemporaryDirectory() as d:
            anmeldung.LISTE = os.path.join(d, "liste.json")
            try:
                def melde(i):
                    with anmeldung.LISTE_LOCK:
                        e = [x for x in anmeldung.lade() if x.get("ip") != f"10.0.0.{i}"]
                        e.append({"name": f"S{i}", "ip": f"10.0.0.{i}"})
                        anmeldung.speichere(e)
                ts = [threading.Thread(target=melde, args=(i,)) for i in range(20)]
                for t in ts:
                    t.start()
                for t in ts:
                    t.join()
                self.assertEqual(len(anmeldung.lade()), 20)
            finally:
                anmeldung.LISTE = alt


if __name__ == "__main__":
    unittest.main()
