# Provenance

Every file in this repository is derived from the **public ENWRA 2018 AEM survey
deliverables**. Nothing here is original data. This document records where each input came
from, exactly what was done to it, and how to check that for yourself.

## The survey

| | |
|---|---|
| Survey | ENWRA 2018 airborne electromagnetic survey, eastern Nebraska |
| System | SkyTEM 304, dual moment (LM + HM), Z and X receiver components |
| Acquisition | **28–30 June 2018**, 10 Hz |
| Districts | Lower Platte North NRD (LPNNRD) and Lower Platte South NRD (LPSNRD) |
| CRS | EPSG:32614 — WGS 84 / UTM zone 14N |

One flight campaign, one system, flown across two natural resources districts and
**delivered separately by district**. The two deliveries overlap rather than partition: some
flight lines appear in both, with identical Fid and position. That is why each dataset below
draws from whichever delivery actually covers it, rather than from the district its name
suggests.

## Sources

Both districts publish their deliverables on Dropbox; LPNNRD also has an ArcGIS viewer.
The links are reproduced from the survey's own `readme.txt`.

**LPN-NRD**
- Viewer — <https://lpsnrd.maps.arcgis.com/apps/webappviewer/index.html?id=ac2d1aada438420492e1044472679b1c>
- Deliverables — <https://www.dropbox.com/scl/fo/8lubs33q7s7ltg3t7unud/AIGf3RYEQqmNTKRdL5brRfU?dl=0&rlkey=5qiqfojn7g1ascvi2v7jsvt2d>

**LPS-NRD**
- Deliverables — <https://www.dropbox.com/scl/fo/9lla2b7u66cxrp7d9qy6d/AOOOqyrJcqgGmxiCQPYSV-k/Appendices/Appendix%203%20-%20Deliverables?dl=0&rlkey=may29av4fkyammg3g6ynpbimf>

Files used:

| input | delivery | used for |
|---|---|---|
| `LPNNRD2018_EM_MAG_AUX.xyz` (2.5 GB) | LPN-NRD | `line_300901` delivered data |
| `LPSNRD2018_EM_MAG_AUX.XYZ` (1.8 GB) | LPS-NRD | `block` delivered data |
| `LPNLPS_SCI12i_MOD_{dat,inv,syn}.xyz` | SCI appendix | all models, both datasets |
| `20180823_304_DualWaveform_60Hz_skb.gex` | either | source for the derived xyz GEX (not shipped) |
| `20180613_446_NE304_{LPNNRD,LPSNRD}.lin` | both | flight-line masks |

The GEX shipped in both deliveries is **byte-identical** — one system, one description — so
`system/` carries a single copy.

**Two GEX variants.** The delivery publishes only the `_skb` GEX — the system as flown, with
GPS/altimeter/inclinometer offsets from the frame centre and the measured `GateFactor` per
channel. The delivered XYZ has already had those applied, so inverting it against the skb GEX
would apply them twice. `system/` therefore carries only a **derived `_xyz` GEX**: the skb
file with `GPSDifferentialPosition`, `GPSPosition`, `AltimeterPosition` and
`InclinometerPosition` set to zero and `GateFactor` set to 1.0 — nine lines changed, nothing
else, `RxCoilPosition` untouched. This is SkyTEM's own convention: a skb/xyz pair from a
different 304 survey differs in exactly and only those keys. That pair is private and is not
part of this repository; only the transformation it demonstrates is used. The pairing of a GEX with
an XYZ is part of the data's provenance, which is why only the matching variant is shipped and the derivation is stated here.

## What was done

1. **Line selection.** `line_300901` is one whole flight line. `block` is the 26 lines in
   `demo_lines.txt`, clipped to easting 693194–700199, northing 4549995–4555187.
2. **Format conversion.** The LPSNRD delivered data is a Geosoft CSV export —
   comma-delimited, alphabetically ordered columns, `Line NNNNNN` block markers — and the
   LPNNRD one is plain comma-delimited. `libaarhusxyz` reads with a separator of
   `,?[\s]+` (an optional comma *followed by whitespace*), so it cannot read either. Both
   are converted to whitespace-delimited Aarhus Workbench XYZ.
3. **One column renamed.** The vendor column `Alt` is **not an altitude**. It holds the
   transmitter's *elevation* — verified equal to `DTM + Height` to within 0.1 m over 3589
   soundings — and is renamed **`tx_elevation`**. Altitude is referenced to the ground;
   elevation to the datum. Shipping the vendor name would hand on a trap that has previously
   caused a processing pipeline to discard 100% of soundings. **No values are changed, and
   no column moves**, so the positional ALCs remain valid.
4. **Halfspace stripped from the models.** Workbench exports N layers where the deepest is an
   unbounded halfspace carrying a resistivity but no thickness. It is removed, matching the
   published product. Detection uses two signals — a short `dep_bot` relative to `dep_top`,
   and the last layer's median thickness against the one above it (computed from
   `dep_bot − dep_top`, ratio ≥ 3) — and prefers the geometric signal when they disagree,
   because column bookkeeping is convention-dependent while the geometry is the data.

Nothing else is altered. No filtering, no resampling, no reprojection, no gap-filling.

## How to verify

Re-run the derivation against your own download:

```
python3 tools/build_dataset.py --source /path/to/deliverables --out data
```

The strongest check is that **`block/inversion/block_mod.xyz` reproduces the published inversion
exactly**. Comparing it against `LPNNRD2018_AEM_SCI_INV_v1.xyz` over the same area:

- 5648 soundings × 39 layers on both sides
- all 5648 positions match to within 1 m
- across **220,272 resistivity values the difference is exactly zero**

So the model shipped here is not merely similar to the published one — it is the published
one, reached independently through this pipeline.

## Rights

**The survey data is not ours.** It was collected for ENWRA and published by the two
districts; this repository redistributes public subsets of it and imposes no further
restrictions. Cite the original survey — ENWRA 2018 — not this repository, when the data
itself is what you are using.

**The code and documentation are MIT** (see `LICENSE`), which covers `tools/`, this file, and
the README — not the survey data.

`tools/aem_csv_to_xyz.py` is vendored from the YmerFlow repository so this repository can
rebuild its own data without a YmerFlow checkout; see `tools/VENDORED.md`.
