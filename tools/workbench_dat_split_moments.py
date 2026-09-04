#!/usr/bin/env python3
"""Split a Workbench dat/syn export into per-moment gate groups, one row per sounding.

Aarhus Workbench exports of the data that went into an inversion (``_MOD_dat``)
and of the model's forward response (``_MOD_syn``) carry **two rows per
sounding**, one per transmitter moment, told apart by the ``segment`` column
(1 = LM, 2 = HM). Every row has the full set of gate columns (``data_01..NN``),
and those columns are the **union of the LM and HM gate times, sorted by time**
- the two moments are interleaved column by column, not laid side by side. A
segment-1 row holds values only in the LM-time columns and the dummy elsewhere;
a segment-2 row the converse; a gate time both moments share is filled in both
rows. Gates Workbench culled for a sounding are dummy too.

YmerFlow's import wants the layout of a delivered SkyTEM file: one row per
sounding, ``Gate_Ch01[...]`` for LM and ``Gate_Ch02[...]`` for HM, one column
per GEX gate, positive pV/(A m^4). That is what this produces.

The column -> moment map comes from the **GEX**, not from the data. The export
header carries the master gate-time array; the GEX carries each channel's gate
table. LM columns are the ones whose master time equals a Channel1 gate centre
minus that channel's ``GateTimeShift``; HM columns equal a Channel2 gate centre
as written. (Which of the two conventions a channel follows is *tested*, not
assumed - Workbench applied the shift to one moment and not the other in the
files this was built on.) Because the map lands on GEX gate *indices*, the
output carries every GEX gate: the ones Workbench never exported, or culled for
a sounding, are written as the dummy with in-use 0. So the file imports against
the standard GEX for the system - no gate-matched GEX is needed.

The data-derived map (which segment carries a real value in each column) is
kept as a cross-check and the split refuses to proceed if the two disagree on
any column that carries data.

Usage:
    python3 workbench_dat_split_moments.py --gex system.gex --out DIR file.xyz [...]

Library use (this is the shape the libaarhusxyz port takes, see
YmerFlow/libaarhusxyz#10):

    xyz = split_workbench_moments(libaarhusxyz.XYZ(path), libaarhusxyz.GEX(gex))
    xyz.dump(out_xyz, alcfile=out_alc)
"""

import argparse
import os
import sys

import numpy as np
import pandas as pd
import libaarhusxyz as lx


# Workbench writes dB/dt in V/(A m^4); a delivered SkyTEM XYZ - what YmerFlow's
# importer is built for, with its default scalefactor of 1e-12 - carries the
# same quantity in pV/(A m^4). Both are positive for a normal decay (checked on
# the 304 line: 95.5% of exported values positive, the rest noisy late gates;
# per-gate medians of the converted export agree with the delivered file to
# within 6%). The sign is kept as a parameter because a source that writes
# negative decays exists (SimPEG's own convention), and a silent sign flip
# inverts to a plausible wrong model.
WORKBENCH_TO_DELIVERED_SCALE = 1e12
WORKBENCH_TO_DELIVERED_SIGN = 1.0

# Uncertainties (``datastd_NN``) are relative in both worlds; untouched.

SEGMENT_COL = "segment"
LINE_COL = "line"
FID_COL = "fid"
DATA_KEY = "data"
STD_KEY = "datastd"
MASTER_TIMES_KEY = "gate times"
DUMMY_KEY = "dummy"
DEFAULT_DUMMY = 9999.0

# Workbench column -> the canonical (ALC) name the importer understands. The
# rest of the sounding columns are kept under their Workbench names.
FLIGHTLINE_RENAMES = {
    "line": "Line", "fid": "Fid", "x": "UTMX", "y": "UTMY",
    "topo": "Topography", "invalt": "TxAltitude",
    # Workbench's own per-sounding data residual and total residual. Kept -
    # they are the contractor's misfit and therefore the target to match - but
    # under a name that cannot be mistaken for a residual this platform computed.
    "resdata": "wb_resdata", "restotal": "wb_restotal",
}
# Per-segment bookkeeping that means nothing once the pair is one row.
FLIGHTLINE_DROPS = ("segment", "numdata")


class SplitError(ValueError):
    pass


def _gex_channel(gex, ch):
    return gex.gex_dict["Channel%d" % ch]


