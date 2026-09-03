#!/usr/bin/env python3
"""Build the clean demo dataset from the public LPNNRD/LPSNRD deliverables.

This is the whole derivation, start to finish, so that every file shipped in
this repository can be reproduced from the public downloads rather than taken
on trust. See PROVENANCE.md for where the inputs come from.

What it does, per dataset:

  1. **Extract** the wanted flight lines (and, for the block, clip to a bounding
     box) out of the multi-gigabyte deliverables, streaming.
  2. **Convert** the pre-processed data to Aarhus Workbench XYZ. The LPSNRD
     deliverable is a Geosoft CSV export - comma-delimited, alphabetically
     ordered columns, ``Line NNNNNN`` block markers - which libaarhusxyz cannot
     read, so it goes via ``aem_csv_to_xyz``.
  3. **Rename** the mis-named ``Alt`` column to ``tx_elevation``. It holds the
     transmitter's *elevation* (verified equal to ``DTM + Height`` to 0.1 m),
     not an altitude. Shipping the vendor name hands the next reader the same
     trap that once caused the pipeline to cull 100% of soundings.
  4. **Strip the halfspace** from the Workbench model exports. Those carry N
     layers but only N-1 thicknesses; the last is an unbounded halfspace, and
     AGF removes it before publishing because it is often meaningless. Doing the
     same here makes our models match the published product exactly.

Only the pre-processed data needs step 2; the model exports are already
whitespace-delimited XYZ that libaarhusxyz reads natively.

Usage:
    python3 build_dataset.py --source /path/to/deliverables --out ../data
"""

import argparse
import os
import re
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import extract_line
from aem_csv_to_xyz import data_csv_to_xyz


# ---------------------------------------------------------------------------
# Configuration - everything project-specific lives here
# ---------------------------------------------------------------------------

# The single line: a whole flight line, for running a pipeline end to end.
LINE_DATASET = {
    "name": "line_300901",
    "lines": ["300901"],
    "bbox": None,
}

# The block: adjacent lines over a common area, for anything needing lateral
# continuity - spatially constrained inversion, gridding, sections.
BLOCK_DATASET = {
    "name": "block",
    "lines_file": "demo_lines.txt",
    # easting/northing in the survey CRS, EPSG:32614 (WGS 84 / UTM zone 14N)
    "bbox": (693194.0, 4549995.0, 700199.0, 4555187.0),
}

# Source deliverables, relative to --source. Each dataset draws its
# pre-processed data and its models from whichever delivery actually covers it:
# the LPSNRD export covers all 26 block lines, the LPNNRD one covers 300901.
SOURCES = {
    "line_300901": {
        "data":   "LPNNRD2018_EM_MAG_AUX.xyz",
        # ALC shipped with the delivery, describing the LPNNRD column order.
        # Renaming Alt -> tx_elevation does not move any column, so the
        # positional mapping in it stays valid.
        "data_alc": "LPNNRD2018_EM_MAG_AUX_300901.alc",
        "models": {"dat": "2018_AGF_LPNNRD/LPNLPS_SCI12i_MOD_dat.xyz",
                   "mod": "2018_AGF_LPNNRD/LPNLPS_SCI12i_MOD_inv.xyz",
                   "syn": "2018_AGF_LPNNRD/LPNLPS_SCI12i_MOD_syn.xyz"},
    },
    "block": {
        "data":   "LPSNRD2018_EM_MAG_AUX.XYZ",
        "models": {"dat": "2018_AGF_LPNNRD/LPNLPS_SCI12i_MOD_dat.xyz",
                   "mod": "2018_AGF_LPNNRD/LPNLPS_SCI12i_MOD_inv.xyz",
                   "syn": "2018_AGF_LPNNRD/LPNLPS_SCI12i_MOD_syn.xyz"},
    },
}

# Shared system description - one GEX serves both districts (the two copies in
# the delivery are byte-identical), plus a flight-line mask per district.
SYSTEM_FILES = [
    "20180613_446_NE304_LPNNRD.lin",
    "20180613_446_NE304_LPSNRD.lin",
]

# The vendor's "Alt" is an elevation, not an altitude. Renamed on export.
COLUMN_RENAMES = {"Alt": "tx_elevation"}

