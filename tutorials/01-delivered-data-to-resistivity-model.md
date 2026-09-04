# Tutorial 1 — From delivered data to a resistivity model

_Draft 2026-09-04. Written from the process schemas and the AEM26 validation runs, not yet
walked through click by click on ymerflow.earth — step names are the ones the process types
expose; parameter defaults are what those runs used. Mark anything that does not match what
you see._

**What you will do:** take one flight line as SkyTEM delivered it, process it, invert it, and
compare your model with the one the survey published. About 20 minutes of your time; the
inversion itself runs 5–15 minutes on the free tier.

**What you need:** from `line_300901/`, the delivered data and its ALC; from `system/`, the
xyz GEX. Get them with `python3 download.py --dataset line_300901/delivered` and
`--dataset system`, or from the release page.

| file | role |
|---|---|
| `skytem_as_delivered_line_300901.xyz` | 8,995 soundings at 10 Hz — the input |
| `skytem_as_delivered_line_300901.alc` | tells the importer which column is which |
| `system_skytem304_for_delivered_data.gex` | the SkyTEM 304 system, as it applies to delivered data |

## 1. Import

Create a process of type **Import SkyTEM data** (`import_skytem`). Upload the three files into
its fields:

- **XYZ Data File** → `skytem_as_delivered_line_300901.xyz`
- **GEX System File** → the `_xyz.gex`
- **ALC Allocation File** → `skytem_as_delivered_line_300901.alc`
- **Scale Factor** → `1e-12`. The delivered gates are in picovolts; the pipeline works in V/m².
- **EPSG Projection Code** → `32614`. The coordinates are WGS 84 / UTM zone 14N.

Run it. The output dataset should report 8,995 soundings, one flight line, and two channels —
`Gate_Ch01` with 28 gates (low moment) and `Gate_Ch02` with 37 (high moment). If the channel
count is one, the ALC did not apply; if the coordinates land in the wrong place on the map,
the EPSG is wrong.

**Why the `_xyz` GEX and not a `_skb` one.** The delivered data already has the GPS-to-frame-
centre shift and the gate scaling applied. The xyz GEX has those corrections neutralized so
they are not applied twice. Using a skb GEX here silently misplaces the receiver by 13 m.

## 2. Process — and bring the sounding count down

Create a **Process TEM data** (`process_tem`) process with the import as its input, and build
this chain. Every step exposes its parameters; the ones that matter are named.

1. **Apply GEX** (disable early gates) — honours `RemoveInitialGates=7` from the GEX: the
   first seven gates of each moment are transmitter turn-off and not invertible.
2. **STD error: Replace from GEX** — once per channel. Gives every datum an uncertainty from
   the GEX noise model. Without uncertainties the inversion has nothing to fit *to*.
3. **Tilt & altitude** cull — drops soundings with implausible frame tilt or altitude. Note
   the altitude column is `Height` (metres above ground); the vendor's `Alt` is an
   *elevation* and has been renamed `tx_elevation` in this data so you cannot pick it by
   accident.
4. **Moving-average filter** — this is the step that makes the free tier possible.
   - `target_spacing_m` = **30** → resamples the 10 Hz stream to one sounding per ~30 m.
     8,995 soundings over 19.7 km become roughly **650**. That is what the inversion sees.
   - `filter_dict`: leave the defaults (LM 3→5 soundings, HM 5→9) — they stack neighbours
     into each output sounding, which is where the noise reduction comes from.
   - `min_valid_fraction` = 0.35 (default).

   Skip this step and you will submit 8,995 soundings: a 2-hour, 24-CPU job that the free
   tier cannot finish. It is not a quality choice; it is the difference between a job that
   ends and one that is killed.
5. **Noise floor** / **Negative data** culls — optional; the defaults are conservative.
6. **Normalize for SimPEG** — required; converts units and layout for the inversion.

Run it. Check the output sounding count — it should be in the hundreds, not thousands — and
that both channels still have gates 8 onward active.

## 3. Invert

Create an **Invert TEM data** (`invert_tem`) process on the processed dataset. System:
**Dual moment TEM**. These are the AEM26 validation settings; they are a good starting point.

| group | parameter | value | why |
|---|---|---|---|
| gate filter | `start_lm` / `end_lm` | 5 / 28 | keep the usable low-moment window |
| | `start_hm` / `end_hm` | 10 / 32 | same for high moment |
| start model | `n_layer` | 39 | matches the published model — makes the comparison direct |
| | `thicknesses_type` | logspaced, min dz 1 m, top of last layer 400 m | |
| | `res` | 100 Ω·m | uniform start |
| regularization | `alpha_s` / `alpha_r` / `alpha_z` | 1e-4 / 1 / 1 | smooth-L2 |
| uncertainties | `std_data_override` | false | use the STDs from step 2.2 |
| | `std_data` | 0.03 | 3 % floor |
| directives | `max_iter` | **25** | see below |
| simulation | `parallel` / `n_cpu` | true / 8 | |

**Resources** — this is where jobs die. For ~650 soundings:

- **CPU 8, memory 4 Gi, deadline 45 min.** Measured: 753 soundings ran in 17 min at 16 CPU
  with a 1.2 GiB peak. Memory barely depends on sounding count; do not size it by soundings.
- `max_iter` 25 rather than the default 50: the misfit flattens by iteration 20–30 and the
  remaining iterations only cost time. The published-fit target still stops it early if it
  gets there.

Submit. Watch the log: you should see the Gauss–Newton iterations counting up with the
misfit (`rmse_d`) falling toward ~1.0.

## 4. Review

Open the output model in a section plot. Then compare against the published one:
`line_300901/inversion/inversion_resistivity_model_line_300901.xyz` — 39 layers, the same line, produced by the
survey contractor in Aarhus Workbench and published by the district.

What "good" looks like: the same stratigraphy — resistive near-surface, the conductive
layer at depth — at similar depths. Your resistivities will differ in detail; the published
model used different gate culling and regularization. What would be wrong: a model that is
uniform (nothing fit — check the uncertainties), or one that looks like the start model
(check `max_iter` actually ran), or structure that follows the flight line's altitude
(the altitude column is wrong).

## If it goes wrong

| symptom | cause | fix |
|---|---|---|
| import shows 1 channel | ALC not applied | re-upload the `.alc` in the ALC field |
| `22 gates of data but gate-time table yields 28` | wrong GEX for the data | this data wants the full-gate `_xyz` GEX |
| every sounding culled at step 2.3 | altitude column is an elevation | use `Height`, not `Alt`/`tx_elevation` |
| job killed at the deadline | too many soundings or deadline too short | step 2.4, and size from the sizing guide |
| uniform model | no uncertainties | step 2.2 ran? `std_data_override` false? |