def gate_map(master_times, gex, channels=(1, 2), tol=5e-3):
    """Map master gate-time columns onto GEX gate indices, per channel.

    Returns ``({ch: {master_col: gate_idx}}, report)``. For each channel both
    time conventions - centre minus ``GateTimeShift``, and centre as written -
    are tried and the one matching more columns wins; the report says which.
    A master column matching two gates of one channel, or two master columns
    matching one gate, is an error: the map must be one-to-one where it exists.
    The tolerance is relative; 0.5% is far inside the 10-30% spacing between
    neighbouring gates, and wide enough for a shared gate whose two centres
    differ slightly (277.7 us on the 304: LM 276.7 us, HM 277.7 us).
    """
    T = np.asarray(master_times, dtype=float)
    maps, report = {}, {}
    for ch in channels:
        block = _gex_channel(gex, ch)
        centres = np.asarray(gex.gate_times(ch), dtype=float)
        centres = centres[:, 0] if centres.ndim == 2 else centres
        shift = float(block.get("GateTimeShift", 0.0))
        best = None
        for convention, cand in (("centre - GateTimeShift", centres - shift), ("centre", centres)):
            idx = np.argmin(np.abs(T[:, None] - cand[None, :]), axis=1)
            ok = np.abs(cand[idx] - T) <= tol * np.abs(T)
            m = {int(j): int(idx[j]) for j in np.flatnonzero(ok)}
            if best is None or len(m) > len(best[1]):
                best = (convention, m)
        convention, m = best
        gates = list(m.values())
        if len(set(gates)) != len(gates):
            dup = sorted({g for g in gates if gates.count(g) > 1})
            raise SplitError("channel %d: GEX gate(s) %s matched by more than one master column" % (ch, dup))
        maps[ch] = m
        report[ch] = {"convention": convention, "n": len(m), "n_gates": len(centres),
                      "gates": sorted(set(gates))}
    return maps, report


def _pair_rows(fl):
    """Row positions of each sounding's segment-1 and segment-2 rows, in file order.

    Returns ``(p1, p2, counts)``; a position is -1 where the sounding has no row
    for that moment. Workbench writes no row for a moment it culled entirely,
    so a sounding with only an HM row is a real, published sounding whose LM
    was rejected - it is kept, with the LM gates all dummy, rather than dropped.
    Soundings are keyed by (line, fid); a duplicate row for one moment is an
    error, since nothing here could choose between them.
    """
    seg = fl[SEGMENT_COL].to_numpy()
    keys = list(zip(fl[LINE_COL].to_numpy(), fl[FID_COL].to_numpy()))
    pos = {1: {}, 2: {}}
    order, seen = [], set()
    for i, (k, s) in enumerate(zip(keys, seg)):
        if s not in pos:
            raise SplitError("row %d: segment %r is neither 1 (LM) nor 2 (HM)" % (i, s))
        if k in pos[s]:
            raise SplitError("sounding %r has more than one segment-%d row" % (k, s))
        pos[s][k] = i
        if k not in seen:
            seen.add(k)
            order.append(k)
    p1 = np.asarray([pos[1].get(k, -1) for k in order], dtype=int)
    p2 = np.asarray([pos[2].get(k, -1) for k in order], dtype=int)
    counts = {"lm_only": int((p2 < 0).sum()), "hm_only": int((p1 < 0).sum())}
    return p1, p2, counts


