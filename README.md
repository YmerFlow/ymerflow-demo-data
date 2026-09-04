# YmerFlow demo data

A small, ready-to-run **public benchmark** for airborne electromagnetic (AEM) processing and
inversion: real SkyTEM data, the published inversion of it, and everything needed to
reproduce that inversion yourself.

Two datasets, deliberately different shapes:

| | what | why |
|---|---|---|
| **`line_300901`** | one whole flight line, 8995 soundings at 10 Hz | run a pipeline end to end on something small |
| **`block`** | 26 adjacent lines over ~7 × 5 km, 76,389 soundings | anything needing neighbours — spatially constrained inversion, gridding, sections |

> ## ⚠️ The "as delivered" data must be PROCESSED before it is inverted
>
> `skytem_as_delivered_*.xyz` is SkyTEM's 10 Hz product: **8,995 soundings on the single line.**
> Inverting it as-is takes **2+ hours at 24 CPU** and is far outside a free-tier budget — the
> job will be killed unfinished and you will have paid for nothing. Run `process_tem` first with
> the **moving-average filter at `target_spacing_m` ≈ 30 m**, which stacks it to ~650 soundings.
> Tutorial 1 walks through it. The `agf_inversion/` files are *already* stacked — that is what
> AGF inverted — and are the reference to compare against, not a second input.

Each dataset is laid out the same way — the survey data kept separate from AGF's inversion of it:

```
<dataset>/
  as_delivered/   skytem_as_delivered_<dataset>.xyz + .alc   SkyTEM's 10 Hz product. PROCESS FIRST.
  agf_inversion/  inversion_input_data_<dataset>.xyz          the soundings AGF actually inverted
                  inversion_resistivity_model_<dataset>.xyz   AGF's published model - the benchmark
                  inversion_forward_response_<dataset>.xyz    what that model predicts the data to be
system/           system_skytem304_for_delivered_data.gex     the GEX to import the delivered data with
                  *.lin                                       flight-line masks (not used by the import)
```

**Two datasets, two releases.** `python3 download.py` fetches **only the single line** and the
system files. The 26-line block is a separate release, fetched only with `--dataset block` or
`--all`, so nobody on a small plan downloads 76,389 soundings and tries to invert them.

**`as_delivered/` is the contractor's product, minimally processed** — navigation and drift
applied, but nothing stacked, culled or filtered, still at the full 10 Hz acquisition rate.
It is not the instrument raw (`.skb` / `.mat`), which is not published. Everything a
processing pipeline would do to it is still ahead of you, which is the point.

So you have the whole chain — input, what was inverted, the model, and what that model
predicts — not just a pile of soundings.

## What each file is, and what to do with it

| file | what it is | what consumes it |
|---|---|---|
| `as_delivered/skytem_as_delivered_*.xyz` + `.alc` | SkyTEM's minimally processed 10 Hz data, one row per sounding, LM and HM gates in one row | **Import** in YmerFlow (`import_skytem`: XYZ + this ALC + the GEX from `system/`), then **process — including the averaging step —** then **invert** |
| `system/system_skytem304_for_delivered_data.gex` | the system description matching the delivered data | Import, with the file above |
| `agf_inversion/inversion_input_data_*.xyz` | the soundings that went **into** AGF's inversion, *after* their culling and stacking — **two rows per sounding** (one per moment, `segment` column), as Aarhus Workbench exports them | Reference: what a good processing run should leave you with. See the note below before trying to import it |
| `agf_inversion/inversion_resistivity_model_*.xyz` | AGF's published resistivity model, 39 layers | **Compare** your own inverted model against it — this is the benchmark |
| `agf_inversion/inversion_forward_response_*.xyz` | the forward response of that model, same two-rows-per-sounding layout | Check a forward calculation, or the data fit the published model achieved |

Only the as-delivered file carries an `.alc`: an ALC maps gates and channels, and a model
carries layers, so a model's would be an empty shell.

**About importing `inversion_input_data` directly.** It is not a drop-in input. Workbench writes one row per
moment per sounding, and the import expects one row per sounding with both moments across
it; the culled gate count (22 LM / 29 HM) also needs a GEX with matching `NoGates`, not the
full-gate one in `system/`. Inverting it is possible — the published comparison figure was
made that way — but it takes a de-interleaving step and a gate-matched GEX that are not in
this repository yet. Until they are, treat the inversion input as a reference product, and run the pipeline
from `as_delivered/`.

