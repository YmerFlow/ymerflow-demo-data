#!/usr/bin/env python3
"""Extract selected flight lines - optionally clipped to a bounding box - from
large AEM XYZ files, by streaming.

The LPNNRD2018 delivery ships three header flavors and this handles all of them
without loading any file into memory:

  * **Workbench** - a block of ``/``-prefixed metadata lines followed by
    whitespace-delimited data, used by Aarhus Workbench model exports. The
    metadata block is preserved verbatim in the output: it carries the
    coordinate system, layer count, gate times and dummy value, without which
    the extract is not interpretable.
  * **comma-delimited** - the ENWRA processed-data and SCI deliverables.
  * **whitespace-delimited** - re-exports carrying a plain header row.

Streaming matters: the full processed-data file is ~2.5 GB and
``libaarhusxyz.parse`` reads a whole file into a DataFrame via
``pd.read_csv(engine='python')``, which is not viable at that size. Once
extracted the result is small enough to hand to libaarhusxyz normally.

Usage:
    python3 extract_line.py --lines 409001,409301 --out ../data SOURCE...
    python3 extract_line.py --lines-file lines.txt \\
        --bbox 693194 4549995 700199 4555187 --out ../data SOURCE...
"""

import argparse
import os
import re
import sys


# ---------------------------------------------------------------------------
# Configuration - defaults only; every value is overridable on the command line
# ---------------------------------------------------------------------------

DEFAULT_OUT_DIR = "data"
WORKBENCH_COMMENT_PREFIX = "/"

# Column names are matched case-insensitively, in order. Projected coordinates
# only - the geographic Lon/Lat columns are deliberately excluded so a bounding
# box is always interpreted in meters.
# "__E"/"__N" are the Geosoft export's UTM columns. Note that file also carries
# a bare "E" holding the same easting and no matching "N", so the doubled-
# underscore pair is the one to match - never a bare single letter.
X_COLUMN_CANDIDATES = ("X", "East_UTM_M", "E_UTM14N_m", "__E", "EASTING", "UTMX")
Y_COLUMN_CANDIDATES = ("Y", "North_UTM_M", "N_UTM14N_m", "__N", "NORTHING", "UTMY")

# The delivery spells the line column several ways - "LINE", "Line", "line",
# "Line_1" - and carries both a string form (L409001) and a numeric one.
LINE_COLUMN_PREFIX = "line"


# A Geosoft CSV export marks the start of each line's block with a bare
# "Line  160001" row that is structure, not data. Kept in the output (so the
# extract stays a valid file of the same format) but never parsed as a sounding.
GEOSOFT_LINE_MARKER = re.compile(r"^Line\s+(\S+)\s*$")


def detect_flavor(path):
    """Return (flavor, delimiter) by inspecting the head of the file.

    Four flavors appear in this delivery:

      ``workbench``  ``/`` metadata block, whitespace-delimited data, column
                     names on the last ``/`` line (Aarhus Workbench exports).
      ``geosoft``    ``/`` metadata block, **comma**-delimited data, column
                     names on a ``/`` line that is itself comma-separated, and
                     ``Line NNNNNN`` marker rows between blocks (the LPSNRD
                     processed-data export, from a Geosoft database).
      ``tabular``    a plain header row, comma-delimited.
      ``tabular``    a plain header row, whitespace-delimited.

    ``delimiter`` is ``','`` or ``None`` (whitespace), matching ``str.split``.
    """
    with open(path, "r", errors="replace") as fh:
        head = [fh.readline() for _ in range(40)]
    for raw in head:
        if not raw.strip():
            continue
        if raw.startswith(WORKBENCH_COMMENT_PREFIX):
            # Distinguish workbench from geosoft by whether any comment line
            # looks like a comma-separated column header.
            for line in head:
                if line.startswith(WORKBENCH_COMMENT_PREFIX) and line.count(",") >= 5:
                    return "geosoft", ","
            return "workbench", None
        return "tabular", ("," if "," in raw else None)
    raise ValueError(f"{path} appears to be empty")


def find_column(names, candidates, what, path):
    """Index of the first column matching ``candidates``, case-insensitively."""
    lowered = [n.strip().lower() for n in names]
    for candidate in candidates:
        if candidate.lower() in lowered:
            return lowered.index(candidate.lower())
    raise ValueError(
        f"{os.path.basename(path)}: no {what} column; looked for {candidates} "
        f"in {names[:10]}"
    )