def split_workbench_moments(xyz, gex, tol=5e-3,
                            scale=WORKBENCH_TO_DELIVERED_SCALE,
                            sign=WORKBENCH_TO_DELIVERED_SIGN, verbose=True):
    """Return a new XYZ: one row per sounding, Gate/STD/InUse per channel, every GEX gate.

    ``xyz`` is a parsed Workbench dat or syn export (``libaarhusxyz.XYZ``);
    ``gex`` the system's ``libaarhusxyz.GEX``.
    """
    fl = xyz.flightlines
    for col in (SEGMENT_COL, LINE_COL, FID_COL):
        if col not in fl.columns:
            raise SplitError("not a Workbench dat/syn export: no %r column" % col)
    if DATA_KEY not in xyz.layer_data:
        raise SplitError("not a Workbench dat/syn export: no %r gate block" % DATA_KEY)
    master = xyz.model_info.get(MASTER_TIMES_KEY)
    if master is None:
        raise SplitError("export header carries no %r line" % MASTER_TIMES_KEY)
    master = np.asarray(master, dtype=float)
    data = xyz.layer_data[DATA_KEY].to_numpy(dtype=float)
    if data.shape[1] != len(master):
        raise SplitError("%d gate columns but %d master gate times" % (data.shape[1], len(master)))
    std = xyz.layer_data[STD_KEY].to_numpy(dtype=float) if STD_KEY in xyz.layer_data else None
    dummy = float(xyz.model_info.get(DUMMY_KEY, DEFAULT_DUMMY))

    maps, report = gate_map(master, gex, tol=tol)
    lm, hm = maps[1], maps[2]
    unmatched = [j for j in range(len(master)) if j not in lm and j not in hm]
    if unmatched:
        raise SplitError("master gate times %s match no gate of either channel: %s"
                         % (unmatched, master[unmatched]))

    p1, p2, counts = _pair_rows(fl)
    if len(p1) == 0:
        raise SplitError("no soundings")
    real = ~(np.isclose(data, dummy) | np.isnan(data))

    # Cross-check: a column that carries data in segment 1 must be an LM column
    # by the GEX, and likewise for segment 2 / HM. The GEX may assign a column
    # the data cannot (dummy everywhere); the reverse is a contradiction.
    seg1_has = real[p1[p1 >= 0]].any(axis=0)
    seg2_has = real[p2[p2 >= 0]].any(axis=0)
    bad = [j for j in range(len(master)) if (seg1_has[j] and j not in lm) or (seg2_has[j] and j not in hm)]
    if bad:
        raise SplitError("GEX map and data disagree on column(s) %s (master times %s)" % (bad, master[bad]))

    n = len(p1)
    out_layers = {}
    for ch, m, rows in ((1, lm, p1), (2, hm, p2)):
        n_gates = report[ch]["n_gates"]
        gate = np.full((n, n_gates), np.nan)
        sd = np.full((n, n_gates), np.nan) if std is not None else None
        present = np.flatnonzero(rows >= 0)      # output rows that have this moment
        src = rows[present]                      # ...and their source rows
        for j, k in m.items():
            keep = real[src, j]
            dst = present[keep]
            gate[dst, k] = sign * scale * data[src[keep], j]
            if sd is not None:
                sd[dst, k] = std[src[keep], j]
        finite = gate[np.isfinite(gate)]
        if finite.size and np.median(finite) < 0:
            raise SplitError("channel %d: converted dB/dt is negative on the whole (median %.3g); "
                             "delivered SkyTEM data is positive - check the sign convention of "
                             "this export before importing" % (ch, np.median(finite)))
        chan = "%02d" % ch
        out_layers["Gate_Ch" + chan] = pd.DataFrame(gate)
        if sd is not None:
            out_layers["STD_Ch" + chan] = pd.DataFrame(sd)
        out_layers["InUse_Ch" + chan] = pd.DataFrame((~np.isnan(gate)).astype(np.int8))

    keep_cols = [c for c in fl.columns if c not in FLIGHTLINE_DROPS]
    aux_rows = np.where(p1 >= 0, p1, p2)         # sounding columns from the LM row, else the HM row
    out_fl = fl.iloc[aux_rows][keep_cols].reset_index(drop=True)
    out_fl = out_fl.rename(columns={c: FLIGHTLINE_RENAMES[c] for c in keep_cols if c in FLIGHTLINE_RENAMES})

    info = dict(xyz.model_info)
    for k in ("number of gates", MASTER_TIMES_KEY, DUMMY_KEY):
        info.pop(k, None)
    info["gate layout"] = ("one row per sounding; Gate_Ch01 = LM on GEX Channel1 gates (%d), "
                           "Gate_Ch02 = HM on GEX Channel2 gates (%d); gates absent from the "
                           "Workbench export or culled for a sounding are * with InUse 0"
                           % (report[1]["n_gates"], report[2]["n_gates"]))
    info["units"] = "dB/dt in pV/(A m^4), positive, as delivered by SkyTEM (Workbench V/(A m^4) x %g)" % (sign * scale)
    info["moment split"] = ("Workbench dat/syn two-rows-per-sounding export merged by GEX gate times "
                            "(LM: %s, HM: %s); see ymerflow-demo-data tools/workbench_dat_split_moments.py"
                            % (report[1]["convention"], report[2]["convention"]))

    if verbose:
        shared = sorted(set(lm) & set(hm))
        print("  gate map from GEX: LM %d cols (%s) -> gates %s; HM %d cols (%s) -> gates %s; shared %d; unmatched 0"
              % (report[1]["n"], report[1]["convention"], _ranges(report[1]["gates"]),
                 report[2]["n"], report[2]["convention"], _ranges(report[2]["gates"]), len(shared)))
        single = "".join(", %d with %s only" % (c, lab) for lab, c in (("HM", counts["hm_only"]), ("LM", counts["lm_only"])) if c)
        print("  %d soundings -> %d rows%s; gates LM %d + HM %d%s"
              % (n, n, single, report[1]["n_gates"], report[2]["n_gates"], " + STD" if std is not None else ""))
    return lx.XYZ({"flightlines": out_fl, "layer_data": out_layers, "model_info": info})


def _ranges(idx):
    """[2,3,5,6,7] -> '2-3,5-7' (GEX gate indices, 0-based)."""
    out, start, prev = [], None, None
    for i in idx:
        if start is None:
            start = prev = i
        elif i == prev + 1:
            prev = i
        else:
            out.append("%d-%d" % (start, prev) if start != prev else str(start))
            start = prev = i
    if start is not None:
        out.append("%d-%d" % (start, prev) if start != prev else str(start))
    return ",".join(out)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("sources", nargs="+", help="Workbench _MOD_dat / _MOD_syn exports")
    p.add_argument("--gex", required=True, help="the system's GEX (the xyz variant)")
    p.add_argument("--out", required=True, help="output directory")
    p.add_argument("--suffix", default="_ymerflow_import", help="appended to the source stem")
    a = p.parse_args(argv)
    os.makedirs(a.out, exist_ok=True)
    gex = lx.GEX(a.gex)
    for src in a.sources:
        print(os.path.basename(src))
        xyz = split_workbench_moments(lx.XYZ(src), gex)
        stem = os.path.splitext(os.path.basename(src))[0] + a.suffix
        out_xyz = os.path.join(a.out, stem + ".xyz")
        out_alc = os.path.join(a.out, stem + ".alc")
        xyz.dump(out_xyz, alcfile=out_alc)
        print("    -> %s\n    -> %s" % (out_xyz, out_alc))
    return 0


if __name__ == "__main__":
    sys.exit(main())
