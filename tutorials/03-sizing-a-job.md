# Tutorial 3 — Sizing a job so it finishes

_Same content as the sizing guide drafted for the YmerFlow user guide; kept here so the demo data is self-contained. Source of truth once merged: the user guide._


_Draft for the user guide — Ben & Claude, 2026-09-03. Every number here is measured, from
`LPNNRD2018-inversion-stats.md` (Egil, 2026-09-02) and the AEM26 validation runs. Update
the tables when new runs land; do not extrapolate beyond them without saying so._

## The three numbers a job asks for

When you submit an inversion you set a **resource request** — CPU, memory, and a
**deadline**. Two things about it that decide whether your job succeeds:

1. **You are billed on what you *request*, not what you use.** Over-asking costs tokens for
   nothing. Under-asking kills the job. So the goal is a request just above the real need.
2. **The deadline is a hard stop.** A job that runs out of time is killed and billed for the
   time it ran. Set it from the runtime table below, then add margin.

## What actually drives each number

**Memory is nearly flat in sounding count.** The dominant term is the pool of parallel
forward-modelling workers plus the sensitivity matrix, both of which barely grow with more
soundings. Measured: **8,995 soundings peaked at 4.0 GiB**; **753 soundings at 1.2 GiB.**
The 48 Gi requested for the big line used 8% of itself. **Do not size memory by soundings.**

**Runtime grows a bit faster than linearly in soundings**, and is dominated by how many
Gauss-Newton iterations run. `max_iter=50` is the default and most runs use all 50 whether
or not the fit has converged — the 8,995-sounding line was essentially unchanged after
iteration ~25–30 but ran to 50 anyway. Per-iteration cost: ~5 s at 500 soundings, ~20 s at
750, ~2–2.5 min at 9,000.

**CPU sets the per-iteration time, up to the node.** The forward simulation is parallel
(`n_cpu`); more cores help until you hit what the node has free (≈25 of 28 on the default
cluster). Beyond the node, more requested CPU just makes the job harder to schedule.

## Measured runs — use these as anchors

| soundings | layers | CPU req | RAM req | peak RAM | iterations | wall time | fit (rmse_d) |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 501 | 39 | 26 | 55 Gi | — | — | **3 m 39 s** | ≈1.0 |
| 753 | 30 | 16 | 12 Gi | **1.2 GiB** | 50 | **17 m** | 1.02 |
| 8,995 | 30 | 24 | 48 Gi | **4.0 GiB** | 50 | **2 h 18 m** | 1.22 (plateau) |

All: SkyTEM 304 dual-moment, LU solver, smooth-L2, `fix_Jmatrix=true`, default cluster.

## Recommended requests

| your data | CPU | memory | deadline | expect |
|---|---:|---:|---:|---|
| **one short line, ≤ 1,000 soundings** | 8–16 | **4 Gi** | 1 h | 5–20 min |
| **one long line, ~5,000–10,000** | 24 | **12 Gi** | 3 h | 1–2.5 h |
| **a block, tens of thousands** | 24+ | 16 Gi | *split it* | see below |

Memory: **3× the measured peak** is comfortable; there is no case in the table where more
than 12 Gi did anything but slow down scheduling.

Deadline: take the wall-time anchor nearest your size, assume all 50 iterations, and add
50%. Running out of deadline at iteration 48 wastes everything before it.

**Blocks (e.g. the 26-line, 76,389-sounding demo block): do not invert as one job.** Runtime
scales super-linearly and a single pod is capped by one node. Invert per line, or reduce
`max_iter`. This is also the case that overruns a free-tier budget on the first click.

## Two levers that cut time and cost without changing the answer

- **`max_iter`.** If the misfit has flattened, later iterations do nothing. A cap of 25–30
  would have halved the 8,995-sounding run.
- **Right-size the pod.** Billing is per requested CPU-hour and GB-hour. The 753-sounding line
  at 16 CPU / 12 Gi costs ≈4.5 tokens; the same run at 8 CPU / 4 Gi ≈2.2 — same result,
  because it never used more than 1.2 GiB.

## Before you submit — the checklist that catches the actual failures

- **GEX gate counts must match the data.** The inversion validates them and refuses a
  mismatch (`22 gates of data but gate-time table yields 28`). Delivered data uses the
  full-gate GEX; a Workbench `dat` export that was culled needs a GEX with the same
  `NoGates`.
- **Tilt columns must exist.** If the data has no `tilt_x`/`tilt_y`, add the *Assume
  horizontal transmitter* processing step or the tilt correction fails.
- **Coordinates in a projected CRS** (UTM). Set the EPSG on import.
- **A deadline longer than the anchor**, not equal to it.

## Free tier

Sized for the 753-sounding single-line case: ~2–4.5 tokens per full experiment depending on
pod size, so a 50-token grant is roughly 11–22 inversions — enough to change gate filters,
regularization and layer counts and re-run. It is **not** sized for the long line (2+ h,
~30+ tokens at 24/48) or the block. The demo data is split accordingly.