# The delivery publishes only the "_skb" GEX: the system as flown, with the GPS,
# altimeter and inclinometer offsets from the frame centre and the measured
# GateFactor per channel. The delivered XYZ has already had those applied -
# soundings are referenced to the frame centre and gates are scaled - so an
# inversion must NOT apply them again. The matching "xyz" GEX is the skb one
# with those corrections neutralized. Verified by diffing a skb/xyz pair from
# another SkyTEM 304 survey (private, not included here): these keys are the
# ENTIRE difference.
# RxCoilPosition is deliberately left alone - the receiver really is offset
# from the frame centre, and the forward model needs that.
SKB_GEX = "20180823_304_DualWaveform_60Hz_skb.gex"
XYZ_GEX_OUT = "20180823_304_DualWaveform_60Hz_xyz.gex"
GEX_ZERO_KEYS = ("GPSDifferentialPosition", "GPSPosition",
                 "AltimeterPosition", "InclinometerPosition")
GEX_UNIT_KEYS = ("GateFactor",)


def derive_xyz_gex(skb_path, out_path):
    """Write the xyz-variant GEX from the skb one; return the list of changed lines."""
    changed, out = [], []
    with open(skb_path, "r", errors="replace") as fh:
        for raw in fh:
            line = raw.rstrip("\n")
            key = line.split("=", 1)[0].strip() if "=" in line else ""
            base = key.rstrip("0123456789")
            new = line
            if base in GEX_ZERO_KEYS:
                new = f"{key}={'0.00':>25}{'0.00':>9}{'0.00':>9}"
            elif base in GEX_UNIT_KEYS:
                new = f"{key}=1.0"
            if new != line:
                changed.append((line.strip(), new.strip()))
            out.append(new)
    with open(out_path, "w") as fh:
        fh.write("\n".join(out) + "\n")
    return changed

# ALC describing the Geosoft column order, for the LPSNRD pre-processed export.
GEOSOFT_ALC = "alc/LPSNRD2018_EM_MAG_AUX_geosoft.alc"


# Identifying detail carried in the Workbench export headers. A delivered file
# names things in more places than its filename, and free-text header fields are
# where they survive: these two carry an individual's username and a contractor's
# internal directory tree, neither of which belongs in a public dataset.
#
# The survey itself needs no scrubbing - it is published by the districts, so its
# location, dates and line numbering are already public. Only the operator's own
# details are removed.
HEADER_SCRUBS = [
    (re.compile(r"User:\s*\S+"), "User: <User>"),
    (re.compile(r"^[A-Za-z]:\\.*$"), "LPSNRD_SCI_folder"),   # absolute Windows path
]


def scrub_header(xyz):
    """Replace identifying operator detail in a model's header block.

    Returns a list of (before, after) pairs for whatever was changed, so the
    build reports it rather than scrubbing silently.
    """
    changed = []
    info = xyz.get("model_info") or {}
    for key, value in info.items():
        if not isinstance(value, str):
            continue
        new = value
        for pattern, replacement in HEADER_SCRUBS:
            new = pattern.sub(replacement, new)
        if new != value:
            info[key] = new
            changed.append((value, new))
    return changed


# A real layer in a geometric-progression discretization is only ~1.05-1.3x
# thicker than the one above it. A halfspace is normally 10x+. Anything at or
# above this ratio is taken to be a halfspace rather than a genuine layer.
HALFSPACE_THICKNESS_RATIO = 3.0


