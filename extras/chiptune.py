#!/usr/bin/env python3
"""Chiptune-Sound fuer PAC-PI: synthetisiert Melodien + Effekte als pygame-Sounds (keine Audiodateien noetig).
Spielt den echten Soundtrack ueber Monitor/HDMI, waehrend der Buzzer auf der Platine parallel laeuft."""
import numpy as np

SR = 44100
NOTEN = {"C": 0, "C#": 1, "D": 2, "D#": 3, "E": 4, "F": 5, "F#": 6, "G": 7, "G#": 8, "A": 9, "A#": 10, "B": 11}


def frequenz(note):
    if not note or note == "-":
        return 0.0
    name, okt = note[:-1], int(note[-1])
    return 440.0 * 2 ** ((12 * (okt + 1) + NOTEN[name] - 69) / 12)


def _welle(form, phase):
    if form == "square":
        return np.where((phase % 1.0) < 0.5, 1.0, -1.0)
    if form == "pulse":  # schmaler Puls = heller, naselnder NES-Ton
        return np.where((phase % 1.0) < 0.25, 1.0, -1.0)
    if form == "triangle":
        return 2 * np.abs(2 * (phase % 1.0) - 1) - 1
    if form == "saw":
        return 2 * (phase % 1.0) - 1
    return np.sin(2 * np.pi * phase)  # sine


def _ton(f, dauer, form, vol):
    n = max(1, int(SR * dauer))
    if f <= 0:
        return np.zeros(n, dtype=np.float32)
    t = np.arange(n) / SR
    y = _welle(form, f * t)
    # kleiner Vibrato gibt Leben, Huelle verhindert Klicks
    y += 0.25 * _welle(form, f * t * 2.01) if form in ("pulse", "square") else 0
    huelle = np.ones(n)
    a = min(n, int(SR * 0.006))
    d = min(n - a, int(SR * 0.05))
    huelle[:a] = np.linspace(0, 1, a)
    if d > 0:
        huelle[-d:] = np.linspace(1, 0.0, d)
    huelle *= np.linspace(1.0, 0.75, n)  # leichtes Abklingen
    return (y * huelle * vol).astype(np.float32)


class Chiptune:
    def __init__(self):
        self.ok = False
        self.cache = {}
        self.aktuell = None
        try:
            import pygame
            if not pygame.mixer.get_init():
                pygame.mixer.pre_init(SR, -16, 2, 512)
                pygame.mixer.init()
            pygame.mixer.set_num_channels(16)
            self.pg = pygame
            self.kanal_musik = pygame.mixer.Channel(0)
            self.ok = True
        except Exception as e:  # kein Audiogeraet -> stumm, Buzzer uebernimmt
            print("Chiptune aus (kein Audio):", e)

    def _sound(self, lied, form, vol):
        schluessel = (id(lied), form, round(vol, 2))
        if schluessel not in self.cache:
            teile = [_ton(frequenz(note), dauer, form, vol) for note, dauer in lied]
            daten = np.concatenate(teile) if teile else np.zeros(1, dtype=np.float32)
            stereo = np.ascontiguousarray(np.column_stack([daten, daten]) * 32767, dtype=np.int16)
            self.cache[schluessel] = self.pg.sndarray.make_sound(stereo)
        return self.cache[schluessel]

    def musik(self, lied):
        if not self.ok or lied is self.aktuell:
            return
        self.aktuell = lied
        self.kanal_musik.play(self._sound(lied, "triangle", 0.35), loops=-1)

    def stop(self):
        self.aktuell = None
        if self.ok:
            self.kanal_musik.stop()

    def effekt(self, lied, form="pulse", vol=0.5):
        if not self.ok:
            return
        kanal = self.pg.mixer.find_channel(True)
        if kanal and kanal is not self.kanal_musik:
            kanal.play(self._sound(lied, form, vol))
