#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
qrgen.py - Reiner-Python QR-Code-Generator (nur Standardbibliothek).

Baut QR-Codes im Byte-Modus mit Fehlerkorrektur-Level L, Versionen 1-6,
korrekter Reed-Solomon-Fehlerkorrektur (GF(256)), BCH-Format-Info,
allen Funktionsmustern (Finder, Separator, Timing, Alignment, Dark-Modul)
und sauberer Masken-Auswahl ueber die vier Penalty-Regeln der Spec.

Gedacht fuer das Raspberry-Pi-Schulspiel: eine Lobby-URL wie
"http://192.168.1.50:8081" wird als scannbarer QR-Code auf den Monitor
gebracht. Keine externen Abhaengigkeiten - laeuft direkt auf dem Pi.

Oeffentliche API (andere Module rufen genau das auf):
    qr_matrix(data: str) -> list[list[int]]
        Reine QR-Matrix (NxN), 1 = schwarzes Modul, 0 = weiss.
        OHNE Quiet-Zone - nur die reinen Module.
    qr_text(data: str) -> str
        ASCII-Vorschau (zwei Zeichen pro Modul) zum Testen im Terminal.

CLI:
    python3 qrgen.py "http://192.168.1.50:8081"
    -> druckt die ASCII-Vorschau.