def strip_halfspace(xyz, verbose=True):
    """Drop the trailing halfspace layer from a Workbench model, if present.

    Workbench inversion exports carry N layers where the deepest is an unbounded
    halfspace. AGF strips it before publishing - it is usually meaningless - so
    doing the same makes our models match the published product.

    Detection uses two independent signals, because neither is sufficient alone:

    * **Column count** - a short ``dep_bot`` relative to ``dep_top`` means the
      halfspace has no bottom depth, so it is present. Reliable when the source
      genuinely omits the slot, but **not** reliable on raw Workbench files in
      general: Workbench often writes a real-but-meaningless value into the
      halfspace's thickness/bottom slot instead of leaving it short, and then
      column counting silently reports no halfspace.
    * **Geometry** - the last layer's median thickness against the one above it,
      computed from ``dep_bot - dep_top`` rather than from ``thk`` (whose column
      count is the very thing in question). This reads the data instead of the
      file's bookkeeping conventions.

    When the two disagree the geometry signal wins, and the reason is printed.

    Only arrays whose width equals the layer count are trimmed - deliberately
    not a blanket ``min()`` across every array, so gate data (``dat``/``syn``,
    at a different width entirely) and already-short arrays are left alone.

    Returns the number of layers dropped (0 or 1).
    """
    layers = xyz.get("layer_data") or {}
    if "dep_top" not in layers:
        return 0                      # not a layered model - gate data, say

    n_layers = layers["dep_top"].shape[1]
    dep_bot = layers.get("dep_bot")

    by_columns = dep_bot is not None and dep_bot.shape[1] < n_layers

    by_geometry, ratio = None, None
    if dep_bot is not None and dep_bot.shape[1] == n_layers and n_layers >= 2:
        thickness = dep_bot.to_numpy(float) - layers["dep_top"].to_numpy(float)
        import numpy as np
        last, above = np.nanmedian(thickness[:, -1]), np.nanmedian(thickness[:, -2])
        if above and np.isfinite(last) and np.isfinite(above) and above > 0:
            ratio = last / above
            by_geometry = ratio >= HALFSPACE_THICKNESS_RATIO

    present = by_geometry if by_geometry is not None else by_columns
    if by_geometry is not None and by_geometry != by_columns:
        print(f"    halfspace: column count says {by_columns}, geometry says "
              f"{by_geometry} (last layer {ratio:.1f}x the one above) - "
              f"trusting geometry, since column bookkeeping is convention-dependent")

    if not present:
        return 0

    for key, df in layers.items():
        if df.shape[1] == n_layers:
            layers[key] = df.iloc[:, :n_layers - 1]
    if verbose:
        how = f"geometry, ratio {ratio:.1f}x" if by_geometry else "column count"
        print(f"    halfspace stripped ({how}): {n_layers} -> {n_layers - 1} layers")
    return 1


def _copy_data_alc(name, src_root, tools_dir, out_dir, flavor):
    """Put an ALC beside the pre-processed data file.

    Without one the data file has no column mapping, and an ALC is positional -
    so it must match the layout the data was written in, not some other file's.
    The Geosoft column order needs the ALC written for it in this repo; the
    LPNNRD order is described by the ALC that ships with the delivery.
    """
    dst = os.path.join(out_dir, "delivered", f"{name}_delivered.alc")
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    if flavor == "geosoft":
        shutil.copy(os.path.join(tools_dir, GEOSOFT_ALC), dst)
        return True
    rel = SOURCES[name].get("data_alc")
    src = os.path.join(src_root, rel) if rel else None
    if src and os.path.exists(src):
        shutil.copy(src, dst)
        return True
    print(f"    WARNING: no ALC for {name}_data.xyz - it ships without a column mapping")
    return False


def resolve_lines(dataset, repo_dir):
    """The flight lines this dataset wants, inline or from its lines file."""
    if dataset.get("lines"):
        return dataset["lines"]
    path = os.path.join(repo_dir, dataset["lines_file"])
    with open(path) as fh:
        return [l.strip() for l in fh if l.strip() and not l.startswith("#")]


def build_data(dataset, src_root, out_dir, tools_dir, lines):
    """Extract and convert the pre-processed (10 Hz) data for one dataset."""
    import pandas as pd

    name = dataset["name"]
    src = os.path.join(src_root, SOURCES[name]["data"])

    print(f"  [{name}] pre-processed data")
    flavor, delimiter = extract_line.detect_flavor(src)

    # Conversion keys on the DELIMITER, not the flavor. libaarhusxyz reads with
    # sep=",?[\s]+" - an optional comma followed by whitespace - so any
    # comma-without-space file is unreadable to it, whether that is the Geosoft
    # export or the plain comma-delimited LPNNRD deliverable. Only a
    # whitespace-delimited source can pass through untouched.
    if delimiter == ",":
        csv_path = extract_line.extract(src, out_dir, lines, dataset["bbox"],
                                        suffix="tmp", plain_csv=True)
        if not csv_path:
            print(f"  [{name}] no matching rows in {os.path.basename(src)}")
            return False
        df = pd.read_csv(csv_path, low_memory=False)
        renamed = {k: v for k, v in COLUMN_RENAMES.items() if k in df.columns}
        df = df.rename(columns=renamed)
        if renamed:
            print(f"    renamed {renamed}")
        df.to_csv(csv_path, index=False)
        xyz_path = os.path.join(out_dir, "delivered", f"{name}_delivered.xyz")
        os.makedirs(os.path.dirname(xyz_path), exist_ok=True)
        data_csv_to_xyz(csv_path, xyz_path)
        os.remove(csv_path)
        _copy_data_alc(name, src_root, tools_dir, out_dir, flavor)
    else:
        got = extract_line.extract(src, out_dir, lines, dataset["bbox"], suffix="data")
        if got:
            dst = os.path.join(out_dir, "delivered", f"{name}_delivered.xyz")
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            os.replace(got, dst)
    return True


