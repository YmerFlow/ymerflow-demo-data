# Tutorial 1 — From delivered data to a resistivity model

**What you will do:** take one flight line as SkyTEM delivered it, process it, invert it, and
compare your model with the one the survey published. About 20 minutes of your time; the
inversion itself runs 5–15 minutes on the free tier.

**What you need:** the delivered data and its ALC from `line_300901/as_delivered/`, and the
GEX from `system/`. `python3 download.py` fetches exactly these; they are also on the
release page.

| file | role |
|---|---|
| `skytem_as_delivered_line_300901.xyz` | 8,995 soundings at 10 Hz — the input |
| `skytem_as_delivered_line_300901.alc` | tells the importer which column is which |
| `system_skytem304_for_delivered_data.gex` | the SkyTEM 304 system, as it applies to delivered data |

## 1. Import

Create a process of type **Import SkyTEM data** (`import_skytem`). Upload the three files into
its fields:

- **XYZ Data File** → `skytem_as_delivered_line_300901.xyz`
- **GEX System File** → `system_skytem304_for_delivered_data.gex`
- **ALC Allocation File** → `skytem_as_delivered_line_300901.alc`
- **Scale Factor** → `1e-12`. The delivered gates are in pV/(A m⁴); the pipeline works in V/(A m⁴).
- **EPSG Projection Code** → `32614`. The coordinates are WGS 84 / UTM zone 14N.

Run it. The output dataset reports 8,995 soundings, one flight line, and two channels —
`Gate_Ch01` with 28 gates (low moment) and `Gate_Ch02` with 37 (high moment), the first seven
of each blank because SkyTEM removes them before delivery. If the channel count is one, the ALC
did not apply; if the soundings land in the wrong place on the map, the EPSG is wrong.

**Why this GEX and not the delivery's `_skb` one.** The delivered data already has the
GPS-to-frame-centre shift and the gate scaling applied. This GEX has those corrections
neutralized so they are not applied twice. Using a skb GEX here silently misplaces the receiver
by 13 m.

## 2. Process — and bring the sounding count down

Create a **Process TEM data** (`process_tem`) process with the import as its input, and build
this chain. Every step exposes its parameters; the ones that matter are named.

1. **Apply gex** — disables the first `RemoveInitialGates` gates of each moment (7 on the 304),
   as the system description declares. They are transmitter turn-off and not invertible.
2. **Correct data and tilt for 1D** — uses the delivered `TxPitch` and `TxRoll` to correct the
   data for frame tilt.
3. **Disable soundings by tilt and altitude** — drops soundings with implausible frame tilt or
   altitude. The altitude column is **`TxAltitude`**, height above ground (28–56 m on this
   line). The vendor's `Alt` column is an *elevation* and has been renamed `tx_elevation` in
   this data so you cannot pick it by accident.
4. **STD error: Replace from GEX** — once per channel. Gives every datum an uncertainty from
   the GEX noise model. Without uncertainties the inversion has nothing to fit *to*.
5. **Moving average filter** — this is the step that makes the free tier possible.
   - `target_spacing_m` = **30** → resamples the 10 Hz stream to one sounding per ~30 m.
     8,995 soundings over 19.7 km become roughly **650**. That is what the inversion sees.
   - `filter_dict`: the widths stack neighbours into each output sounding, which is where the
     noise reduction comes from. Narrower windows keep narrow targets; wider ones are quieter.
   - `min_valid_fraction` = 0.35.

   Skip this step and you will submit 8,995 soundings: a 2-hour, 24-CPU job that the free
   tier cannot finish. It is not a quality choice; it is the difference between a job that
   ends and one that is killed.
6. **Disable gates by noise floor** and **by negative data** — optional; the defaults are
   conservative.

Run it. Check the output sounding count — it should be in the hundreds, not thousands — and
that both channels still have gates 8 onward active.

## 3. Invert

Create an **Invert TEM data** (`invert_tem`) process on the processed dataset. System:
**Dual moment TEM**. A good starting point:

| group | parameter | value | why |
|---|---|---|---|
| gate filter | `start_lm` / `end_lm` | 7 / 28 | the GEX's `RemoveInitialGates` and `NoGates` for LM; indices are 0-based |
| | `start_hm` / `end_hm` | 7 / 37 | same for HM |
| start model | `n_layer` | 40 | the published model's discretization (it shows 39 because the halfspace is stripped before release) |
| | `thicknesses_type` | logspaced, minimum 1 m, top of last layer 350 m | same |
| | `res` | 100 Ω·m | uniform start |
| regularization | `alpha_s` / `alpha_r` / `alpha_z` | 1e-4 / 1 / 1 | smooth-L2 |
| uncertainties | `std_data_override` | false | use the STDs from step 2.4 |
| | `std_data` | 0.03 | 3 % floor |
| directives | `max_iter` | **25** | see below |
| simulation | `parallel` / `n_cpu` | true / 8 | |

**Resources** — this is where jobs die. For ~650 soundings:

- **CPU 8, memory 4 Gi, deadline 45 min.** Measured: 753 soundings ran in 17 min at 16 CPU
  with a 1.2 GiB peak. Memory barely depends on sounding count; do not size it by soundings.
- `max_iter` 25 rather than the default 50: the misfit flattens by iteration 20–30 and the
  remaining iterations only cost time.

Submit. Watch the log: you should see the Gauss–Newton iterations counting up with the
misfit (`rmse_d`) falling toward ~1.0.

## 4. Review

Open the output model in a section plot. Then compare against the published one,
`line_300901/agf_inversion/inversion_resistivity_model_line_300901.xyz` — 39 layers, the same
line, produced by the survey contractor in Aarhus Workbench and published by the district.

What "good" looks like: the same layering at similar depths. Your resistivities will differ
in detail; the published model used different culling, stacking and regularization, and the
early gates are modelled differently (see Tutorial 2, *See it done*). What would be wrong: a
model that is uniform (nothing fit — check the uncertainties), or one that looks like the start
model (check `max_iter` actually ran), or structure that follows the flight line's altitude
(the altitude column is wrong).

## If it goes wrong

| symptom | cause | fix |
|---|---|---|
| import shows 1 channel | ALC not applied | re-upload the `.alc` in the ALC field |
| every sounding culled at step 2.3 | altitude column is an elevation | use `TxAltitude`, not `tx_elevation` |
| job killed at the deadline | too many soundings or deadline too short | step 2.5, and size from Tutorial 3 |
| uniform model | no uncertainties | step 2.4 ran? `std_data_override` false? |

## See it done

Links to this chain on ymerflow.earth — import, processing and inversion of the as-delivered line in the public LPNNRD2018 project — will appear here when it has been run there.