def find_line_column(names, path, sample_row=None):
    """Index of the line column, preferring a purely numeric one.

    Preferring the numeric form keeps line ids comparable across files, which
    matters when outputs from different deliverables are overlaid.
    """
    candidates = [idx for idx, name in enumerate(names)
                  if name.strip().lower().startswith(LINE_COLUMN_PREFIX)]
    if not candidates:
        raise ValueError(f"{os.path.basename(path)}: no line column in {names[:10]}")
    if sample_row:
        for idx in candidates:
            if idx < len(sample_row) and sample_row[idx].strip().lstrip("L").isdigit():
                if sample_row[idx].strip().isdigit():
                    return idx
    return candidates[0]


def read_header(path, flavor, delimiter):
    """Return (column_names, header_text_to_emit).

    For Workbench files the emitted header is the whole ``/`` block; for the
    others it is the single header row.
    """
    if flavor == "geosoft":
        # File-level header runs up to and including the comma-separated column
        # names. Everything after it - "//Flight", "//Date", "Line NNNNNN" - is
        # per-block preamble that repeats, and belongs with its own block rather
        # than at the top of the file.
        block, csv_names = [], None
        with open(path, "r", errors="replace") as fh:
            for raw in fh:
                if not raw.startswith(WORKBENCH_COMMENT_PREFIX):
                    break
                if raw.startswith("//"):
                    break
                block.append(raw)
                if raw.count(",") >= 5:
                    csv_names = raw.lstrip("/").rstrip("\n").split(",")
                    break
        return [n.strip() for n in (csv_names or [])], "".join(block)

    if flavor == "workbench":
        block, last = [], None
        with open(path, "r", errors="replace") as fh:
            for raw in fh:
                if raw.startswith(WORKBENCH_COMMENT_PREFIX):
                    block.append(raw)
                    last = raw
                    continue
                break
        names = last.lstrip("/").split() if last else []
        return names, "".join(block)

    with open(path, "r", errors="replace") as fh:
        header = fh.readline()
    return [n.strip() for n in header.rstrip("\n").split(delimiter)], header


def iter_data_rows(path, flavor, delimiter):
    """Yield (raw_text, fields, marker) for each data row, one at a time.

    ``marker`` is the most recent Geosoft ``Line NNNNNN`` block marker, or None.
    It is carried alongside so a caller writing a subset can re-emit the marker
    for each line it keeps, leaving the output a valid file of the same format.
    """
    with open(path, "r", errors="replace") as fh:
        if flavor == "geosoft":
            preamble, pending = None, []
            for raw in fh:
                stripped = raw.strip()
                if not stripped:
                    continue
                if raw.startswith("//"):
                    pending.append(raw)      # "//Flight", "//Date" for the next block
                    continue
                if raw.startswith(WORKBENCH_COMMENT_PREFIX):
                    continue                 # file-level header, already emitted
                if GEOSOFT_LINE_MARKER.match(stripped):
                    pending.append(raw)
                    preamble = "".join(pending)
                    pending = []
                    continue
                yield raw, stripped.split(delimiter), preamble
        elif flavor == "workbench":
            in_header = True
            for raw in fh:
                if in_header and raw.startswith(WORKBENCH_COMMENT_PREFIX):
                    continue
                in_header = False
                yield raw, raw.split(), None
        else:
            fh.readline()
            for raw in fh:
                if raw.strip():
                    yield raw, raw.rstrip("\n").split(delimiter), None


