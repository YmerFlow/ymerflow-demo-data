# Tutorial 2 — From AGF's inversion input to a resistivity model

**The idea.** `agf_inversion/inversion_input_data_line_300901.xyz` is the data the contractor
actually inverted — already culled and stacked to 531 soundings, with the uncertainties they
used. Skip the processing that Tutorial 1 spends its time on, invert it, and your model should
*reproduce* the published one, because you start from the same soundings with the same
error bars. This is the shortest path from download to a model you can check.

It is also the cheapest inversion in this repository: 531 soundings, well inside a free tier.

## Files

| file | role |
|---|---|
| `line_300901/agf_inversion/inversion_input_data_line_300901.xyz` + `.alc` | the input. One row per sounding; `Gate_Ch01` (LM, 28 gates) and `Gate_Ch02` (HM, 37 gates) with `STD_Ch01/02` and `InUse_Ch01/02`. Gates AGF culled are `*` with in-use 0 |
| `system/system_skytem304_for_delivered_data.gex` | the same GEX as for the delivered data. No special gate-matched GEX is needed: the file carries every GEX gate |
| `line_300901/agf_inversion/inversion_resistivity_model_line_300901.xyz` | the published model — what you are trying to reproduce |
| `line_300901/agf_inversion/inversion_forward_response_line_300901.xyz` + `.alc` | the published model's forward response, same layout as the input; optional, for checking data fit |

## Steps

1. **Import** — `import_skytem` with the XYZ, its `.alc`, and the GEX above. Leave the
   scale factor at its default (`1e-12`): the file is in pV/(A m⁴), the delivered convention.
   Projection `32614`.

2. **Process** — one step only: **Assume horizontal transmitter**. The Workbench export
   carries a combined `tilt` angle but no pitch/roll, and the inversion wants both; this step
   sets them to zero, which is what AGF's export already assumes for the corrected data.
   *Do not* add the moving-average filter (the data are already stacked) and *do not* replace
   the STD from the GEX (the file carries AGF's own uncertainties, 3–19% relative — that is
   part of what you are reproducing).

3. **Invert** — the same settings as Tutorial 1 are fine. The inversion's gate filter narrows
   the gates further; the defaults work. Size the job from Tutorial 3: ~15 minutes at 16 CPU /
   8 Gi, deadline 1 h.

4. **Compare** with `inversion_resistivity_model_line_300901.xyz`, 39 layers. Expect the data
   misfit near 1 and a model that matches the published one closely but not exactly: AGF ran a
   spatially constrained inversion in Workbench across the whole survey, and you are running
   a single line with a different regularization. The structure should be the same; the
   smoothing will differ.

## If something is off

- **Import refuses the ALC** — you gave it the delivered data's `.alc`. Each XYZ ships with its
  own; they are positional and not interchangeable.
- **The inversion drops every sounding** — the tilt step was skipped. Without `TxPitch` /
  `TxRoll` columns nothing can be tilt-corrected, and everything is culled.
- **Everything looks 1e12 too small or too large** — the scale factor was changed at import.
  Leave it at `1e-12`.

## Where the file came from

Workbench exports the inversion data as two rows per sounding, one per moment, with both
moments interleaved across one set of gate columns. The build merged those pairs and placed
every gate on its GEX gate by matching gate times. See PROVENANCE, step 5, and
`tools/workbench_dat_split_moments.py`.
