#!/usr/bin/env python3
"""Klassen-Anmeldung fuer das LED-Game (Namen der Mitspieler am Host-Pi sammeln).

Zwei Rollen in EINER Datei:
  * Server (laeuft auf dem Host-Pi):   python3 anmeldung.py --server
      - sammelt die Namen, zeigt die Live-Liste am Monitor/Terminal
      - liefert sich selbst aus, damit Mitschueler nur EINEN Befehl brauchen
  * Popup  (jede/r Mitschueler am eigenen Pi):
      curl -s http://<HOST>:8090/anmelden.py -o anmelden.py && python3 anmelden.py
      - Fenster "Wie heisst du?" -> Name wird an den Server geschickt
      - ohne Desktop: fragt im Terminal nach
      - Host-Adresse: traegt der Server beim Ausliefern selbst ein; sonst
        python3 anmelden.py <HOST-IP>   oder   GAME_HOST=<HOST-IP> python3 anmelden.py

Kein Login auf fremde Geraete: jede/r startet das Popup selbst.
"""
import json
import os
import socket
import sys
import time
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = 8090
HIER = os.path.dirname(os.path.abspath(__file__))
LISTE = os.path.join(HIER, "anmeldungen.json")
STANDARD_HOST = ""  # traegt der Server beim Ausliefern (/anmelden.py) mit seiner IP ein


def eigene_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))  # sendet nichts, waehlt nur die Schnittstelle mit Standard-Route
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        try:
            return socket.gethostbyname(socket.gethostname())
        except OSError:
            return "127.0.0.1"


# ---------------------------------------------------------------- Server

def lade():
    try:
        with open(LISTE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return []


def speichere(eintraege):
    tmp = LISTE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(eintraege, f, ensure_ascii=False, indent=2)
    os.replace(tmp, LISTE)  # atomar


SELF = None  # Quelltext dieser Datei, zum Ausliefern


def server():
    host_ip = eigene_ip()
    befehl = f"curl -s http://{host_ip}:{PORT}/anmelden.py -o anmelden.py && python3 anmelden.py"

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, body, typ="text/plain; charset=utf-8", code=200):
            daten = body.encode("utf-8") if isinstance(body, str) else body
            self.send_response(code)
            self.send_header("Content-Type", typ)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Content-Length", str(len(daten)))
            self.end_headers()
            try:
                self.wfile.write(daten)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def do_GET(self):
            pfad = urllib.parse.urlparse(self.path)
            q = urllib.parse.parse_qs(pfad.query)
            if pfad.path in ("/anmelden.py", "/client.py", "/a"):
                self._send(SELF.replace('STANDARD_HOST = ""', f'STANDARD_HOST = "{host_ip}"', 1),
                           "text/x-python; charset=utf-8")
            elif pfad.path == "/reg":
                name = (q.get("name", [""])[0]).strip()[:24]
                pi = (q.get("pi", [""])[0]).strip()[:24]
                ok = (q.get("ok", ["0"])[0]) in ("1", "true", "ja")
                ip = self.client_address[0]
                if name:
                    eintraege = [e for e in lade() if e.get("ip") != ip]
                    eintraege.append({"name": name, "pi": pi, "ip": ip,
                                      "start_ok": ok, "zeit": time.strftime("%H:%M:%S")})
                    speichere(eintraege)
                    haken = "OK Fernstart" if ok else "KEIN Fernstart"
                    print(f"  [+] {name}  (Pi {pi or '?'}, {ip}) [{haken}]  -> {len(eintraege)} angemeldet")
                self._send("ok")
            elif pfad.path in ("/liste", "/l"):
                self._send(json.dumps(lade(), ensure_ascii=False), "application/json")
            else:
                zeilen = "".join(
                    f"<li>{'✅' if e.get('start_ok') else '▫️'} <b>{e['name']}</b> "
                    f"<small>Pi {e.get('pi') or '?'} · {e['ip']}</small></li>"
                    for e in lade())
                self._send(f"""<!doctype html><meta charset=utf-8>
<title>Anmeldung</title><style>body{{font-family:system-ui;background:#0b0f14;color:#e8eef5;
text-align:center;padding:20px}}code{{background:#161b22;padding:8px 12px;border-radius:8px;display:inline-block}}
li{{list-style:none;font-size:20px;margin:6px}}small{{opacity:.6}}</style>
<h1>LED-Game Anmeldung</h1><p>Am eigenen Pi im Terminal eingeben:</p>
<code>{befehl}</code><h2>{len(lade())} dabei</h2><ul>{zeilen}</ul>
<script>setTimeout(()=>location.reload(),2000)</script>""", "text/html; charset=utf-8")

    try:
        srv = ThreadingHTTPServer(("0.0.0.0", PORT), H)
    except OSError as e:
        print(f"Port {PORT} belegt: {e}")
        return
    ips = os.popen("hostname -I 2>/dev/null").read().split()
    print("=" * 56)
    print("  KLASSEN-ANMELDUNG laeuft")
    print("  Mitschueler tippen an IHREM Pi:")
    print("  " + befehl)
    for ip in ips:
        if "." in ip:
            print(f"    (Alternative Adresse: http://{ip}:{PORT}/anmelden.py )")
    print(f"  Live-Liste im Browser: http://{host_ip}:{PORT}/")
    print("=" * 56)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nAngemeldet:", ", ".join(e["name"] for e in lade()) or "niemand")


