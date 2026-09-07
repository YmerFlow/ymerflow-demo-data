#!/usr/bin/env python3
"""Compare a processed dataset with the data the contractor actually inverted, gate by gate.

Matches soundings by position to the published inversion input
(``inversion_input_data_<dataset>``), then reports per gate and per moment: the median
ratio of your dB/dt to theirs, how far 90% of soundings scatter from it, the fraction of
soundings with the gate in use on each side, and the median relative STD on each side.

That answers the three questions a processing run has to face: are the amplitudes the
same (a flat offset is a processing difference - tilt correction, gate factor, units);
is the gate coverage the same (where each side's culling stopped, early and late); and
are the error bars comparable (which decides how hard the inversion fits).

Usage:
    python3 compare_data_to_published.py path/to/processed_data.msgpack [--dataset line_300901] [--radius 20]

The input is the ``processed_data`` (or ``imported_data``) msgpack a YmerFlow process
writes. Needs libaarhusxyz and scipy.
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
    for a, b in (("UTMX", "UTMY"), ("x", "y")):
        if a in fl.columns:
            return np.column_stack([fl[a].to_numpy(float), fl[b].to_numpy(float)])
    raise KeyError("no position columns among %s" % list(fl.columns))


def keys(xyz, ch):
    """(gate, std, inuse) layer_data keys for a channel, whichever naming the file uses."""
    for g, s, u in (("Gate_Ch%02d" % ch, "STD_Ch%02d" % ch, "InUse_Ch%02d" % ch),
                    ("dbdt_ch%dgt" % ch, "dbdt_std_ch%dgt" % ch, "dbdt_inuse_ch%dgt" % ch)):
        if g in xyz.layer_data:
            return g, s, u
    raise KeyError("no gate block for channel %d" % ch)


def block(xyz, ch):
    g, s, u = keys(xyz, ch)
    G = xyz.layer_data[g].to_numpy(float)
    S = xyz.layer_data[s].to_numpy(float) if s in xyz.layer_data else np.full_like(G, np.nan)
    U = xyz.layer_data[u].to_numpy(float).astype(bool) if u in xyz.layer_data else np.isfinite(G)
    return np.where(U, G, np.nan), S, U


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("processed", help="processed_data msgpack")
    p.add_argument("--dataset", default="line_300901")
    p.add_argument("--radius", type=float, default=20.0)
    a = p.parse_args(argv)

    ours, gex = mp.load(a.processed, True)
    inv = os.path.join(DATA, a.dataset, "agf_inversion")
    pub = lx.XYZ(os.path.join(inv, "inversion_input_data_%s.xyz" % a.dataset),
                 alcfile=os.path.join(inv, "inversion_input_data_%s.alc" % a.dataset))
    pub.normalize(naming_standard="alc")

    d, idx = cKDTree(positions(pub.flightlines)).query(positions(ours.flightlines), distance_upper_bound=a.radius)
    ok = np.isfinite(d)
    print("yours: %d soundings; published input: %d; %d of yours matched within %.0f m (median offset %.1f m)"
          % (len(d), len(pub.flightlines), int(ok.sum()), a.radius, np.nanmedian(d[ok])))

    for ch, name in ((1, "LM"), (2, "HM")):
        t = np.asarray(gex.gate_times(ch))[:, 0]
        G, S, U = block(ours, ch)
        G, S, U = G[ok], S[ok], U[ok]
        A, AS, AU = block(pub, ch)
        A, AS, AU = A[idx[ok]], AS[idx[ok]], AU[idx[ok]]
        print("\n== channel %d (%s), matched soundings ==" % (ch, name))
        print("%4s %8s %9s %13s %11s %6s %9s %8s" % ("gate", "t (us)", "yours/pub", "|ratio-1| p90", "in use yours", "publ.", "STD yours", "STD pub"))
        for k in range(G.shape[1]):
            if not U[:, k].any() and not AU[:, k].any():
                continue
            both = U[:, k] & AU[:, k]
            r = G[both, k] / A[both, k] if both.any() else np.array([np.nan])
            print("%4d %8.0f %9.3f %13.3f %11.2f %6.2f %9.3f %8.3f"
                  % (k, t[k] * 1e6, np.nanmedian(r), np.nanpercentile(np.abs(r - 1), 90) if both.any() else np.nan,
                     U[:, k].mean(), AU[:, k].mean(),
                     np.nanmedian(S[U[:, k], k]) if U[:, k].any() else np.nan,
                     np.nanmedian(AS[AU[:, k], k]) if AU[:, k].any() else np.nan))
    return 0


if __name__ == "__main__":
    sys.exit(main())