"""

from __future__ import annotations


# ---------------------------------------------------------------------------
# Spec-Tabellen fuer Fehlerkorrektur-Level L, Versionen 1-6
# ---------------------------------------------------------------------------

# Pro Version (Level L): Anzahl EC-Codewoerter pro Block und die Blockgruppen
# als (Anzahl_Bloecke, Daten-Codewoerter_pro_Block).
# Quelle: ISO/IEC 18004, Error-Correction-Characteristics-Tabelle.
#   v1-L: 1x(26,19) ec=7    v2-L: 1x(44,34) ec=10   v3-L: 1x(70,55) ec=15
#   v4-L: 1x(100,80) ec=20  v5-L: 1x(134,108) ec=26 v6-L: 2x(86,68) ec=18
_EC_L = {
    1: {"ec": 7,  "groups": [(1, 19)]},
    2: {"ec": 10, "groups": [(1, 34)]},
    3: {"ec": 15, "groups": [(1, 55)]},
    4: {"ec": 20, "groups": [(1, 80)]},
    5: {"ec": 26, "groups": [(1, 108)]},
    6: {"ec": 18, "groups": [(2, 68)]},
}

# Maximal moegliche Datenbytes im Byte-Modus (Level L) pro Version.
_BYTE_CAP_L = {1: 17, 2: 32, 3: 53, 4: 78, 5: 106, 6: 134}

# Zentren der Alignment-Muster pro Version. Platziert wird nur an
# (x, x)-Kombinationen, die nicht mit den Finder-Mustern kollidieren.
_ALIGN = {1: [], 2: [6, 18], 3: [6, 22], 4: [6, 26], 5: [6, 30], 6: [6, 34]}

# Format-Info: Level L hat die Indikatorbits 0b01.
_ECL_FORMAT_BITS = 0b01

# Maximal unterstuetzte Version.
_MAX_VERSION = 6


# ---------------------------------------------------------------------------
# Galois-Feld GF(256) - Grundlage fuer Reed-Solomon
# Primitives Polynom 0x11d (x^8 + x^4 + x^3 + x^2 + 1), wie in der QR-Spec.
# ---------------------------------------------------------------------------

def _gf_mul(x: int, y: int) -> int:
    """Multiplikation zweier Bytes im GF(256) (ohne Vorab-Log-Tabellen)."""
    z = 0
    for i in range(7, -1, -1):
        # z = z * 2 (mit Reduktion modulo Primpolynom, falls Bit 7 gesetzt)
        z = (z << 1) ^ ((z >> 7) * 0x11D)
        # addiere x, falls das i-te Bit von y gesetzt ist (Addition = XOR)
        z ^= ((y >> i) & 1) * x
    return z & 0xFF


def _rs_generator(degree: int) -> list[int]:
    """Erzeugt das Reed-Solomon-Generatorpolynom vom Grad `degree`.

    Rueckgabe sind die Koeffizienten (ohne den fuehrenden 1-Koeffizienten),
    `result[-1]` ist der Koeffizient zur niedrigsten Potenz.
    """
    result = [0] * degree
    result[-1] = 1  # entspricht dem Polynom "1"
    root = 1  # wird nacheinander 2^0, 2^1, 2^2, ... (Wurzeln des Polynoms)
    for _ in range(degree):
        # multipliziere das bisherige Polynom mit (x - 2^i)
        for j in range(degree):
            result[j] = _gf_mul(result[j], root)
            if j + 1 < degree:
                result[j] ^= result[j + 1]
        root = _gf_mul(root, 0x02)
    return result


def _rs_remainder(data: list[int], generator: list[int]) -> list[int]:
    """Berechnet die EC-Codewoerter (Rest der Polynomdivision)."""
    result = [0] * len(generator)
    for b in data:
        factor = b ^ result.pop(0)  # fuehrendes Codewort herausschieben
        result.append(0)
        for i in range(len(result)):
            result[i] ^= _gf_mul(generator[i], factor)
    return result


# ---------------------------------------------------------------------------
# Datenkodierung (Byte-Modus)
# ---------------------------------------------------------------------------

def _choose_version(num_bytes: int) -> int:
    """Kleinste Version 1-6, in die `num_bytes` Nutzdaten passen (Level L)."""
    for version in range(1, _MAX_VERSION + 1):
        if num_bytes <= _BYTE_CAP_L[version]:
            return version
    raise ValueError(
        f"Daten zu lang: {num_bytes} Bytes passen nicht in Version 1-6 (max "
        f"{_BYTE_CAP_L[_MAX_VERSION]} Bytes bei Level L)."
    )


def _encode_data(data: str, version: int) -> list[int]:
    """Kodiert `data` im Byte-Modus in die vollstaendige Codewort-Folge.

    Enthaelt Modus-Indikator, Zeichenzaehler, Daten, Terminator, Byte-
    Auffuellung sowie die Padding-Bytes 0xEC/0x11 bis zur Kapazitaet.
    """
    payload = data.encode("utf-8")  # UTF-8 deckt Latin/ASCII und URLs sicher ab

    spec = _EC_L[version]
    total_data_cw = sum(count * size for count, size in spec["groups"])

    # Bitstrom als Liste von 0/1 aufbauen.
    bits: list[int] = []

    def put(value: int, length: int) -> None:
        for i in range(length - 1, -1, -1):
            bits.append((value >> i) & 1)

    put(0b0100, 4)             # Modus-Indikator: Byte-Modus
    put(len(payload), 8)       # Zeichenzaehler: 8 Bit fuer Version 1-9
    for byte in payload:
        put(byte, 8)

    # Terminator: bis zu 4 Null-Bits, aber nicht ueber die Kapazitaet hinaus.
    capacity_bits = total_data_cw * 8
    terminator = min(4, capacity_bits - len(bits))
    put(0, terminator)

    # Auf volle Bytegrenze auffuellen.
    if len(bits) % 8 != 0:
        put(0, 8 - (len(bits) % 8))

    # In Codewoerter (Bytes) wandeln.
    codewords = [int("".join(str(b) for b in bits[i:i + 8]), 2)
                 for i in range(0, len(bits), 8)]

    # Mit den Padding-Bytes 0xEC / 0x11 (abwechselnd, beginnend mit 0xEC)
    # auf die volle Datenkapazitaet auffuellen.
    pad = [0xEC, 0x11]
    pad_idx = 0
    while len(codewords) < total_data_cw:
        codewords.append(pad[pad_idx % 2])
        pad_idx += 1

    return codewords


def _structure_codewords(data_cw: list[int], version: int) -> list[int]:
    """Teilt Daten in Bloecke, berechnet EC und verschachtelt beides."""
    spec = _EC_L[version]
    ec_count = spec["ec"]
    generator = _rs_generator(ec_count)

    # Daten-Codewoerter gemaess Gruppen in Bloecke aufteilen.
    blocks: list[list[int]] = []
    pos = 0
    for count, size in spec["groups"]:
        for _ in range(count):
            blocks.append(data_cw[pos:pos + size])
            pos += size

    ec_blocks = [_rs_remainder(block, generator) for block in blocks]

    # Daten-Codewoerter spaltenweise verschachteln.
    result: list[int] = []
    max_data = max(len(b) for b in blocks)
    for i in range(max_data):
        for b in blocks:
            if i < len(b):
                result.append(b[i])
    # EC-Codewoerter spaltenweise verschachteln.
    max_ec = max(len(e) for e in ec_blocks)
    for i in range(max_ec):
        for e in ec_blocks:
            if i < len(e):
                result.append(e[i])

    return result


# ---------------------------------------------------------------------------
# Matrix-Aufbau (Funktionsmuster + Datenplatzierung)
# ---------------------------------------------------------------------------

def _new_matrix(size: int):
    """Leere Matrix plus Begleit-Matrix, die Funktionsmodule markiert."""
    matrix = [[0] * size for _ in range(size)]
    reserved = [[False] * size for _ in range(size)]
    return matrix, reserved


def _place_finder(matrix, reserved, row: int, col: int) -> None:
    """Setzt ein 7x7-Finder-Muster mit Rand an die obere linke Ecke (row,col)."""
    for r in range(-1, 8):
        for c in range(-1, 8):
            rr, cc = row + r, col + c
            if not (0 <= rr < len(matrix) and 0 <= cc < len(matrix)):
                continue
            # Ring aus schwarz/weiss; der 1-Modul-Rand ist der Separator (weiss).
            if 0 <= r <= 6 and 0 <= c <= 6:
                is_dark = (r in (0, 6) or c in (0, 6)
                           or (2 <= r <= 4 and 2 <= c <= 4))
                matrix[rr][cc] = 1 if is_dark else 0
            else:
                matrix[rr][cc] = 0  # Separator
            reserved[rr][cc] = True


def _place_alignment(matrix, reserved, version: int) -> None:
    """Setzt die 5x5-Alignment-Muster (ab Version 2)."""
    centers = _ALIGN[version]
    size = len(matrix)
    for r in centers:
        for c in centers:
            # Kollisionen mit den Finder-Mustern ueberspringen.
            if reserved[r][c]:
                continue
            for dr in range(-2, 3):
                for dc in range(-2, 3):
                    rr, cc = r + dr, c + dc
                    is_dark = (abs(dr) == 2 or abs(dc) == 2
                               or (dr == 0 and dc == 0))
                    matrix[rr][cc] = 1 if is_dark else 0
                    reserved[rr][cc] = True


def _place_timing(matrix, reserved) -> None:
    """Timing-Muster: abwechselnd schwarz/weiss in Zeile 6 und Spalte 6."""
    size = len(matrix)
    for i in range(size):
        if not reserved[6][i]:
            matrix[6][i] = 1 if i % 2 == 0 else 0
            reserved[6][i] = True
        if not reserved[i][6]:
            matrix[i][6] = 1 if i % 2 == 0 else 0
            reserved[i][6] = True


def _reserve_format_areas(reserved, version: int) -> None:
    """Reserviert die Format-Info-Bereiche (werden spaeter beschrieben)."""
    size = len(reserved)
    # rund um das obere linke Finder-Muster
    for i in range(9):
        reserved[8][i] = True
        reserved[i][8] = True
    # rechts (obere rechte Ecke) und unten (untere linke Ecke)
    for i in range(8):
        reserved[8][size - 1 - i] = True
    for i in range(7):
        reserved[size - 1 - i][8] = True
    # Dark-Modul
    reserved[size - 8][8] = True


def _place_data_bits(matrix, reserved, codewords: list[int]) -> None:
    """Platziert den Codewort-Bitstrom im Zickzack (von unten rechts)."""
    size = len(matrix)
    bits: list[int] = []
    for cw in codewords:
        for i in range(7, -1, -1):
            bits.append((cw >> i) & 1)

    idx = 0
    upward = True
    col = size - 1
    while col > 0:
        if col == 6:  # Timing-Spalte ueberspringen
            col -= 1
        for i in range(size):
            row = (size - 1 - i) if upward else i
            for c in (col, col - 1):
                if not reserved[row][c]:
                    # Rest-Bits (ueber die Codewoerter hinaus) bleiben 0.
                    matrix[row][c] = bits[idx] if idx < len(bits) else 0
                    idx += 1
        upward = not upward
        col -= 2


# ---------------------------------------------------------------------------
# Masken
# ---------------------------------------------------------------------------

_MASK_FUNCS = [
    lambda r, c: (r + c) % 2 == 0,
    lambda r, c: r % 2 == 0,
    lambda r, c: c % 3 == 0,
    lambda r, c: (r + c) % 3 == 0,
    lambda r, c: (r // 2 + c // 3) % 2 == 0,
    lambda r, c: (r * c) % 2 + (r * c) % 3 == 0,
    lambda r, c: ((r * c) % 2 + (r * c) % 3) % 2 == 0,
    lambda r, c: ((r + c) % 2 + (r * c) % 3) % 2 == 0,
]


def _apply_mask(matrix, reserved, mask_id: int):
    """Liefert eine neue Matrix mit angewandter Maske (nur Datenmodule)."""
    size = len(matrix)
    func = _MASK_FUNCS[mask_id]
    out = [row[:] for row in matrix]
    for r in range(size):
        for c in range(size):
            if not reserved[r][c] and func(r, c):
                out[r][c] ^= 1
    return out


def _format_bits(mask_id: int) -> int:
    """15-Bit-Format-Info mit BCH(15,5) und Masken-XOR (Level L)."""
    data = (_ECL_FORMAT_BITS << 3) | mask_id  # 5 Bit: 2 EC-Level + 3 Maske
    rem = data
    for _ in range(10):
        rem = (rem << 1) ^ ((rem >> 9) * 0x537)  # BCH-Generator 0b10100110111
    return ((data << 10) | rem) ^ 0x5412  # Masken-Pattern der Spec


def _place_format(matrix, mask_id: int) -> None:
    """Schreibt beide Kopien der Format-Info in die (gemaskte) Matrix."""
    size = len(matrix)
    bits = _format_bits(mask_id)

    def bit(i: int) -> int:
        return (bits >> i) & 1

    # Erste Kopie (um das obere linke Finder-Muster).
    for i in range(6):
        matrix[i][8] = bit(i)
    matrix[7][8] = bit(6)
    matrix[8][8] = bit(7)
    matrix[8][7] = bit(8)
    for i in range(9, 15):
        matrix[8][14 - i] = bit(i)

    # Zweite Kopie (gespiegelt): Bits 0-7 waagerecht in Zeile 8 (rechts, unter
    # dem oberen rechten Finder), Bits 8-14 senkrecht in Spalte 8 (unten, neben
    # dem unteren linken Finder).
    for i in range(8):
        matrix[8][size - 1 - i] = bit(i)
    for i in range(8, 15):
        matrix[size - 15 + i][8] = bit(i)
    matrix[size - 8][8] = 1  # Dark-Modul (immer schwarz)


# ---------------------------------------------------------------------------
# Penalty-Bewertung (vier Regeln der Spec)
# ---------------------------------------------------------------------------

def _penalty(matrix) -> int:
    size = len(matrix)
    score = 0

    # Regel 1: >=5 gleichfarbige Module in Folge (Zeilen und Spalten).
    for line in (matrix + [[matrix[r][c] for r in range(size)]
                           for c in range(size)]):
        run_color = line[0]
        run_len = 1
        for v in line[1:]:
            if v == run_color:
                run_len += 1
            else:
                if run_len >= 5:
                    score += 3 + (run_len - 5)
                run_color = v
                run_len = 1
        if run_len >= 5:
            score += 3 + (run_len - 5)

    # Regel 2: gleichfarbige 2x2-Bloecke.
    for r in range(size - 1):
        for c in range(size - 1):
            v = matrix[r][c]
            if v == matrix[r][c + 1] == matrix[r + 1][c] == matrix[r + 1][c + 1]:
                score += 3

    # Regel 3: Finder-aehnliches Muster 1:1:3:1:1 mit 4 hellen Modulen.
    pat_a = [1, 0, 1, 1, 1, 0, 1, 0, 0, 0, 0]
    pat_b = [0, 0, 0, 0, 1, 0, 1, 1, 1, 0, 1]
    for r in range(size):
        for c in range(size - 10):
            window = [matrix[r][c + k] for k in range(11)]
            if window == pat_a or window == pat_b:
                score += 40
    for c in range(size):
        for r in range(size - 10):
            window = [matrix[r + k][c] for k in range(11)]
            if window == pat_a or window == pat_b:
                score += 40

    # Regel 4: Abweichung vom 50%-Schwarzanteil.
    dark = sum(sum(row) for row in matrix)
    total = size * size
    percent = dark * 100 // total
    prev5 = percent - (percent % 5)
    next5 = prev5 + 5
    score += min(abs(prev5 - 50), abs(next5 - 50)) // 5 * 10

    return score


# ---------------------------------------------------------------------------
# Oeffentliche API
# ---------------------------------------------------------------------------

def qr_matrix(data: str) -> list[list[int]]:
    """Erzeugt die reine QR-Matrix (NxN) fuer `data`.

    1 = schwarzes Modul, 0 = weiss. OHNE Quiet-Zone.
    Version wird automatisch (1-6) nach Datenlaenge gewaehlt, Maske
    per Penalty-Bewertung ueber alle 8 Masken.
    """
    if not isinstance(data, str):
        raise TypeError("data muss ein String sein")

    num_bytes = len(data.encode("utf-8"))
    version = _choose_version(num_bytes)
    size = 17 + 4 * version

    # 1) Nutzdaten kodieren und mit EC verschachteln.
    data_cw = _encode_data(data, version)
    all_cw = _structure_codewords(data_cw, version)

    # 2) Grundmatrix mit allen Funktionsmustern aufbauen.
    matrix, reserved = _new_matrix(size)
    _place_finder(matrix, reserved, 0, 0)
    _place_finder(matrix, reserved, 0, size - 7)
    _place_finder(matrix, reserved, size - 7, 0)
    _place_alignment(matrix, reserved, version)
    _place_timing(matrix, reserved)
    _reserve_format_areas(reserved, version)

    # 3) Datenbits einfuellen.
    _place_data_bits(matrix, reserved, all_cw)

    # 4) Beste Maske ueber Penalty-Bewertung waehlen.
    best_matrix = None
    best_score = None
    for mask_id in range(8):
        candidate = _apply_mask(matrix, reserved, mask_id)
        _place_format(candidate, mask_id)
        score = _penalty(candidate)
        if best_score is None or score < best_score:
            best_score = score
            best_matrix = candidate

    return best_matrix


def qr_text(data: str, quiet: int = 4) -> str:
    """ASCII-Vorschau (zwei Zeichen pro Modul) mit Quiet-Zone zum Testen."""
    matrix = qr_matrix(data)
    size = len(matrix)
    dark, light = "██", "  "  # zwei Vollbloecke bzw. zwei Leerzeichen

    lines = []
    total = size + 2 * quiet
    for _ in range(quiet):
        lines.append(light * total)
    for row in matrix:
        cells = light * quiet
        cells += "".join(dark if v else light for v in row)
        cells += light * quiet
        lines.append(cells)
    for _ in range(quiet):
        lines.append(light * total)
    return "\n".join(lines)


if __name__ == "__main__":
    import sys

    text = sys.argv[1] if len(sys.argv) > 1 else "http://192.168.1.50:8081"
    m = qr_matrix(text)
    print(f"Daten : {text}")
    print(f"Version/Groesse: {len(m)}x{len(m)} Module")
    print()
    print(qr_text(text))
