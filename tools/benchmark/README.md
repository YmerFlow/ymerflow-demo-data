# Benchmark tools

The measuring instruments for the benchmark. Each takes a YmerFlow output (the `msgpack`
a process writes; download it from the dataset's file URL) and compares it with what
this repository ships from the published survey.

| tool | question it answers |
|---|---|
| `compare_model_to_published.py` | how close is an inverted model to the published one — per layer, by depth band, matched by sounding position |
| `compare_data_to_published.py` | how does a processed dataset compare with the data the contractor actually inverted — amplitude, gate coverage and error bars, gate by gate |
| `measure_noise_and_curvature.py` | what noise level and curvature limits does a delivered line itself suggest for the processing steps |
| `window_width_vs_std.py` | how the averaged uncertainty at each gate depends on the averaging window — where a trapezoid can be wide and where it must stay narrow |
| `../forward_vs_workbench.py` | how does a forward model compare with Workbench's forward of the published model, gate by gate — no inversion in the loop |

All read the data under `data/` relative to this repository, so run `download.py` first.
They need `libaarhusxyz` and `scipy`; the forward check also needs the YmerFlow simpeg fork.
