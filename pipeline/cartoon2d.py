"""Flat 2D cartoons of each BAF complex, generated from the 3D bead models.

Each colour region is the part of one subunit that is visible from the front:
beads (one per residue, pipeline/bead_model.py) are rasterised into a depth
buffer as spheres, every pixel is owned by the frontmost subunit, and each
subunit's owned pixels are smoothed and traced into SVG paths. Regions
therefore never overlap (a Goodsell-style flat illustration rather than
overlapping hulls), and the framing matches the 3D view's front camera, so
the site can cross-fade between the two.

    pixi run cartoons     # writes site/src/lib/cartoons/{cBAF,PBAF,ncBAF}.json

Coordinates are Angstrom in the bead-model frame (x right, y down). `frame`
fits one complex (and matches the 3D view); `shared_frame` is common to all
three, for same-scale, nucleosome-aligned comparison.
"""
from __future__ import annotations

import json

import numpy as np
from scipy import ndimage
from skimage import measure

from .common import ROOT, write_json

MODELS = ROOT / "site" / "src" / "lib" / "models"
OUT = ROOT / "site" / "src" / "lib" / "cartoons"

GRID = 1.0          # A per pixel
BEAD_R = 4.2        # A; slightly above the 3D bead radius so neighbours fuse
SMOOTH = 2.5        # A; closing/opening radius that rounds the cartoon shapes
MIN_AREA = 25.0     # A^2; smaller visible fragments are dropped
SIMPLIFY = 0.45     # A; polygon simplification tolerance
ZOOM = 1.02         # the 3D complex view's default zoom (Complex3D.svelte)


def disk(r_px: float) -> np.ndarray:
    n = int(np.ceil(r_px))
    y, x = np.ogrid[-n:n + 1, -n:n + 1]
    return x * x + y * y <= r_px * r_px


def chaikin(pts: np.ndarray, rounds: int = 2) -> np.ndarray:
    """Corner-cutting smoothing of a closed polygon."""
    for _ in range(rounds):
        nxt = np.roll(pts, -1, axis=0)
        pts = np.column_stack([0.75 * pts + 0.25 * nxt, 0.25 * pts + 0.75 * nxt]).reshape(-1, 2)
    return pts


def path_d(contours: list[np.ndarray]) -> str:
    parts = []
    for c in contours:
        c = np.round(c, 1)
        parts.append("M" + "L".join(f"{x:g} {y:g}" for x, y in c) + "Z")
    return "".join(parts)


def region_key(c: dict) -> str:
    return c["symbol"] if c["kind"] == "subunit" else c["kind"]   # histone / dna / unassigned


