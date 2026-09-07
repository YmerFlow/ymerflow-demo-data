#!/usr/bin/env python3
"""Measure two processing parameters from a delivered line instead of guessing them.

**Noise level at 1 ms** for the ``STD error: Add from noise model`` step. Taken as the
sounding-to-sounding scatter of the raw high-moment data (the ground barely changes over
one 10 Hz step, so the difference between neighbours is noise), divided by sqrt(2),
converted from the delivered pV/(A m^4) to the step's V/m^2 using the GEX dipole moment,
and fitted with a power law over the late gates. Reports the level at 1 ms and the
exponent. On the 304 demo line: ~2e-9 V/m^2, exponent -1.3 (the textbook -0.5 is for
pure ambient noise; the raw floor still holds signal).

**Curvature limits** for the ``Disable gates by curvature`` steps. Curvature is the second
difference of log10(dB/dt) against log10(t). Reports the 0.5-99.5% range of what the
contractor's culling kept (from the published inversion input) beside the raw line's, so
a limit can bracket the accepted data with a little room. On the 304 demo line:
LM -2.1..+2.2, HM -5.4..+4.8 kept; the step's defaults of +/-10 would cull almost nothing.

Usage:
    python3 measure_noise_and_curvature.py [--dataset line_300901]

Needs libaarhusxyz.
"""

import argparse
import os
import sys

import numpy as np
import libaarhusxyz as lx

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "..", "..", "data")


def curvature(G, t):
    x = np.log10(np.abs(G))
    y = np.log10(t)
    return (x[:, 2:] - 2 * x[:, 1:-1] + x[:, :-2]) / (y[2:] - y[:-2]) ** 2


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--dataset", default="line_300901")
    a = p.parse_args(argv)

    gex = lx.GEX(os.path.join(DATA, "system", "system_skytem304_for_delivered_data.gex"))
    dl = os.path.join(DATA, a.dataset, "as_delivered", "skytem_as_delivered_%s" % a.dataset)
    inv = os.path.join(DATA, a.dataset, "agf_inversion", "inversion_input_data_%s" % a.dataset)
    raw = lx.XYZ(dl + ".xyz", alcfile=dl + ".alc")
    raw.normalize(naming_standard="alc")
    kept = lx.XYZ(inv + ".xyz", alcfile=inv + ".alc")
    kept.normalize(naming_standard="alc")

    with np.errstate(all="ignore"):
        print("== noise level for 'STD error: Add from noise model', from the raw HM scatter ==")
        t2 = np.asarray(gex.gate_times(2))[:, 0]
        moment = float(gex.gex_dict["Channel2"]["ApproxDipoleMoment"])
        g2 = raw.layer_data["Gate_Ch02"].to_numpy(float)
        noise = np.nanstd(np.diff(g2, axis=0) / np.sqrt(2), axis=0) * 1e-12 * moment   # V/m^2
        signal = np.nanmedian(np.abs(g2), axis=0) * 1e-12 * moment
        for k in np.flatnonzero(np.isfinite(noise))[::4]:
            print("  HM gate %2d  t = %6.2f ms  signal %.2e  noise %.2e V/m^2  S/N %5.1f"
                  % (k, t2[k] * 1e3, signal[k], noise[k], signal[k] / noise[k]))
        ok = np.isfinite(noise) & (t2 > 3e-4)
        fit = np.polyfit(np.log10(t2[ok]), np.log10(noise[ok]), 1)
        print("  power-law fit over gates later than 0.3 ms: noise ~ t^%.2f ; level at 1 ms = %.2e V/m^2"
              % (fit[0], 10 ** np.polyval(fit, -3)))

        print("\n== curvature of log10(dB/dt) vs log10(t): kept by the contractor's culling, vs the raw line ==")
        for name, key, ch in (("LM", "Gate_Ch01", 1), ("HM", "Gate_Ch02", 2)):
            t = np.asarray(gex.gate_times(ch))[:, 0]
            ck = np.nanpercentile(curvature(kept.layer_data[key].to_numpy(float), t), [0.5, 2.5, 50, 97.5, 99.5])
            cr = np.nanpercentile(curvature(raw.layer_data[key].to_numpy(float), t), [0.5, 2.5, 50, 97.5, 99.5])
            print("  %s kept: p0.5 %6.2f  p2.5 %6.2f  median %6.2f  p97.5 %6.2f  p99.5 %6.2f" % ((name,) + tuple(ck)))
            print("  %s raw : p0.5 %6.2f  p2.5 %6.2f  median %6.2f  p97.5 %6.2f  p99.5 %6.2f" % ((name,) + tuple(cr)))

        print("\n== along-line spacing of the delivered soundings ==")
        fl = raw.flightlines
        sp = np.hypot(np.diff(fl["UTMX"].to_numpy(float)), np.diff(fl["UTMY"].to_numpy(float)))
        m = np.median(sp)
        print("  median %.2f m per sounding; an averaging window of N soundings is N x %.2f m" % (m, m))
    return 0


if __name__ == "__main__":
    sys.exit(main())
