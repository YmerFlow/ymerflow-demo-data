#!/usr/bin/env python3
"""Split a Workbench dat/syn export into per-moment gate groups, one row per sounding.

Workbench exports of the data that went into an inversion (``_MOD_dat``) and of
the model's forward response (``_MOD_syn``) carry **two rows per sounding**, one
per transmitter moment, distinguished by the ``segment`` column. Every row has
the full set of gate columns (``data_01..data_51`` here), and those columns are
**the union of the LM and HM gate times, sorted by time** - so the two moments
are interleaved column by column, not laid side by side. A segment-1 row fills
the columns whose gate time is an LM gate and holds the dummy elsewhere; a
segment-2 row the converse; a column whose gate time both moments share is
filled in both rows. Gates culled for a sounding are dummy too.

The column -> moment map is therefore the key to the merge. It is derived here
from the data itself - which segment carries real values in each column across
all soundings - and that resolves every column that carries data for any
sounding. Columns that are dummy in every row (late gates culled everywhere)
carry no data and cannot be assigned from the data; they are reported, and
assigned by the ``--gex`` gate-time tables when one is given.

YmerFlow's import wants the opposite: one row per sounding with both moments
across it, as ``Gate_Ch01[...]`` (LM) and ``Gate_Ch02[...]`` (HM). This merges
the segment pairs, takes the LM slice from segment 1 and the HM slice from
segment 2, keeps position/aux columns once, and writes an XYZ plus the ALC that
describes it.


Usage:
    python3 workbench_dat_split_moments.py --out ../data/line_300901/inversion \
        ../data/line_300901/inversion/line_300901_dat.xyz [--gex system.gex]
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from extract_line import read_header, iter_data_rows, detect_flavor  # noqa: E402

DUMMY = "9999"
DUMMY_VALUE = 9999.0


def is_dummy(v):
    try:
        return float(v) == DUMMY_VALUE
    except ValueError:
        return v.strip() == ""
SEGMENT_COL = "segment"
FID_COL = "fid"
LINE_COL = "line"
DATA_PREFIX = "data_"
STD_PREFIX = "datastd_"

# Columns that describe the sounding rather than a moment: keep once, from
# segment 1. Everything else that is not a gate column is dropped, with a note.
KEEP_COLS = ("line", "x", "y", "time", "fid", "record", "topo", "alt", "invalt",
             "invaltstd", "deltaalt", "tilt", "invtilt", "invtiltstd", "resdata", "restotal")


def gate_columns(names, prefix):
    cols = [(i, n) for i, n in enumerate(names) if n.lower().startswith(prefix)]
    cols.sort(key=lambda t: int(t[1][len(prefix):]))
    return cols


def merge(src, out_dir):
    flavor, delim = detect_flavor(src)
    names, header_text = read_header(src, flavor, delim)
    lname = [n.lower() for n in names]
    iseg, ifid, iline = lname.index(SEGMENT_COL), lname.index(FID_COL), lname.index(LINE_COL)
    data_cols = gate_columns(lname, DATA_PREFIX)
    std_cols = gate_columns(lname, STD_PREFIX)
    n_total = len(data_cols)

    rows = {}
    order = []
    for _raw, f, _m in iter_data_rows(src, flavor, delim):
        if iseg >= len(f):
            continue
        key = (f[iline], f[ifid])
        if key not in rows:
            rows[key] = {}
            order.append(key)
        rows[key][f[iseg].strip()] = f

    # Column -> moment map: for each gate column, which segment ever carries a
    # real value there. A column real in segment 1 belongs to LM, in segment 2
    # to HM, in both to both (a shared gate time), in neither to nobody.
    seg1 = [r["1"] for r in rows.values() if "1" in r]
    seg2 = [r["2"] for r in rows.values() if "2" in r]
    lm_cols, hm_cols, unassigned = [], [], []
    for i, name in data_cols:
        in1 = any(not is_dummy(r[i]) for r in seg1)
        in2 = any(not is_dummy(r[i]) for r in seg2)
        if in1: lm_cols.append(i)
        if in2: hm_cols.append(i)
        if not in1 and not in2: unassigned.append(name)
    shared = sorted(set(lm_cols) & set(hm_cols))
    print(f"  column map from data: {len(lm_cols)} LM, {len(hm_cols)} HM"
          f"{f', {len(shared)} shared' if shared else ''}"
          f"{f', {len(unassigned)} dummy-everywhere: {unassigned}' if unassigned else ''}")
    if unassigned:
        print("    (those columns carry no data; their moment needs the GEX gate-time tables)")
    n_lm, n_hm = len(lm_cols), len(hm_cols)
    lm_std = [i + (std_cols[0][0] - data_cols[0][0]) for i in lm_cols] if std_cols else []
    hm_std = [i + (std_cols[0][0] - data_cols[0][0]) for i in hm_cols] if std_cols else []

    keep = [(i, names[i]) for i, n in enumerate(lname) if n in KEEP_COLS]
    out_names = [n for _, n in keep]
    out_names += [f"Gate_Ch01[{k+1:03d}]" for k in range(n_lm)]
    out_names += [f"Gate_Ch02[{k+1:03d}]" for k in range(n_hm)]
    has_std = len(std_cols) == n_total and bool(std_cols)
    if has_std:
        out_names += [f"STD_Ch01[{k+1:03d}]" for k in range(n_lm)]
        out_names += [f"STD_Ch02[{k+1:03d}]" for k in range(n_hm)]

    stem = os.path.splitext(os.path.basename(src))[0]
    out_xyz = os.path.join(out_dir, f"{stem}_merged.xyz")
    out_alc = os.path.join(out_dir, f"{stem}_merged.alc")
    dropped_pairs = 0
    with open(out_xyz, "w") as fh:
        fh.write("/ " + " ".join(out_names) + "\n")
        for key in order:
            pair = rows[key]
            if "1" not in pair or "2" not in pair:
                dropped_pairs += 1
                continue
            s1, s2 = pair["1"], pair["2"]
            vals = [s1[i] for i, _ in keep]
            vals += [s1[i] for i in lm_cols]
            vals += [s2[i] for i in hm_cols]
            if has_std:
                vals += [s1[i] for i in lm_std]
                vals += [s2[i] for i in hm_std]
            fh.write(" ".join(v.strip() for v in vals) + "\n")

    # ALC: positional, 1-based, canonical names the importer understands.
    pos = {n.lower(): i + 1 for i, n in enumerate(out_names)}
    alc = [("Version", 2), ("System", "SkyTEM XYZ"), ("Dummy", DUMMY), ("ChannelsNumber", 2),
           ("Line", pos["line"]), ("UTMX", pos["x"]), ("UTMY", pos["y"]),
           ("Topography", pos["topo"]), ("TxAltitude", pos["invalt"])]
    alc += [(f"Gate_Ch01[{k+1:03d}]", pos[f"gate_ch01[{k+1:03d}]"]) for k in range(n_lm)]
    alc += [(f"Gate_Ch02[{k+1:03d}]", pos[f"gate_ch02[{k+1:03d}]"]) for k in range(n_hm)]
    if has_std:
        alc += [(f"STD_Ch01[{k+1:03d}]", pos[f"std_ch01[{k+1:03d}]"]) for k in range(n_lm)]
        alc += [(f"STD_Ch02[{k+1:03d}]", pos[f"std_ch02[{k+1:03d}]"]) for k in range(n_hm)]
    with open(out_alc, "w") as fh:
        for k, v in alc:
            fh.write(f"{k + '=':<22}{v}\n")

    print(f"  {os.path.basename(src)}: {len(order)} soundings -> {len(order) - dropped_pairs} rows, "
          f"gates LM {n_lm} + HM {n_hm}{' + STD' if has_std else ''}"
          + (f", {dropped_pairs} incomplete pair(s) dropped" if dropped_pairs else ""))
    print(f"    -> {out_xyz}\n    -> {out_alc}")
    return out_xyz, out_alc, n_lm, n_hm


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("sources", nargs="+")
    p.add_argument("--out", required=True)
    a = p.parse_args(argv)
    os.makedirs(a.out, exist_ok=True)
    for s in a.sources:
        merge(s, a.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
