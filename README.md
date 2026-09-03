# YmerFlow demo data

A small, ready-to-run **public benchmark** for airborne electromagnetic (AEM) processing and
inversion: real SkyTEM data, the published inversion of it, and everything needed to
reproduce that inversion yourself.

Two datasets, deliberately different shapes:

| | what | why |
|---|---|---|
| **`line_300901`** | one whole flight line, 8995 soundings at 10 Hz | run a pipeline end to end on something small |
| **`block`** | 26 adjacent lines over ~7 × 5 km, 76,389 soundings | anything needing neighbours — spatially constrained inversion, gridding, sections |

Each is laid out the same way — the survey data kept separate from somebody's inversion of it:

```
<dataset>/
  delivered/   <dataset>_delivered.xyz   as delivered by SkyTEM, 10 Hz, + .alc
  inversion/   <dataset>_dat.xyz         the data that went INTO the inversion
               <dataset>_mod.xyz         the recovered resistivity model
               <dataset>_syn.xyz         the forward response of that model
system/        the GEX, and a flight-line mask per district
```

**`delivered/` is the contractor's product, minimally processed** — navigation and drift
applied, but nothing stacked, culled or filtered, still at the full 10 Hz acquisition rate.
It is not the instrument raw (`.skb` / `.mat`), which is not published. Everything a
processing pipeline would do to it is still ahead of you, which is the point.

So you have the whole chain — input, what was inverted, the model, and what that model
predicts — not just a pile of soundings.

Only the `delivered` file carries an `.alc`: an ALC maps gates and channels, and a model
carries layers, so a model's would be an empty shell.

## The data

ENWRA 2018 AEM survey, eastern Nebraska. SkyTEM 304, dual moment, flown 28–30 June 2018.
The originals are published by the districts themselves — you do not have to take ours:
[LPN-NRD deliverables](https://www.dropbox.com/scl/fo/8lubs33q7s7ltg3t7unud/AIGf3RYEQqmNTKRdL5brRfU?dl=0&rlkey=5qiqfojn7g1ascvi2v7jsvt2d)
· [LPS-NRD deliverables](https://www.dropbox.com/scl/fo/9lla2b7u66cxrp7d9qy6d/AOOOqyrJcqgGmxiCQPYSV-k/Appendices/Appendix%203%20-%20Deliverables?dl=0&rlkey=may29av4fkyammg3g6ynpbimf)
· [LPN-NRD viewer](https://lpsnrd.maps.arcgis.com/apps/webappviewer/index.html?id=ac2d1aada438420492e1044472679b1c).
EPSG:32614 (WGS 84 / UTM zone 14N). Everything is derived from the districts' public
deliverables — see **[PROVENANCE.md](PROVENANCE.md)** for sources, exactly what was changed,
and how to check it.

`block/inversion/block_mod.xyz` **is** the published inversion: 220,272 resistivity values compared
against the ENWRA release, difference exactly zero. That is the point of the benchmark — you
can check your result against a model that was published independently of you.

## Getting it

```
python3 download.py
```

Or clone and use `data/` directly.

To rebuild from the original deliverables instead of trusting these files:

```
python3 tools/build_dataset.py --source /path/to/deliverables --out data
```

## Reading it

Aarhus Workbench XYZ throughout, so [`libaarhusxyz`](https://github.com/YmerFlow/libaarhusxyz)
reads it directly:

```python
import libaarhusxyz as lx

data  = lx.parse("data/line_300901/delivered/line_300901_delivered.xyz",
                 alcfile="data/line_300901/delivered/line_300901_delivered.alc")
model = lx.parse("data/line_300901/inversion/line_300901_mod.xyz")

model["layer_data"]["rho_i"].shape     # (531, 39) - soundings x layers
```

Dependencies are in `requirements.txt`. The only YmerFlow-stack dependency is `libaarhusxyz`;
this repository does not need a YmerFlow checkout to build or read its own data.

## Two GEX files — use the `_xyz` one to invert

`system/` holds two system descriptions for the same instrument:

- **`…_skb.gex`** — as published with the delivery. The system *as flown*: GPS, altimeter
  and inclinometer offsets from the frame centre, and the measured `GateFactor` per channel.
- **`…_xyz.gex`** — derived from it by the build. The delivered XYZ has **already had those
  corrections applied** — soundings are referenced to the frame centre and gates are scaled —
  so the xyz GEX zeroes the sensor offsets and sets `GateFactor` to 1.0, so nothing is applied
  twice. `RxCoilPosition` is unchanged in both: the receiver really is 13.25 m behind the frame
  centre, and the forward model needs that.

**Invert the delivered data with `…_xyz.gex`.** Using the skb one applies the GPS-to-centre
shift a second time. Nothing in the toolchain checks that a GEX and an XYZ belong together, so
this is a silent error if you get it wrong.

The derivation follows SkyTEM's own convention: a skb/xyz pair from another SkyTEM 304 survey
differs in exactly and only those keys. (That pair is not public and is not included here —
only the rule it demonstrates.)

## Two things worth knowing before you use it

**`tx_elevation`, not `Alt`.** The vendor's `Alt` column holds the transmitter's *elevation*
(≈ `DTM + Height`), not an altitude, and it is renamed here accordingly. Altitude is
referenced to the ground; elevation to the datum. The altitude — what a tilt/altitude filter
wants — is `Height`, 24–82 m. Pointing a filter at the wrong one discards every sounding, and
does so silently.

**39 layers, not 40.** Workbench exports carry a trailing halfspace layer with a resistivity
but no thickness. It is stripped here, matching the published product. If you compare against
a raw Workbench export you will be comparing 39 against 40, and everything will misalign.

## Licence

Code and documentation: **MIT** (see `LICENSE`).
Survey data: **not ours** — published by the Lower Platte North and Lower Platte South NRDs,
redistributed here with no further restrictions. Cite **ENWRA 2018**, not this repository.
