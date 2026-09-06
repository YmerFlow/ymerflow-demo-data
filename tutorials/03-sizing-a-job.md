# Tutorial 3 — Sizing a job so it finishes

Every number here is measured on YmerFlow's default cluster with the SkyTEM 304 data in this
repository. The tables are anchors, not formulas: size from the nearest measured case.

## The three numbers a job asks for

When you submit an inversion you set a **resource request** — CPU, memory, and a
**deadline**. Two things about it decide whether your job succeeds:

1. **You are billed on what you *request*, not what you use.** Over-asking costs for
   nothing. Under-asking kills the job. So the goal is a request just above the real need.
2. **The deadline is a hard stop.** A job that runs out of time is killed and billed for the
   time it ran. Set it from the runtime table below, then add margin.

## What actually drives each number

**Memory is nearly flat in sounding count.** The dominant term is the pool of parallel
forward-modelling workers plus the sensitivity matrix, both of which barely grow with more
soundings. Measured: **8,995 soundings peaked at 4.0 GiB**; **753 soundings at 1.2 GiB.**
A 48 Gi request for the big line used 8% of itself. **Do not size memory by soundings.**

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
| 531 | 40 | 16 | 8 Gi | — | 50 | **6 m 33 s** | 0.58 |
| 753 | 30 | 16 | 12 Gi | **1.2 GiB** | 50 | **17 m** | 1.02 |
| 8,995 | 30 | 24 | 48 Gi | **4.0 GiB** | 50 | **2 h 18 m** | 1.22 (plateau) |

All: SkyTEM 304 dual-moment, LU solver, smooth-L2, default cluster. The 531-sounding row is
Tutorial 2's inversion of the published input data; its fit is against the contractor's own
uncertainties.

## Recommended requests

| your data | CPU | memory | deadline | expect |
|---|---:|---:|---:|---|
| **one short line, ≤ 1,000 soundings** | 8–16 | **4–8 Gi** | 1 h | 5–20 min |
| **one long line, ~5,000–10,000** | 24 | **12 Gi** | 3 h | 1–2.5 h |
| **a block, tens of thousands** | 24+ | 16 Gi | *see below* | hours |

Memory: **3× the measured peak** is comfortable; there is no case in the table where more
than 12 Gi did anything but slow down scheduling.

Deadline: take the wall-time anchor nearest your size, assume all 50 iterations, and add
50%. Running out of deadline at iteration 48 wastes everything before it.

**The block (26 lines, 76,389 soundings delivered).** It is there to be inverted as a block —
a spatially constrained inversion across all 26 lines, which is how the published model was
made — and that is a paid-plan job: hours at high CPU, and a single pod is capped by one node.
On the free tier, invert it **one line at a time**: about 3,000 delivered soundings per line,
a few hundred after averaging, each line sized like the short-line row above.

## Two levers that cut time and cost without changing the answer

- **`max_iter`.** If the misfit has flattened, later iterations do nothing. A cap of 25–30
  would have halved the 8,995-sounding run.
- **Right-size the pod.** Billing is per requested CPU-hour and GB-hour. The 753-sounding line
  at 16 CPU / 12 Gi costs about twice what the same run costs at 8 CPU / 4 Gi — for the same
  result, because it never used more than 1.2 GiB.

## Before you submit — the checklist that catches the actual failures

- **GEX gate counts must match the data.** The inversion validates them and refuses a
  mismatch. Every file in this repository carries the full gate set and imports with the one
  GEX in `system/`; if you bring your own Workbench export with culled columns, it needs a GEX
  with the same `NoGates`, or the gates put back as in-use 0.
- **Tilt columns must exist.** If the data has no pitch/roll, add the *Assume horizontal
  transmitter* processing step or the tilt correction culls everything (Tutorial 2).
- **Coordinates in a projected CRS** (UTM). Set the EPSG on import.
- **A deadline longer than the anchor**, not equal to it.

## Free tier

Sized for the single-line cases: Tutorial 2's 531 soundings and Tutorial 1's ~650. Each full
experiment is a few minutes and a small fraction of a free grant, so there is room to change
gate filters, regularization and layering and re-run. The free tier is **not** sized for the
unaveraged 8,995-sounding line (2+ hours at 24 CPU) or for the block as one job. The demo data
is split accordingly.
