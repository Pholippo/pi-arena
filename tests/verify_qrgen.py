#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Pruefung von party/qrgen.py.

Immer (nur Standardbibliothek): Groesse, Finder-Muster, Timing-Linien, Determinismus.
Zusaetzlich, wenn installiert: PNG rendern + mit OpenCV (cv2) bzw. pyzbar dekodieren
und mit der Referenz-Bibliothek "qrcode" vergleichen. Fehlt etwas davon, wird dieser
Teil sauber uebersprungen - qrgen.py selbst braucht keine Zusatz-Pakete.

Aufruf:  python3 tests/verify_qrgen.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "party"))

import qrgen  # noqa: E402

try:
    import numpy as np
    from PIL import Image
    HAVE_BILD = True
except Exception:
    HAVE_BILD = False

try:
    import cv2
    HAVE_CV2 = HAVE_BILD
except Exception:
    HAVE_CV2 = False

try:
    from pyzbar.pyzbar import decode as zbar_decode
    HAVE_ZBAR = HAVE_BILD
except Exception:
    HAVE_ZBAR = False

try:
    import qrcode as refqr
    HAVE_REF = True
except Exception:
    HAVE_REF = False

TESTS = [
    "A",
    "http://192.168.1.50:8081",
    "http://192.168.1.50:8081/lobby?pi=01",
    "https://arcade.local:8081/join?code=ABCD-1234-XY",
    "Gruesse ae oe ue ss @#%&/ 123",
    "x" * 100,  # lang -> hohe Version
]


def finder_ok(m, r0, c0):
    """7x7-Finder-Muster an (r0, c0): schwarzer Rand, weisser Ring, 3x3 schwarzer Kern."""
    for r in range(7):
        for c in range(7):
            rand = r in (0, 6) or c in (0, 6)
            kern = 2 <= r <= 4 and 2 <= c <= 4
            soll = 1 if (rand or kern) else 0
            if m[r0 + r][c0 + c] != soll:
                return False
    return True


def struktur(text):
    """Pruefungen ohne Zusatz-Pakete. -> Liste von Fehlern."""
    m = qrgen.qr_matrix(text)
    n = len(m)
    f = []
    if any(len(z) != n for z in m):
        f.append("Matrix nicht quadratisch")
    if (n - 17) % 4 or not 21 <= n <= 41:
        f.append(f"Groesse {n} passt zu keiner Version 1-6")
    for r0, c0 in ((0, 0), (0, n - 7), (n - 7, 0)):
        if not finder_ok(m, r0, c0):
            f.append(f"Finder-Muster bei {r0},{c0} kaputt")
    for i in range(8, n - 8):  # Timing-Linien abwechselnd schwarz/weiss
        if m[6][i] != (i + 1) % 2 or m[i][6] != (i + 1) % 2:
            f.append("Timing-Linie kaputt")
            break
    if qrgen.qr_matrix(text) != m:
        f.append("nicht deterministisch")
    return m, f


def png(matrix, pfad, scale=10, quiet=4):
    size = len(matrix)
    img = np.full((size + 2 * quiet, size + 2 * quiet), 255, dtype=np.uint8)
    for r in range(size):
        for c in range(size):
            if matrix[r][c]:
                img[r + quiet][c + quiet] = 0
    Image.fromarray(np.kron(img, np.ones((scale, scale), dtype=np.uint8))).save(pfad)
    return pfad


def main():
    out = tempfile.mkdtemp(prefix="qrgen_test_")
    print(f"Zusatz-Pakete: numpy+PIL={'ja' if HAVE_BILD else 'nein'}  cv2={'ja' if HAVE_CV2 else 'nein'}  "
          f"pyzbar={'ja' if HAVE_ZBAR else 'nein'}  qrcode={'ja' if HAVE_REF else 'nein'}")
    if not (HAVE_CV2 or HAVE_ZBAR):
        print("-> Dekodier-Test uebersprungen (cv2/pyzbar fehlt), nur Struktur-Pruefung.")
    print("=" * 78)
    alle_ok = True
    for i, t in enumerate(TESTS):
        m, fehler = struktur(t)
        version = (len(m) - 17) // 4
        info = ""
        if HAVE_CV2 or HAVE_ZBAR:
            pfad = png(m, os.path.join(out, f"qr_{i}.png"))
            gelesen = []
            if HAVE_CV2:
                gelesen.append(cv2.QRCodeDetector().detectAndDecode(cv2.imread(pfad, cv2.IMREAD_GRAYSCALE))[0])
            if HAVE_ZBAR:
                res = zbar_decode(Image.open(pfad))
                gelesen.append(res[0].data.decode("utf-8") if res else None)
            if t not in gelesen:
                fehler.append(f"nicht dekodierbar (gelesen: {gelesen!r})")
            info += " dekodiert ok" if t in gelesen else ""
        if HAVE_REF:
            q = refqr.QRCode(error_correction=refqr.constants.ERROR_CORRECT_L, border=0)
            q.add_data(t)
            q.make(fit=True)
            info += f" | Referenz V{q.version}" + (" gleich" if q.version == version else " ANDERS")
        alle_ok = alle_ok and not fehler
        anzeige = t if len(t) <= 45 else t[:42] + "..."
        print(f"[{'OK ' if not fehler else 'FEHLER'}] V{version} {len(m)}x{len(m)} len={len(t):3d}{info}  {anzeige!r}")
        for f in fehler:
            print("       ", f)
    print("=" * 78)
    print("QRGEN", "OK" if alle_ok else "FEHLER", f"(Bilder: {out})" if (HAVE_CV2 or HAVE_ZBAR) else "")
    return 0 if alle_ok else 1


if __name__ == "__main__":
    sys.exit(main())
