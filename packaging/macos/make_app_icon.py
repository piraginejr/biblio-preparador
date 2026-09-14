#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Gera o iconset do Biblio Preparador sem depender de bibliotecas externas."""

from __future__ import annotations

import math
import pathlib
import struct
import sys
import zlib


GREEN = (28, 91, 65, 255)
GREEN_DARK = (18, 61, 45, 255)
GREEN_LIGHT = (48, 145, 104, 255)
CREAM = (249, 242, 226, 255)
PAPER = (255, 251, 242, 255)
GOLD = (194, 117, 39, 255)
INK = (43, 33, 27, 255)
TRANSPARENT = (0, 0, 0, 0)


def blend(dst, src):
    sr, sg, sb, sa = src
    if sa == 255:
        return src
    if sa == 0:
        return dst
    dr, dg, db, da = dst
    a = sa / 255
    return (
        int(sr * a + dr * (1 - a)),
        int(sg * a + dg * (1 - a)),
        int(sb * a + db * (1 - a)),
        255,
    )


def inside_rounded_rect(x, y, left, top, right, bottom, radius):
    if left + radius <= x <= right - radius and top <= y <= bottom:
        return True
    if left <= x <= right and top + radius <= y <= bottom - radius:
        return True
    centers = (
        (left + radius, top + radius),
        (right - radius, top + radius),
        (left + radius, bottom - radius),
        (right - radius, bottom - radius),
    )
    return any((x - cx) ** 2 + (y - cy) ** 2 <= radius ** 2 for cx, cy in centers)


def point_in_poly(x, y, points):
    inside = False
    j = len(points) - 1
    for i, pi in enumerate(points):
        xi, yi = pi
        xj, yj = points[j]
        if ((yi > y) != (yj > y)) and (
            x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-9) + xi
        ):
            inside = not inside
        j = i
    return inside


def dist_to_segment(px, py, ax, ay, bx, by):
    dx = bx - ax
    dy = by - ay
    if dx == 0 and dy == 0:
        return math.hypot(px - ax, py - ay)
    t = max(0, min(1, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    x = ax + t * dx
    y = ay + t * dy
    return math.hypot(px - x, py - y)


class Canvas:
    def __init__(self, size):
        self.size = size
        self.pixels = [TRANSPARENT] * (size * size)

    def set(self, x, y, color):
        if 0 <= x < self.size and 0 <= y < self.size:
            idx = y * self.size + x
            self.pixels[idx] = blend(self.pixels[idx], color)

    def rect_rounded(self, left, top, right, bottom, radius, color):
        for y in range(max(0, int(top)), min(self.size, int(bottom) + 1)):
            for x in range(max(0, int(left)), min(self.size, int(right) + 1)):
                if inside_rounded_rect(x + 0.5, y + 0.5, left, top, right, bottom, radius):
                    self.set(x, y, color)

    def polygon(self, points, color):
        xs = [p[0] for p in points]
        ys = [p[1] for p in points]
        for y in range(max(0, int(min(ys))), min(self.size, int(max(ys)) + 1)):
            for x in range(max(0, int(min(xs))), min(self.size, int(max(xs)) + 1)):
                if point_in_poly(x + 0.5, y + 0.5, points):
                    self.set(x, y, color)

    def line(self, a, b, width, color):
        ax, ay = a
        bx, by = b
        pad = width + 1
        left = int(min(ax, bx) - pad)
        right = int(max(ax, bx) + pad)
        top = int(min(ay, by) - pad)
        bottom = int(max(ay, by) + pad)
        for y in range(max(0, top), min(self.size, bottom + 1)):
            for x in range(max(0, left), min(self.size, right + 1)):
                if dist_to_segment(x + 0.5, y + 0.5, ax, ay, bx, by) <= width / 2:
                    self.set(x, y, color)


def png_bytes(size, pixels):
    raw = bytearray()
    for y in range(size):
        raw.append(0)
        for x in range(size):
            raw.extend(pixels[y * size + x])
    compressed = zlib.compress(bytes(raw), 9)

    def chunk(kind, data):
        return (
            struct.pack(">I", len(data))
            + kind
            + data
            + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
        )

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0))
        + chunk(b"IDAT", compressed)
        + chunk(b"IEND", b"")
    )


