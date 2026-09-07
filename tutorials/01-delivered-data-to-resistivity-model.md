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

Every cull below takes a channel and a start gate, so it appears once per moment: gate
**10 on LM and 15 on HM** (1-based) here. Culls trim the tail of a sounding after the first
gate they reject, which is what you want on 10 Hz data.

1. **Apply gex** — disables the first `RemoveInitialGates` gates of each moment (7 on the 304),
   as the system description declares. They are transmitter turn-off and not invertible.
   It does *not* set uncertainties.
2. **STD error: Add from noise model** — once per channel: `noise_level_1ms` **2e-9** V/m²,
   `noise_exponent` −0.5, `relative_noise_fraction` 0.03. This gives every datum an error
   that grows as the signal dies, which is what lets late gates be *kept* and weighted
   rather than culled. The 2e-9 is measured from this line
   (`tools/benchmark/measure_noise_and_curvature.py`); the step's default of 1e-8 is five
   times too pessimistic for a 304.
3. **Disable soundings by tilt and altitude** — once per channel; `max_alt` **75** m, pitch
   and roll 10°. The altitude column is **`TxAltitude`**, height above ground (28–56 m on
   this line). The vendor's `Alt` column is an *elevation* and has been renamed
   `tx_elevation` in this data so you cannot pick it by accident.
4. **Correct data and tilt for 1D** — uses the delivered `TxPitch` and `TxRoll` to correct the
   amplitudes for frame tilt.
5. **Disable gates by negative data** — once per channel.
6. **Disable gates by curvature max** and **min** — once per channel each: **±3 on LM,
   ±6 on HM**. These bracket the curvature range the contractor's own culling kept (the
   defaults of ±10 would cull almost nothing). Curvature caught 8–9% of the LM data on this
   line and nothing on HM.
7. **Moving average filter** — this is the step that makes the free tier possible.
   - `filter_dict`: window widths in *soundings*, first gate to last gate:
     `Gate_Ch01` **51 → 125**, `Gate_Ch02` **75 → 175**. At 10 Hz this line is 2.2 m per
     sounding, so that is 115–280 m and 170–390 m windows. Narrower keeps narrow targets;
     wider is quieter.
   - `target_spacing_m` = **30** → one output sounding per ~30 m. 8,995 soundings over
     19.7 km become **692**. That is what the inversion sees.
   - `averaging_method` hybrid, `min_valid_fraction` 0.35.

   Skip this step and you will submit 8,995 soundings: a 2-hour, 24-CPU job that the free
   tier cannot finish. It is not a quality choice; it is the difference between a job that
   ends and one that is killed. It is also the slow step: 7½ minutes for this line.
8. **Disable gates by STD values** — once per channel, `std_threshold` **0.20**. After
   averaging, the STD reflects how well each stack agreed with itself; this is the cull that
   decides how deep the model is trusted. Lower it to 0.15 if the bottom of the model looks
   noisy, raise it if you lose depth. On this line it took 23% of LM and 15% of HM data, all
   late gates.
9. **Disable soundings by number of active gates** — once per channel, minimum **4**.

There is deliberately no *noise floor* cull before the averaging: signal below the floor is
buried, not gone, and averaging is what recovers it. The error model in step 2 and the STD
cull in step 8 do the judging afterwards.

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
| uncertainties | `std_data_override` | false | use the STDs from steps 2.2 and 2.7 |
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
| job killed at the deadline | too many soundings or deadline too short | step 2.7, and size from Tutorial 3 |
| uniform model | no uncertainties | step 2.2 ran? `std_data_override` false? |
| model noisy at depth | late gates kept that the stacks did not agree on | lower the STD cull in step 2.8 to 0.15 |
