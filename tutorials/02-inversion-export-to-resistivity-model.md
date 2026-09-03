# Tutorial 2 — From the inversion export to a resistivity model

_Outline only, 2026-09-04. Blocked on two inputs: the gate-matched GEX (22 LM / 29 HM) and the
confirmed moment-merge for this line. Do not follow yet._

**The idea.** `inversion/line_300901_dat.xyz` is the data the contractor actually inverted —
already culled and stacked to 531 soundings. Skip processing's averaging, invert it, and your
model should *reproduce* the published one, because you are starting from the same soundings.

**Steps, once unblocked**

1. Split the Workbench export to one row per sounding with
   `tools/workbench_dat_split_moments.py` (or use the pre-split file this repo will ship).
2. **Import** with the generated ALC and the **gate-matched GEX** — `NoGates` 22 / 29, not
   the delivery's 28 / 37. The inversion validates gate counts and will refuse a mismatch.
3. **Process** — *no* moving average: the data are already stacked. You need **STD error:
   Replace from GEX** (uncertainties) and **Assume horizontal transmitter** (the export
   carries no tilt columns; this synthesises them).
4. **Invert** — same settings as Tutorial 1; 531 soundings runs in ~15 min at 8 CPU / 4 Gi.
5. **Compare** with `line_300901_mod.xyz`. Expect `rmse_d` ≈ 1.0 and a close match.
