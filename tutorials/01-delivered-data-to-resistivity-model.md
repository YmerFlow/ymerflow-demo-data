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
   `noise_exponent` −0.5, `relative_noise_fraction` 0.03. Two parts: a 3% relative error
   on every gate, and a **noise floor** that grows as the signal dies. The floor is the
   part that matters. Without it every gate carries the same 3%, the late gates look as
   trustworthy as the early ones, and the inversion is made to fit data that is mostly
   noise — the deep model swings to chase it. With it, late gates are *kept* but weighted
   down, and it is the averaging in step 7 that earns them back. The 2e-9 is measured from
   this line (`tools/benchmark/measure_noise_and_curvature.py`); the step's default of
   1e-8 is five times too pessimistic for a 304. Do not replace this step with
   **STD error: Replace from GEX** — that is the flat 3% with no floor.
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
     `Gate_Ch01` **11 → 25**, `Gate_Ch02` **19 → 35**. At 10 Hz that is 1.1–2.5 s of
     flight for LM and 1.9–3.5 s for HM; at 2.2 m per sounding, 25–56 m and 42–78 m
     windows. Keep the first-gate width narrow: the early gates respond to altitude and
     the top few metres, both of which change along the line, and the averaging counts
     that real variation as uncertainty. Widening the first-gate window from 11 to 51
     soundings raises the early-gate STD from 3% to 8% on this line — not because the
     data got noisier, but because the ground did not stay the same for 110 m. Late gates
     vary slowly and sit near the noise floor, so their window can be wider without cost.
   - `target_spacing_m` = **30** → one output sounding per ~30 m. 8,995 soundings over
     19.7 km become **692**. That is what the inversion sees.
   - `averaging_method` hybrid, `min_valid_fraction` 0.35.

   Skip this step and you will submit 8,995 soundings: a 2-hour, 24-CPU job that the free
   tier cannot finish. It is not a quality choice; it is the difference between a job that
   ends and one that is killed. It is also the slow step: 7 minutes for this line,
   whatever the CPU request — it runs on one core.
8. **Disable gates by STD values** — once per channel, `std_threshold` **0.20**. After
   averaging, the STD reflects how well each stack agreed with itself; this is the cull that
   decides how deep the model is trusted. Lower it to 0.15 if the bottom of the model looks
   noisy, raise it if you lose depth. On this line it took 15% of LM and 8% of HM data, all
   late gates.
9. **Disable soundings by number of active gates** — once per channel, minimum **4**.

There is deliberately no *noise floor* cull before the averaging: signal below the floor is
buried, not gone, and averaging is what recovers it. The noise floor belongs in the *error*
(step 2), not in a cull. The error model and the STD cull in step 8 do the judging
afterwards. We tried the alternative on this line — a flat 3% on every gate and no floor
anywhere, which is what a survey report's "3% uniform error" sounds like. It kept three to
five more late gates per moment than the published processing did, at 5–14% STD, and the
inversion could not fit them: the model's prediction sat one to three standard deviations
below the data at those gates, which is what noise biased high looks like, and the model
below 30 m moved further from the published one. The published processing
got the same effect by culling the late gates outright; the floor keeps them and lets the
inversion decide.

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
| | `noise_level_1ms` | 1e-9 (default) | the inversion adds a floor of its own on top of the processed STD. At this level it is smaller than the one from step 2.2 and changes little; it is not an off switch |
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
in detail; the published model used different culling, stacking and regularization. Expect
the top few metres to come out more conductive than the published model — 5–10 Ω·m where it
has 15. That is not the processing: the forward model does not yet reproduce the earliest
low-moment gates as Workbench does (receiver filters and the front gate;
[Ymerflow#94](https://github.com/YmerFlow/Ymerflow/issues/94)), and a 3% error on those
gates makes the inversion put a conductor at the surface to fit them. Below about 5 m the
two models agree to within a factor of 1.5–1.6 on this line, sounding by sounding. What
would be wrong: a
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
| deep model swings, late gates kept everywhere | no noise floor in the error model | step 2.2 must be the noise model, not a flat STD from the GEX |
| early-gate STD 8% or more | averaging window too wide at the first gate | step 2.7: first-gate width ≤ 25 soundings |
