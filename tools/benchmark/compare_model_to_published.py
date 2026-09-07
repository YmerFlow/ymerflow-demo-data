#!/usr/bin/env python3
"""Compare one or more inverted models with the published model, sounding by sounding.

Soundings are matched by position (nearest published sounding within a radius), so
models with a different sounding count or spacing compare correctly - a model from a
30 m re-sampled processing run against the contractor's 37 m one, for instance. Layers
are compared on the published grid: use the published discretization (40 layers, 1 m
first, 350 m last on the 304 demo) when inverting, or the per-layer numbers are not
like for like.

Reports the median resistivity per layer for the top of the section, then the RMS of
log10(rho / rho_published) over three depth bands and the top-layer median ratio. Where a
model carries a computed per-sounding misfit (``resdata``) that is reported too; the
published model's own is 0.661 median on line 300901.

Usage:
    python3 compare_model_to_published.py [--dataset line_300901] [--radius 20]
        label=path/to/smooth_model.msgpack [label=path ...]

Models are the ``smooth_model`` msgpack outputs an inversion writes (download them from
the dataset's file URL). Needs libaarhusxyz and scipy.
"""

import argparse
import os
import sys

import numpy as np
import libaarhusxyz as lx
import libaarhusxyz.export.msgpack as mp
from scipy.spatial import cKDTree

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "..", "..", "data")


def positions(fl):
    for a, b in (("UTMX", "UTMY"), ("x", "y"), ("utmx", "utmy")):
        if a in fl.columns and b in fl.columns:
            return np.column_stack([fl[a].to_numpy(float), fl[b].to_numpy(float)])
    raise KeyError("no position columns among %s" % list(fl.columns))


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("models", nargs="+", help="label=path.msgpack")
    p.add_argument("--dataset", default="line_300901")
    p.add_argument("--radius", type=float, default=20.0, help="max distance to a published sounding, m")
    p.add_argument("--layers", type=int, default=16, help="layers to print from the top")
    a = p.parse_args(argv)

    pub_path = os.path.join(DATA, a.dataset, "agf_inversion", "inversion_resistivity_model_%s.xyz" % a.dataset)
    pub = lx.XYZ(pub_path, normalize=False)
    RP = pub.layer_data["rho_i"].to_numpy(float)
    top = np.nanmedian(pub.layer_data["dep_top"].to_numpy(float), 0)
    tree = cKDTree(positions(pub.flightlines))

    runs = []
    for spec in a.models:
        label, path = spec.split("=", 1)
        x, _ = mp.load(path, True)
        R = x.layer_data["rho"].to_numpy(float)
        d, idx = tree.query(positions(x.flightlines), distance_upper_bound=a.radius)
        ok = np.isfinite(d)
        k = min(R.shape[1], RP.shape[1])
        lr = np.log10(R[ok, :k]) - np.log10(RP[idx[ok], :k])
        res = x.flightlines["resdata"].to_numpy(float) if "resdata" in x.flightlines else None
        runs.append((label, R, lr, res))
        print("%s: %d soundings, %d matched to a published sounding within %.0f m"
              % (label, len(R), int(ok.sum()), a.radius))

    print("\n%6s %6s | %s   (median resistivity, ohm.m)"
          % ("top m", "publ.", " | ".join("%14s" % lab for lab, *_ in runs)))
    for i in range(min(a.layers, RP.shape[1])):
        print("%6.1f %6.1f | %s" % (top[i], np.nanmedian(RP[:, i]),
                                    " | ".join("%14.1f" % np.nanmedian(R[:, i]) for _, R, *_ in runs)))
    print()
    for label, R, lr, res in runs:
        line = ("%14s: RMS log10(rho/published)  top 5 m %.3f | 5-30 m %.3f | 30-100 m %.3f | top-layer median ratio %.2fx"
                % (label, np.sqrt(np.nanmean(lr[:, :5] ** 2)), np.sqrt(np.nanmean(lr[:, 5:16] ** 2)),
                   np.sqrt(np.nanmean(lr[:, 16:27] ** 2)), 10 ** np.nanmedian(lr[:, 0])))
        if res is not None and np.isfinite(res).any():
            line += " | misfit median %.3f p90 %.3f" % (np.nanmedian(res), np.nanpercentile(res, 90))
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