# ---------------------------------------------------------------- Popup (Client)

def finde_host():
    for a in sys.argv[1:]:
        if a.replace(".", "").isdigit():
            return a
    # Reihenfolge: Argument > Umgebungsvariable GAME_HOST > vom Server eingetragen
    host = os.environ.get("GAME_HOST", "").strip() or STANDARD_HOST
    if not host:
        sys.exit("Host-IP fehlt: python3 anmelden.py <HOST-IP>   (oder GAME_HOST=<HOST-IP> setzen)")
    return host


CONSENT = ("Ich bin einverstanden, dass mein Spiel-Client beim Mitspielen vom "
           "Host-Pi aus ueber das WLAN gestartet und gesteuert wird (Spielrunden). "
           "Es wird NICHTS anderes auf meinem Pi gestartet oder veraendert.")


def schicke(host, name, ok=False):
    pi = socket.gethostname()
    url = f"http://{host}:{PORT}/reg?" + urllib.parse.urlencode(
        {"name": name, "pi": pi, "ok": "1" if ok else "0"})
    with urllib.request.urlopen(url, timeout=5) as r:
        return r.read()


def popup(host):
    name_vorschlag = socket.gethostname()
    try:
        import tkinter as tk
        from tkinter import messagebox
    except Exception:
        tk = None
    if tk and (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        root = tk.Tk()
        root.title("LED-Game")
        root.attributes("-topmost", True)
        root.configure(bg="#0b0f14")
        try:
            root.attributes("-fullscreen", False)
            root.geometry("540x380+200+150")
        except tk.TclError:
            pass
        tk.Label(root, text="LED-GAME", fg="#ff3b3b", bg="#0b0f14",
                 font=("DejaVu Sans", 30, "bold")).pack(pady=(28, 4))
        tk.Label(root, text="Wie heisst du?", fg="#e8eef5", bg="#0b0f14",
                 font=("DejaVu Sans", 18)).pack(pady=6)
        eingabe = tk.Entry(root, font=("DejaVu Sans", 22), justify="center", width=16)
        eingabe.insert(0, name_vorschlag)
        eingabe.pack(pady=10)
        eingabe.focus_set()
        eingabe.select_range(0, "end")
        zustimmung = tk.IntVar(value=0)
        cb = tk.Checkbutton(root, variable=zustimmung, bg="#0b0f14", fg="#cdd7e1",
                            selectcolor="#0b0f14", activebackground="#0b0f14",
                            activeforeground="#fff", font=("DejaVu Sans", 11),
                            wraplength=470, justify="left",
                            text="Ich erlaube, dass der Host mein Spiel ueber das WLAN startet/steuert.")
        cb.pack(pady=(4, 2))
        status = tk.Label(root, text="", fg="#2ea043", bg="#0b0f14", font=("DejaVu Sans", 13))
        status.pack()

        def senden(_=None):
            name = eingabe.get().strip()[:24]
            if not name:
                status.config(text="Bitte Namen eingeben.", fg="#ff3b3b")
                return
            if not zustimmung.get():
                status.config(text="Bitte das Haekchen setzen, um mitzuspielen.", fg="#ff3b3b")
                return
            try:
                schicke(host, name, ok=True)
                status.config(text=f"Angemeldet als {name}  -  bis gleich!", fg="#2ea043")
                root.after(1300, root.destroy)
            except Exception as e:
                status.config(text=f"Keine Verbindung zu {host}: {e}", fg="#ff3b3b")

        tk.Button(root, text="Mitspielen!", font=("DejaVu Sans", 20, "bold"),
                  bg="#1f6feb", fg="#fff", command=senden).pack(pady=8)
        eingabe.bind("<Return>", senden)
        root.mainloop()
    else:
        # kein Desktop -> Terminal
        name = input(f"LED-Game - wie heisst du? [{name_vorschlag}] ").strip() or name_vorschlag
        print("\n" + CONSENT)
        antwort = input("Einverstanden? Mit 'j' bestaetigen: ").strip().lower()
        ok = antwort in ("j", "ja", "y", "yes")
        if not ok:
            print("Ohne Zustimmung keine Teilnahme. Tschuess!")
            return
        try:
            schicke(host, name[:24], ok=True)
            print(f"Angemeldet als {name}. Viel Spass!")
        except Exception as e:
            print(f"Keine Verbindung zum Host {host}: {e}")


def main():
    if "--server" in sys.argv:
        server()
    else:
        popup(finde_host())


if __name__ == "__main__":
    try:
        with open(os.path.abspath(__file__), encoding="utf-8") as f:
            SELF = f.read()
    except OSError:
        SELF = "# Quelltext nicht lesbar"
    main()