def extract(src, out_dir, lines=None, bbox=None, suffix=None, plain_csv=False):
    """Copy the header plus every row matching ``lines`` and/or ``bbox``.

    ``lines`` is a set of line-id strings (matched bare or with a leading L);
    ``bbox`` is (xmin, ymin, xmax, ymax) in the file's projected CRS. Either may
    be None, in which case that filter is not applied.
    """
    flavor, delimiter = detect_flavor(src)
    names, header_text = read_header(src, flavor, delimiter)

    rows = iter_data_rows(src, flavor, delimiter)
    try:
        first = next(rows)
    except StopIteration:
        first = None

    iline = find_line_column(names, src, first[1] if first else None)
    ix = iy = None
    if bbox:
        ix = find_column(names, X_COLUMN_CANDIDATES, "X", src)
        iy = find_column(names, Y_COLUMN_CANDIDATES, "Y", src)

    targets = set()
    for line in (lines or ()):
        targets.add(str(line))
        targets.add(f"L{line}")

    stem, ext = os.path.splitext(os.path.basename(src))
    if plain_csv:
        ext = ".csv"
    dst = os.path.join(out_dir, f"{stem}_{suffix or 'subset'}{ext}")
    tmp = dst + ".partial"

    written, kept_lines = 0, set()
    last_marker_written = None
    import itertools
    try:
        with open(tmp, "w") as fout:
            # A plain CSV - one header row, no comment block, no block markers -
            # is what pending_tools/aem_csv_to_xyz.py expects as its input.
            fout.write(",".join(names) + "\n" if plain_csv else header_text)
            for raw, fields, marker in itertools.chain([first] if first else [], rows):
                if iline >= len(fields):
                    continue
                line_id = fields[iline].strip()
                if targets and line_id not in targets:
                    continue
                if bbox:
                    if max(ix, iy) >= len(fields):
                        continue
                    try:
                        x, y = float(fields[ix]), float(fields[iy])
                    except ValueError:
                        continue
                    if not (bbox[0] <= x <= bbox[2] and bbox[1] <= y <= bbox[3]):
                        continue
                # Re-emit the Geosoft block marker whenever the kept rows move
                # to a new line, so the subset keeps the source file's structure.
                if not plain_csv and marker is not None and marker != last_marker_written:
                    fout.write(marker if marker.endswith("\n") else marker + "\n")
                    last_marker_written = marker
                if plain_csv:
                    fout.write(",".join(f.strip() for f in fields) + "\n")
                else:
                    fout.write(raw if raw.endswith("\n") else raw + "\n")
                written += 1
                kept_lines.add(line_id.lstrip("L"))
    except Exception:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise

    if written == 0:
        os.remove(tmp)
        print(f"  {os.path.basename(src)}: no matching rows - nothing written")
        return None

    os.replace(tmp, dst)
    size_mb = os.path.getsize(dst) / (1024 * 1024)
    print(f"  {os.path.basename(src)}: {written} soundings across "
          f"{len(kept_lines)} line(s), {size_mb:.1f} MB ({flavor})")
    return dst


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("sources", nargs="+", help="XYZ file(s) to extract from")
    parser.add_argument("--lines", help="comma-separated line numbers")
    parser.add_argument("--lines-file", help="file with one line number per line")
    parser.add_argument("--bbox", nargs=4, type=float,
                        metavar=("XMIN", "YMIN", "XMAX", "YMAX"),
                        help="clip to this box, in the file's projected CRS")
    parser.add_argument("--out", default=DEFAULT_OUT_DIR,
                        help=f"output directory (default: {DEFAULT_OUT_DIR})")
    parser.add_argument("--suffix", help="output filename suffix (default: subset)")
    parser.add_argument("--plain-csv", action="store_true",
                        help="emit a plain CSV (one header row, no comment block or "
                             "block markers) for pending_tools/aem_csv_to_xyz.py")
    args = parser.parse_args(argv)

    lines = []
    if args.lines:
        lines += [t.strip() for t in args.lines.split(",") if t.strip()]
    if args.lines_file:
        with open(args.lines_file) as fh:
            lines += [t.strip() for t in fh if t.strip() and not t.startswith("#")]
    if not lines and not args.bbox:
        parser.error("give --lines, --lines-file and/or --bbox")

    os.makedirs(args.out, exist_ok=True)
    what = []
    if lines:
        what.append(f"{len(lines)} line(s)")
    if args.bbox:
        what.append("bbox %g..%g E, %g..%g N" % (args.bbox[0], args.bbox[2],
                                                 args.bbox[1], args.bbox[3]))
    print(f"Extracting {' + '.join(what)} from {len(args.sources)} file(s):")

    results = [extract(s, args.out, lines or None, args.bbox, args.suffix,
                       plain_csv=args.plain_csv)
               for s in args.sources]
    ok = [r for r in results if r]
    print(f"\n{len(ok)}/{len(results)} file(s) produced output")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
