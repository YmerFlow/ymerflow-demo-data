#!/usr/bin/env python3
"""Write a LINE shapefile (one LineString per flight line) from an AEM XYZ file.

Deliberately not a point shapefile: the output carries one feature per flight
line, tracing the sounding positions in acquisition order, for QC and mapping.

Handles the three header flavors in the LPNNRD2018 delivery via
``extract_line.detect_flavor``:

  * Workbench  - ``/``-prefixed metadata block, whitespace-delimited data. The
    last ``/`` line names the columns, and the metadata block also declares the
    coordinate system, so the EPSG is read from the file rather than assumed.
  * comma-delimited  - ENWRA processed-data and SCI deliverables.
  * whitespace-delimited  - re-exports with a plain header row.

Usage:
    python3 xyz_to_line_shapefile.py --out ../shp ../data/*.xyz
"""

import argparse
import os
import re
import sys

from extract_line import detect_flavor, WORKBENCH_COMMENT_PREFIX


# ---------------------------------------------------------------------------
# Configuration - defaults only; overridable on the command line
# ---------------------------------------------------------------------------

# Fallback CRS for files that do not declare one. LPNNRD2018 is WGS 84 UTM 14N;
# the Workbench exports state this in their header and it is read from there in
# preference to this default.
DEFAULT_EPSG = 32614
DEFAULT_OUT_DIR = "shp"

# Coordinate column names seen across the three flavors, matched
# case-insensitively and in order. Projected coordinates only - the geographic
# Lon/Lat columns are deliberately not candidates, so the output is always in a
# metric CRS and reported lengths are in meters.
X_COLUMN_CANDIDATES = ("X", "East_UTM_M", "E_UTM14N_m", "EASTING", "UTMX")
Y_COLUMN_CANDIDATES = ("Y", "North_UTM_M", "N_UTM14N_m", "NORTHING", "UTMY")

LINE_COLUMN_PREFIX = "line"

# Line ids that are not real flight lines. Both appear in this delivery and both
# produce a nonsense feature if kept: rows with a blank line id (2450 of them in
# the public SCI) and Workbench's "0" sentinel for unassigned soundings. Left in,
# each becomes one absurd polyline stitching scattered points across the whole
# survey - the 60 km and 23 km "steps" seen on a first pass were exactly this.
EXCLUDED_LINE_IDS = ("", "0")

# A sounding-to-sounding step larger than this suggests the row order does not
# reflect the flight path - a gap, a concatenation, or an unsorted file.
SUSPICIOUS_STEP_M = 500.0

EPSG_IN_HEADER = re.compile(r"epsg[:\s]*(\d{4,6})", re.IGNORECASE)


def _scan_workbench_header(path):
    """Return (column_names, epsg_or_None) without reading the data block."""
    names, epsg, last_header = None, None, None
    with open(path, "r", errors="replace") as fh:
        for raw in fh:
            if raw.startswith(WORKBENCH_COMMENT_PREFIX):
                match = EPSG_IN_HEADER.search(raw)
                if match:
                    epsg = int(match.group(1))
                last_header = raw
                continue
            # The final '/' line before the data names the columns.
            names = last_header.lstrip("/").split() if last_header else []
            break
    return names or [], epsg


def _iter_rows(path, flavor, delimiter):
    """Yield each data row as a list of fields, one row at a time.

    Streaming rather than materializing: the full processed-data file is 2.5 GB
    across ~130 columns, and holding every field of every row would need tens of
    gigabytes. Callers keep only the few columns they need.
    """
    with open(path, "r", errors="replace") as fh:
        if flavor == "workbench":
            in_header = True
            for raw in fh:
                if in_header and raw.startswith(WORKBENCH_COMMENT_PREFIX):
                    continue
                in_header = False
                yield raw.split()
        else:
            fh.readline()          # discard the header row
            for raw in fh:
                if raw.strip():
                    yield raw.rstrip("\n").split(delimiter)


def _find_column(names, candidates, what, path):
    lowered = [n.lower() for n in names]
    for candidate in candidates:
        if candidate.lower() in lowered:
            return lowered.index(candidate.lower())
    raise ValueError(
        f"{os.path.basename(path)}: no {what} column; looked for {candidates} "
        f"in {names[:10]}"
    )


def _find_line_column(names, path, sample_row=None):
    """Index of the line column, preferring a purely numeric one.

    The ENWRA files carry both a string form (``L409001``) and a numeric form
    (``409001``). Preferring the numeric one keeps line ids comparable across
    files, which matters when the outputs are overlaid to inspect coverage.
    """
    candidates = [idx for idx, name in enumerate(names)
                  if name.strip().lower().startswith(LINE_COLUMN_PREFIX)]
    if not candidates:
        raise ValueError(f"{os.path.basename(path)}: no line column in {names[:10]}")
    if sample_row:
        for idx in candidates:
            if idx < len(sample_row) and sample_row[idx].strip().isdigit():
                return idx
    return candidates[0]


