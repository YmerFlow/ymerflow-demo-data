#!/usr/bin/env python3
"""How the averaged uncertainty depends on the averaging window, gate by gate.

Runs emerald-processing's hybrid rolling average on the delivered line at several
constant window widths, with the same prior STD each time, and reports the median
output STD per gate. It answers the question a trapezoid filter poses: how wide can the
window be at each gate before the STD it produces stops being noise and starts being the
ground changing along the line.

Early gates are sensitive to altitude and the top few metres, both of which vary along a
line, so the spread across a wide window is real variation and the averaging's variance
formula counts it as uncertainty. Late gates vary slowly and sit near the noise floor, so
width barely matters there. For reference the tool also prints the along-line spread of
the raw signal itself over the same windows. On the 304 demo line: gate 7 STD 3.0% at width
1, 4.8% at 25 soundings (56 m), 7.8% at 51, 16.4% at 125 - tracking the raw signal's own
spread (0.02 over 25 m, 0.10 over 114 m, 0.23 over 279 m).

Usage:
    python3 window_width_vs_std.py [--dataset line_300901] [--channel 1]
        [--soundings 2000] [--widths 1,5,11,25,51,125] [--noise-1ms 2e-9] [--rel 0.03]

Needs libaarhusxyz and emeraldprocessing.
"""

import argparse
import os
import sys
import time

import numpy as np
import pandas as pd
import libaarhusxyz as lx

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "..", "..", "data")


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--dataset", default="line_300901")
    p.add_argument("--channel", type=int, default=1)
    p.add_argument("--soundings", type=int, default=2000, help="use the first N soundings (speed)")
    p.add_argument("--widths", default="1,5,11,25,51,125", help="window widths in soundings")
    p.add_argument("--noise-1ms", type=float, default=2e-9, help="noise level at 1 ms, V/m^2 (prior STD)")
    p.add_argument("--rel", type=float, default=0.03, help="relative error fraction (prior STD)")
    p.add_argument("--gates", default="7,10,15,20,23", help="gates to report")
    a = p.parse_args(argv)
    from emeraldprocessing.tem.utils import rolling_hybrid_mean_df

    gex = lx.GEX(os.path.join(DATA, "system", "system_skytem304_for_delivered_data.gex"))
    ch = a.channel
    t = np.asarray(gex.gate_times(ch))[:, 0]
    moment = float(gex.gex_dict["Channel%d" % ch]["ApproxDipoleMoment"])
    dl = os.path.join(DATA, a.dataset, "as_delivered", "skytem_as_delivered_%s" % a.dataset)
    raw = lx.XYZ(dl + ".xyz", alcfile=dl + ".alc")
    raw.normalize(naming_standard="alc")
    fl = raw.flightlines
    spacing = np.median(np.hypot(np.diff(fl["UTMX"].to_numpy(float)), np.diff(fl["UTMY"].to_numpy(float))))

    G = raw.layer_data["Gate_Ch%02d" % ch].iloc[:a.soundings].reset_index(drop=True)
    g = G.to_numpy(float)
    with np.errstate(all="ignore"):
        noise_rel = (a.noise_1ms * (t / 1e-3) ** -0.5) / (np.abs(g) * 1e-12 * moment)
    err = pd.DataFrame(np.sqrt(a.rel ** 2 + noise_rel ** 2), columns=G.columns)
    gates = [int(k) for k in a.gates.split(",")]
    widths = [int(w) for w in a.widths.split(",")]

    print("channel %d, first %d soundings, %.2f m per sounding; prior STD = %.0f%% (+) noise %.1e V/m^2 at 1 ms"
          % (ch, len(G), spacing, a.rel * 100, a.noise_1ms))
    print("\nmedian output STD after the hybrid average:")
    print("%6s %7s | %s" % ("width", "metres", " ".join("gate %2d (%4.0f us)" % (k, t[k] * 1e6) for k in gates)))
    for W in widths:
        t0 = time.time()
        _, fe = rolling_hybrid_mean_df(G, err, [W] * G.shape[1])
        print("%6d %7.0f | %s   (%.0fs)" % (W, W * spacing,
                                            " ".join("%16.3f" % np.nanmedian(fe.iloc[:, k]) for k in gates), time.time() - t0))

    print("\nalong-line spread of the raw signal over the same windows (p16-p84 half-width / median):")
    print("%6s %7s | %s" % ("width", "metres", " ".join("gate %2d          " % k for k in gates)))
    for W in widths:
        if W < 3:
            continue
        row = []
        for k in gates:
            r = pd.Series(g[:, k]).rolling(W, center=True, min_periods=max(2, W // 3))
            with np.errstate(all="ignore"):
                row.append(np.nanmedian(((r.quantile(0.84) - r.quantile(0.16)) / 2 / r.median()).to_numpy()))
        print("%6d %7.0f | %s" % (W, W * spacing, " ".join("%16.3f" % v for v in row)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
