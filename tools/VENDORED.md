# Vendored code

## `aem_csv_to_xyz.py`

Copied **verbatim** (no edits) from the YmerFlow repository:

    YmerFlow/pending_tools/aem_csv_to_xyz.py

Vendored 2026-09-02 so this repository can rebuild its own data without a checkout
of YmerFlow. The file is byte-identical to its source, so `diff` against upstream
is meaningful — please keep it that way. Fixes belong upstream first, then get
re-copied here.

It is expected to move somewhere shared eventually (it is general-purpose, and its
own TODOs point that way); when it does, this copy should be replaced by a
dependency.

Provides:
  * `data_csv_to_xyz(csv, out)` - comma-separated AEM data -> Aarhus XYZ
    (space-separated, NaN -> `*`, case-insensitive column de-duplication)
  * `model_csv_to_xyz(csv, out, units, column_map, drop_columns)` - inversion
    model CSV -> Aarhus XYZ, with renaming to canonical libaarhusxyz names
