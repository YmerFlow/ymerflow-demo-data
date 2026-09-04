#!/usr/bin/env python3
"""The benchmark's forward check: our forward of AGF's published model against Workbench's.

The demo data ships three things that together test a forward model with no inversion
in the loop: AGF's published resistivity model, the data they inverted, and Workbench's
own forward response of that model (``inversion_forward_response_*``). Push the model
through a forward and divide by Workbench's response, gate by gate: a ratio of 1 means
the two forwards agree; a ratio that departs from 1 at the earliest gates and recovers
with time is an unmodelled early-time system effect (front gate, system response).

This drives the YmerFlow simpeg fork's static instrument directly, so it needs that
package installed (``SimPEG.electromagnetics.utils.static_instrument``); it is the one
tool in this repository that is not standalone. It is the check YmerFlow/Ymerflow#94
and #95 are measured against.

Usage:
    python3 forward_vs_workbench.py [--data ../data] [--dataset line_300901] [--step 8]

``--step 8`` forward-models every 8th sounding (67 of 531 on the line, ~45 s
single-threaded). Runs single-threaded on purpose: SimPEG's multiprocessing path
re-imports ``__main__`` and misbehaves on macOS.

Results so far, line 300901, 304 xyz GEX (median ours / Workbench):

  fork without the GEX's receiver low-pass filters (simpleem3 to 2026-09-04):
      LM gates 5-7 (8-13 us) 0.78-0.81, recovering to 0.97 by 300 us; HM 0.94-0.98
  with the two declared first-order filters, coil 210 kHz + TiB 300 kHz (simpeg PR #17):
      LM gates 5-7 0.91-0.95, 0.98 by 300 us; HM 0.98

What is left after the filters - 5-9% at 8-16 us decaying by 40 us - is front-gate
shaped; the flat ~2% at all times is something else. Both on Ymerflow#94; the measured
system response (.sr2) is Ymerflow#95. Whatever fork this runs against, the numbers
it prints are that fork's standing against Workbench.
"""

import argparse
import os
import sys
import time
import warnings

import numpy as np
import libaarhusxyz as lx


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--data", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data"))
    p.add_argument("--dataset", default="line_300901")
    p.add_argument("--step", type=int, default=8, help="forward-model every Nth sounding")
    a = p.parse_args(argv)
    warnings.simplefilter("ignore")
    from SimPEG.electromagnetics.utils.static_instrument import DualMomentTEMXYZSystem

    D = os.path.abspath(a.data)
    inv = os.path.join(D, a.dataset, "agf_inversion")
    gex = lx.GEX(os.path.join(D, "system", "system_skytem304_for_delivered_data.gex"))
    m = lx.XYZ(os.path.join(inv, f"inversion_resistivity_model_{a.dataset}.xyz"))
    m.normalize(naming_standard="libaarhusxyz")
    sel = np.arange(0, len(m.flightlines), a.step)
    sub = lx.XYZ({"flightlines": m.flightlines.iloc[sel].reset_index(drop=True),
                  "layer_data": {k: v.iloc[sel].reset_index(drop=True) for k, v in m.layer_data.items()},
                  "model_info": dict(m.model_info, scalefactor=1e-12, projection=32614)})
    # Inversion data is tilt-corrected by definition; the forward needs the columns to exist.
    sub.flightlines["tilt_x"] = 0.0
    sub.flightlines["tilt_y"] = 0.0
    print(f"model: {len(sub.flightlines)} of {len(m.flightlines)} soundings, {sub.layer_data['resistivity'].shape[1]} layers", flush=True)

    System = DualMomentTEMXYZSystem.load_gex(gex)
    t0 = time.time()
    fwd = System(sub, validate=False).forward(simulation__parallel=False, simulation__n_cpu=1)
    print(f"forward done in {time.time() - t0:.0f}s", flush=True)

    def load(kind):
        x = lx.XYZ(os.path.join(inv, f"{kind}_{a.dataset}.xyz"), alcfile=os.path.join(inv, f"{kind}_{a.dataset}.alc"))
        x.normalize(naming_standard="alc")
        return x
    syn, dat = load("inversion_forward_response"), load("inversion_input_data")
    print("\nours / Workbench forward of the same model, per gate (median over soundings); then Workbench / data (AGF's own fit):")
    for ch, key in ((1, "Gate_Ch01"), (2, "Gate_Ch02")):
        ct = np.asarray(gex.gate_times(ch))[:, 0]
        ours = fwd.layer_data[f"dbdt_ch{ch}gt"].to_numpy(float)
        wb = syn.layer_data[key].to_numpy(float)[sel]
        d = dat.layer_data[key].to_numpy(float)[sel]
        r = np.nanmedian(ours / wb, axis=0)
        f = np.nanmedian(wb / d, axis=0)
        print(f" ch{ch} ours/WB : " + "  ".join(f"g{i}({ct[i] * 1e6:.0f}us)={r[i]:.3f}" for i in np.flatnonzero(np.isfinite(r))))
        print(f" ch{ch} WB/data : " + "  ".join(f"g{i}={f[i]:.2f}" for i in np.flatnonzero(np.isfinite(f))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