def write_png(path, size, pixels):
    png = png_bytes(size, pixels)
    pathlib.Path(path).write_bytes(png)


def write_icns(path):
    # Tipos PNG aceitos pelo formato ICNS moderno.
    entries = [
        (b"icp4", 16),
        (b"icp5", 32),
        (b"icp6", 64),
        (b"ic07", 128),
        (b"ic08", 256),
        (b"ic09", 512),
        (b"ic10", 1024),
    ]
    chunks = []
    for kind, size in entries:
        data = png_bytes(size, draw_icon(size))
        chunks.append(kind + struct.pack(">I", len(data) + 8) + data)
    total = 8 + sum(len(chunk) for chunk in chunks)
    pathlib.Path(path).write_bytes(b"icns" + struct.pack(">I", total) + b"".join(chunks))


def draw_icon(size):
    c = Canvas(size)
    s = size

    # Fundo arredondado.
    c.rect_rounded(0.06 * s, 0.06 * s, 0.94 * s, 0.94 * s, 0.20 * s, GREEN)
    c.rect_rounded(0.09 * s, 0.09 * s, 0.91 * s, 0.91 * s, 0.17 * s, GREEN_LIGHT[:3] + (70,))

    # Livro aberto.
    left_page = [
        (0.20 * s, 0.34 * s),
        (0.48 * s, 0.26 * s),
        (0.50 * s, 0.72 * s),
        (0.23 * s, 0.79 * s),
    ]
    right_page = [
        (0.52 * s, 0.26 * s),
        (0.80 * s, 0.34 * s),
        (0.77 * s, 0.79 * s),
        (0.50 * s, 0.72 * s),
    ]
    c.polygon(left_page, PAPER)
    c.polygon(right_page, CREAM)
    c.line((0.50 * s, 0.28 * s), (0.50 * s, 0.76 * s), 0.028 * s, GREEN_DARK)
    c.line((0.24 * s, 0.79 * s), (0.50 * s, 0.72 * s), 0.018 * s, GREEN_DARK)
    c.line((0.50 * s, 0.72 * s), (0.76 * s, 0.79 * s), 0.018 * s, GREEN_DARK)

    # Linhas do livro.
    for offset in (0.42, 0.50, 0.58):
        c.line((0.28 * s, offset * s), (0.43 * s, (offset - 0.035) * s), 0.012 * s, GREEN_DARK[:3] + (150,))
        c.line((0.57 * s, (offset - 0.035) * s), (0.72 * s, offset * s), 0.012 * s, GREEN_DARK[:3] + (150,))

    # Seta de preparo/envio.
    c.line((0.50 * s, 0.68 * s), (0.50 * s, 0.45 * s), 0.055 * s, GOLD)
    c.polygon(
        [
            (0.50 * s, 0.33 * s),
            (0.38 * s, 0.48 * s),
            (0.46 * s, 0.48 * s),
            (0.46 * s, 0.54 * s),
            (0.54 * s, 0.54 * s),
            (0.54 * s, 0.48 * s),
            (0.62 * s, 0.48 * s),
        ],
        GOLD,
    )

    # Pequeno ponto de luz.
    c.rect_rounded(0.68 * s, 0.18 * s, 0.78 * s, 0.28 * s, 0.05 * s, (255, 255, 255, 85))
    return c.pixels


def main():
    if len(sys.argv) != 2:
        raise SystemExit("uso: make_app_icon.py CAMINHO.icns|CAMINHO.iconset")
    destino = pathlib.Path(sys.argv[1])
    if destino.suffix == ".icns":
        write_icns(destino)
        return
    iconset = destino
    iconset.mkdir(parents=True, exist_ok=True)
    sizes = {
        "icon_16x16.png": 16,
        "icon_16x16@2x.png": 32,
        "icon_32x32.png": 32,
        "icon_32x32@2x.png": 64,
        "icon_128x128.png": 128,
        "icon_128x128@2x.png": 256,
        "icon_256x256.png": 256,
        "icon_256x256@2x.png": 512,
        "icon_512x512.png": 512,
        "icon_512x512@2x.png": 1024,
    }
    for name, size in sizes.items():
        write_png(iconset / name, size, draw_icon(size))


if __name__ == "__main__":
    main()