## Which dataset for which job — read this before you invert anything

These are measured runs on YmerFlow's default cluster, not estimates:

| dataset | soundings | a full inversion takes | request |
|---|---:|---|---|
| **`line_300901`** | 8,995 | **~2 h 20 m** at 24 CPU, peak RAM 4 GiB | 24 CPU / 12 Gi / 3 h deadline |
| **`block`** | 76,389 | **do not invert as one job** — invert per line | — |

**If you are on a free or small plan, neither of these is your first job.** A single short
line is: a few minutes at 8–16 CPU / 4 Gi. Memory barely grows with sounding count; runtime
does, faster than linearly, and it is dominated by the 50 Gauss-Newton iterations most runs
use whether or not they have converged. Set the deadline from the table with margin — a job
killed at iteration 48 is billed and gives you nothing.

## The data

ENWRA 2018 AEM survey, eastern Nebraska. SkyTEM 304, dual moment, flown 28–30 June 2018.
The originals are published by the districts themselves — you do not have to take ours:
[LPN-NRD deliverables](https://www.dropbox.com/scl/fo/8lubs33q7s7ltg3t7unud/AIGf3RYEQqmNTKRdL5brRfU?dl=0&rlkey=5qiqfojn7g1ascvi2v7jsvt2d)
· [LPS-NRD deliverables](https://www.dropbox.com/scl/fo/9lla2b7u66cxrp7d9qy6d/AOOOqyrJcqgGmxiCQPYSV-k/Appendices/Appendix%203%20-%20Deliverables?dl=0&rlkey=may29av4fkyammg3g6ynpbimf)
· [LPN-NRD viewer](https://lpsnrd.maps.arcgis.com/apps/webappviewer/index.html?id=ac2d1aada438420492e1044472679b1c).
EPSG:32614 (WGS 84 / UTM zone 14N). Everything is derived from the districts' public
deliverables — see **[PROVENANCE.md](PROVENANCE.md)** for sources, exactly what was changed,
and how to check it.

`block/agf_inversion/inversion_resistivity_model_block.xyz` **is** the published inversion: 220,272 resistivity values compared
against the ENWRA release, difference exactly zero. That is the point of the benchmark — you
can check your result against a model that was published independently of you.

## Tutorials

Three walkthroughs in [`tutorials/`](tutorials/):

1. [Delivered data → resistivity model](tutorials/01-delivered-data-to-resistivity-model.md) — import, process (including the averaging step that keeps the inversion inside a free-tier budget), invert, compare with the published model.
2. [Inversion export → resistivity model](tutorials/02-inversion-export-to-resistivity-model.md) — outline; blocked on the gate-matched GEX.
3. [Sizing a job so it finishes](tutorials/03-sizing-a-job.md) — CPU, memory and deadline from measured runs.

## Getting it

```
python3 download.py                 # the single line + system files
python3 download.py --dataset block # the 26-line block, if you really want it
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

data  = lx.parse("data/line_300901/as_delivered/skytem_as_delivered_line_300901.xyz",
                 alcfile="data/line_300901/as_delivered/skytem_as_delivered_line_300901.alc")
model = lx.parse("data/line_300901/agf_inversion/inversion_resistivity_model_line_300901.xyz")

model["layer_data"]["rho_i"].shape     # (531, 39) - soundings x layers
```

Dependencies are in `requirements.txt`. The only YmerFlow-stack dependency is `libaarhusxyz`;
this repository does not need a YmerFlow checkout to build or read its own data.

## The GEX is the xyz variant — on purpose

`system/` ships **one** system description, `system_skytem304_for_delivered_data.gex`. The delivery only publishes the
`_skb` GEX — the system *as flown*, with GPS/altimeter/inclinometer offsets from the frame
centre and the measured `GateFactor` per channel. But the delivered XYZ has **already had
those corrections applied**: soundings are referenced to the frame centre and gates are
scaled. Inverting it against the skb GEX applies them a second time, silently.

So the build derives the xyz GEX from the published skb one: sensor-position offsets zeroed,
`GateFactor` set to 1.0, everything else — gate times, waveforms, loop geometry,
`RxCoilPosition` — untouched. That is SkyTEM's own convention for the two variants. The skb
file is an input to `tools/build_dataset.py`, not a deliverable; if you want it, it is in the
district's Dropbox (see PROVENANCE).

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