def build_models(dataset, src_root, out_dir, lines):
    """Extract each model export, strip the halfspace, and re-dump."""
    import libaarhusxyz as lx

    name = dataset["name"]
    for kind, rel in SOURCES[name]["models"].items():
        src = os.path.join(src_root, rel)
        tmp = extract_line.extract(src, out_dir, lines, dataset["bbox"], suffix=f"tmp{kind}")
        if not tmp:
            print(f"  [{name}] {kind}: no matching rows")
            continue
        xyz = lx.parse(tmp)
        for before, after in scrub_header(xyz):
            print(f"    scrubbed header: {before[:58]!r} -> {after[:48]!r}")
        dropped = strip_halfspace(xyz)
        inv_dir = os.path.join(out_dir, "inversion")
        os.makedirs(inv_dir, exist_ok=True)
        out_xyz = os.path.join(inv_dir, f"{name}_{kind}.xyz")
        out_alc = os.path.join(inv_dir, f"{name}_{kind}.alc")
        lx.dump(xyz, out_xyz, alcfile=out_alc)

        # An ALC maps gate/channel columns. Model exports carry layers, not
        # gates, so theirs comes out as a header with no mappings at all -
        # meaningless, and misleading to ship as if it were needed. Drop it
        # unless it actually maps something, which also keeps this correct if a
        # future export does carry mappable columns.
        with open(out_alc) as fh:
            header_only = {"Version", "System", "Dummy", "ChannelsNumber"}
            mappings = [l for l in fh
                        if l.split("=")[0].strip() not in header_only and l.strip()]
        if not mappings:
            os.remove(out_alc)
        os.remove(tmp)
        shape = {k: v.shape for k, v in xyz["layer_data"].items()}
        print(f"  [{name}] {kind}: halfspace layers dropped={dropped}  {shape}")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source", required=True,
                        help="directory holding the downloaded public deliverables")
    parser.add_argument("--out", default="../data", help="output directory")
    parser.add_argument("--only", choices=["line_300901", "block"],
                        help="build just one dataset")
    args = parser.parse_args(argv)

    tools_dir = os.path.dirname(os.path.abspath(__file__))
    repo_dir = os.path.dirname(tools_dir)
    datasets = [LINE_DATASET, BLOCK_DATASET]
    if args.only:
        datasets = [d for d in datasets if d["name"] == args.only]

    for dataset in datasets:
        out_dir = os.path.join(args.out, dataset["name"])
        os.makedirs(out_dir, exist_ok=True)
        lines = resolve_lines(dataset, repo_dir)
        build_data(dataset, args.source, out_dir, tools_dir, lines)
        build_models(dataset, args.source, out_dir, lines)

    sys_dir = os.path.join(args.out, "system")
    os.makedirs(sys_dir, exist_ok=True)
    for f in SYSTEM_FILES:
        src = os.path.join(args.source, f)
        if os.path.exists(src):
            shutil.copy(src, sys_dir)

    # Derive the xyz-variant GEX from the published skb one (see the note at
    # SKB_GEX). Only the xyz GEX ships: it is the one that matches the delivered
    # data. The skb file is an input to this build, not a deliverable - shipping
    # it beside centre-referenced XYZ invites inverting with the wrong geometry.
    skb = os.path.join(args.source, SKB_GEX)
    if os.path.exists(skb):
        changed = derive_xyz_gex(skb, os.path.join(sys_dir, XYZ_GEX_OUT))
        print(f"\n  derived {XYZ_GEX_OUT} from the skb GEX - {len(changed)} line(s) changed:")
        for before, after in changed:
            print(f"    {before}  ->  {after}")
    print(f"\nsystem/: {len(os.listdir(sys_dir))} file(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
