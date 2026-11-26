"""Pictures of numbers worked out once on the CPU that a filter's shader reads (a filter asks with `// @data name`).

SPDX-FileCopyrightText: KiaseCut
SPDX-License-Identifier: GPL-3.0-or-later
"""
import functools

import numpy as np

BLUE_CELLS = 64                  # the blue noise tile: this many cells each way (it repeats after them)
BLUE_POINTS = 2048               # points in it: half a point to a cell, at most one in any cell
_CANDIDATES = 48
_PLACES = 8                      # places tried in a cell


@functools.lru_cache(maxsize=None)
def blue_noise_tile():
    """(BLUE_CELLS, BLUE_CELLS, 4) float32, a texel to a cell: where in the cell its point is (x, y: 0 - 1), the point's
    place in the order they were made (0 - 1) and 1 when the cell has a point.

    Mitchell's best candidate on a torus (the tile repeats without a seam): each point is the one of a few random ones
    that is farthest from all before it. So the first so many points are spread out too - a density is that many of them."""
    rng = np.random.default_rng(20261126)
    n = BLUE_CELLS
    # the places a point may go: a few random ones in every cell, each with how near the nearest point is (squared)
    cell = np.repeat(np.arange(n * n), _PLACES)
    px = (cell % n + rng.random(len(cell))).astype(np.float32)
    py = (cell // n + rng.random(len(cell))).astype(np.float32)
    near = np.full(len(cell), np.inf, np.float32)
    open_cells = np.arange(n * n)                    # the cells without a point: open_cells[:left]
    left = n * n
    tile = np.zeros((n, n, 4), np.float32)
    for i in range(BLUE_POINTS):
        slots = rng.integers(0, left, _CANDIDATES)
        picked = open_cells[slots] * _PLACES + rng.integers(0, _PLACES, _CANDIDATES)
        best = int(near[picked].argmax())
        k = int(picked[best])
        x, y = int(cell[k] % n), int(cell[k] // n)
        tile[y, x] = (px[k] - x, py[k] - y, (i + 0.5) / BLUE_POINTS, 1.0)
        dx, dy = np.abs(px - px[k]), np.abs(py - py[k])
        np.minimum(dx, n - dx, out=dx)
        np.minimum(dy, n - dy, out=dy)
        np.minimum(near, dx * dx + dy * dy, out=near)
        left -= 1
        open_cells[slots[best]] = open_cells[left]
    tile.setflags(write=False)
    return tile


TABLES = {"blue_noise": blue_noise_tile}