def build_lines(path, default_epsg=DEFAULT_EPSG):
    """Return (GeoDataFrame of LineStrings, epsg) for one XYZ file.

    Row order is preserved as acquisition order. The caller is warned rather
    than silently corrected if that order produces an implausible path.
    """
    from shapely.geometry import LineString
    import geopandas as gpd

    flavor, delimiter = detect_flavor(path)
    if flavor == "workbench":
        names, epsg = _scan_workbench_header(path)
    else:
        with open(path, "r", errors="replace") as fh:
            names = [n.strip() for n in fh.readline().rstrip("\n").split(delimiter)]
        epsg = None
    epsg = epsg or default_epsg

    rows = _iter_rows(path, flavor, delimiter)
    try:
        first = next(rows)
    except StopIteration:
        first = None

    ix = _find_column(names, X_COLUMN_CANDIDATES, "X", path)
    iy = _find_column(names, Y_COLUMN_CANDIDATES, "Y", path)
    iline = _find_line_column(names, path, first)

    # Group coordinates by line id, preserving file order within each line.
    # Only the coordinates are retained, so memory scales with sounding count
    # rather than with file size.
    by_line, skipped, excluded = {}, 0, 0
    import itertools
    for fields in itertools.chain([first] if first else [], rows):
        if max(ix, iy, iline) >= len(fields):
            skipped += 1
            continue
        line_id = fields[iline].strip()
        if line_id in EXCLUDED_LINE_IDS:
            excluded += 1
            continue
        try:
            xy = (float(fields[ix]), float(fields[iy]))
        except ValueError:
            skipped += 1
            continue
        by_line.setdefault(line_id, []).append(xy)

    records = []
    for line_id, coords in by_line.items():
        # Consecutive duplicate positions make a zero-length segment, which
        # some GIS readers reject; collapse them.
        deduped = [coords[0]]
        for xy in coords[1:]:
            if xy != deduped[-1]:
                deduped.append(xy)
        if len(deduped) < 2:
            print(f"    line {line_id}: only {len(deduped)} distinct position(s) - skipped")
            continue

        geom = LineString(deduped)
        steps = [((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5
                 for a, b in zip(deduped, deduped[1:])]
        max_step = max(steps)
        records.append({
            "line": line_id,
            "n_sound": len(coords),
            "length_m": round(geom.length, 1),
            "max_step_m": round(max_step, 1),
            "simple": bool(geom.is_simple),
            "source": os.path.basename(path),
            "geometry": geom,
        })

    # Summarize rather than printing per line: these files hold hundreds.
    n_crossing = sum(1 for r in records if not r["simple"])
    n_jumpy = sum(1 for r in records if r["max_step_m"] > SUSPICIOUS_STEP_M)
    if n_crossing:
        worst = sorted((r for r in records if not r["simple"]),
                       key=lambda r: -r["n_sound"])[:5]
        # Reported, not corrected: re-ordering soundings is a judgement call.
        # Re-sorting on recorded acquisition time usually resolves it, since an
        # aircraft occupies one position at a time and so cannot fold back on
        # itself the way a purely geometric sort can.
        print(f"    {n_crossing} line(s) self-cross in file order "
              f"(e.g. {', '.join(str(r['line']) for r in worst)}) - "
              f"row order may not follow the flight path")
    if n_jumpy:
        worst = sorted((r for r in records if r["max_step_m"] > SUSPICIOUS_STEP_M),
                       key=lambda r: -r["max_step_m"])[:5]
        print(f"    {n_jumpy} line(s) with a step > {SUSPICIOUS_STEP_M:.0f} m "
              f"(largest {worst[0]['max_step_m']:.0f} m on line {worst[0]['line']}) - "
              f"gaps or unsorted rows")
    if excluded:
        print(f"    {excluded} row(s) dropped - line id in {EXCLUDED_LINE_IDS} "
              f"(blank or Workbench sentinel, not real flight lines)")
    if skipped:
        print(f"    {skipped} row(s) skipped - short or non-numeric coordinates")

    return gpd.GeoDataFrame(records, crs=f"EPSG:{epsg}"), epsg


def convert(path, out_dir, default_epsg=DEFAULT_EPSG):
    gdf, epsg = build_lines(path, default_epsg)
    if gdf.empty:
        print(f"  {os.path.basename(path)}: no lines built - nothing written")
        return None

    stem = os.path.splitext(os.path.basename(path))[0]
    dst = os.path.join(out_dir, f"{stem}_lines.shp")
    gdf.to_file(dst)

    total_km = gdf["length_m"].sum() / 1000.0
    print(f"  {os.path.basename(path)}: {len(gdf)} line(s), {total_km:.2f} line-km, EPSG:{epsg}")
    print(f"    -> {dst}")
    return dst


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("sources", nargs="+", help="XYZ file(s) to convert")
    parser.add_argument("--out", default=DEFAULT_OUT_DIR,
                        help=f"output directory (default: {DEFAULT_OUT_DIR})")
    parser.add_argument("--epsg", type=int, default=DEFAULT_EPSG,
                        help=f"CRS for files that do not declare one "
                             f"(default: {DEFAULT_EPSG})")
    args = parser.parse_args(argv)

    os.makedirs(args.out, exist_ok=True)
    print(f"Writing line shapefiles for {len(args.sources)} file(s):")
    written = [convert(src, args.out, args.epsg) for src in args.sources]
    ok = [w for w in written if w]
    print(f"\n{len(ok)}/{len(written)} shapefile(s) written")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