def build(name: str) -> dict:
    m = json.loads((MODELS / f"{name}.json").read_text())
    b = np.array(m["beads"], dtype=float).reshape(-1, 4)
    xyz, ci = b[:, :3], b[:, 3].astype(int)
    chains = m["chains"]
    # framing identical to Complex3D: centre = bead mean, R = 99th-percentile radius
    center = xyz.mean(0)
    d = np.sort(np.linalg.norm(xyz - center, axis=1))
    R = float(d[int(np.floor(0.99 * (len(d) - 1)))])
    half = R / (0.94 * ZOOM)
    x0, y0, size = center[0] - half, center[1] - half, 2 * half
    n = int(np.ceil(size / GRID))

    keys = sorted({region_key(c) for c in chains})
    kid = {k: i for i, k in enumerate(keys)}
    bead_key = np.array([kid[region_key(chains[i])] for i in ci])

    # depth buffer: front surface of each bead sphere (+z is toward the viewer)
    zbuf = np.full((n, n), -np.inf)
    owner = np.full((n, n), -1, dtype=int)
    r_px = BEAD_R / GRID
    rr = int(np.ceil(r_px))
    oy, ox = np.mgrid[-rr:rr + 1, -rr:rr + 1]
    cap = r_px * r_px - (ox * ox + oy * oy)
    inside = cap >= 0
    dz = np.sqrt(np.clip(cap, 0, None)) * GRID
    for (x, y, z), k in zip(xyz, bead_key):
        cx, cy = int(round((x - x0) / GRID)), int(round((y - y0) / GRID))
        ys, xs = cy + oy, cx + ox
        ok = inside & (ys >= 0) & (ys < n) & (xs >= 0) & (xs < n)
        yy, xx, zz = ys[ok], xs[ok], z + dz[ok]
        front = zz > zbuf[yy, xx]
        zbuf[yy[front], xx[front]] = zz[front]
        owner[yy[front], xx[front]] = k

    se = disk(SMOOTH / GRID)
    occupied = ndimage.binary_closing(owner >= 0, structure=se)
    pieces = []
    for k, key in enumerate(keys):
        mask = owner == k
        mask = ndimage.binary_opening(ndimage.binary_closing(mask, structure=se), structure=disk(1.2 / GRID))
        mask &= occupied
        lab, nlab = ndimage.label(mask)
        for j in range(1, nlab + 1):
            piece = lab == j
            area = piece.sum() * GRID * GRID
            if area < MIN_AREA:
                continue
            padded = np.pad(piece, 1)
            contours = []
            for c in measure.find_contours(padded.astype(float), 0.5):
                c = measure.approximate_polygon(c, tolerance=SIMPLIFY / GRID)
                if len(c) < 4:
                    continue
                c = chaikin(c[:-1])
                # (row, col) in padded grid -> Angstrom (x, y)
                contours.append(np.column_stack([x0 + (c[:, 1] - 1) * GRID, y0 + (c[:, 0] - 1) * GRID]))
            if not contours:
                continue
            dist = ndimage.distance_transform_edt(piece)
            ay, ax = np.unravel_index(np.argmax(dist), dist.shape)
            own = piece & (owner == k)            # smoothing adds pixels no bead covers (depth -inf)
            depth = float(zbuf[own].mean()) if own.any() else float(np.nanmax(zbuf[np.isfinite(zbuf)]))
            kind = key if key in ("histone", "dna", "unassigned") else "subunit"
            pieces.append({"sym": key if kind == "subunit" else None, "kind": kind, "d": path_d(contours),
                           "area": round(area, 1), "depth": round(depth, 1),
                           "anchor": [round(x0 + ax * GRID, 1), round(y0 + ay * GRID, 1)],
                           "r_in": round(float(dist.max()) * GRID, 1)})
    pieces.sort(key=lambda p: p["depth"])            # back to front

    # ghosts, placed exactly as Complex3D does (between anchor subunits, pushed outward)
    ghosts, flat = [], []
    by_sym = {}
    for c in chains:
        by_sym.setdefault(c["symbol"], []).append(c)
    for g in m.get("ghosts", []):
        anchors = [c for s_ in g.get("anchor_subunits", []) for c in by_sym.get(s_, [])]
        if not anchors:
            flat.append({"slot": g["slot"], "members": g["members"]})
            continue
        a = np.mean([c["centroid"] for c in anchors], axis=0)
        v = a - center
        pos = a + v / (np.linalg.norm(v) or 1) * 22
        ghosts.append({"slot": g["slot"], "members": g["members"], "pos": [round(pos[0], 1), round(pos[1], 1)],
                       "r": 17})

    symbols = sorted({p["sym"] for p in pieces if p["sym"]})
    modelled = sorted({c["symbol"] for c in chains if c["kind"] == "subunit"})
    return {
        "complex": name, "pdb": m["pdb"], "pmid": m["pmid"],
        "frame": [round(x0, 1), round(y0, 1), round(size, 1)],
        "center": [round(center[0], 1), round(center[1], 1)],
        "pieces": pieces, "ghosts": ghosts, "ghosts_flat": flat,
        "hidden": sorted(set(modelled) - set(symbols)),   # modelled but not visible from the front
    }


def shared_frame(frames: list[list[float]]) -> list[float]:
    """One square frame covering every complex. The bead models share a frame
    (superposed on the nucleosome), so this gives all cartoons the same scale
    AND position: the nucleosome sits in the same place in each."""
    x0 = min(f[0] for f in frames); y0 = min(f[1] for f in frames)
    x1 = max(f[0] + f[2] for f in frames); y1 = max(f[1] + f[2] for f in frames)
    size = max(x1 - x0, y1 - y0)
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    return [round(cx - size / 2, 1), round(cy - size / 2, 1), round(size, 1)]


def main() -> None:
    built = {name: build(name) for name in ("cBAF", "PBAF", "ncBAF")}
    common = shared_frame([c["frame"] for c in built.values()])
    for name, c in built.items():
        c["shared_frame"] = common
        json.dumps(c, allow_nan=False)            # fail loudly on inf/NaN rather than emit invalid JSON
        write_json(OUT / f"{name}.json", c)
        size = (OUT / f"{name}.json").stat().st_size
        print(f"{name} {c['pdb']}: {len(c['pieces'])} pieces, "
              f"{len({p['sym'] for p in c['pieces'] if p['sym']})} subunits visible"
              + (f", hidden from front: {c['hidden']}" if c["hidden"] else "")
              + f", {len(c['ghosts'])} ghosts + {len(c['ghosts_flat'])} unplaced; {size // 1024} KB")


if __name__ == "__main__":
    main()
