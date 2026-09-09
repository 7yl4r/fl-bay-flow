# Florida Bay Forward Drift

Forward particle-drift modeling of Everglades freshwater outflow through
Florida Bay and the Florida Keys, for 8 historical water-quality sampling
cruises. Built on [SLIM4](https://git.immc.ucl.ac.be/slim/slim4) (UCL),
a 2D/3D unstructured-mesh coastal circulation model.

Published report: **http://tylar.info/fl-bay-flow/**

## What this does

For each of 8 cruises (from a collaborator's particle-drift request
spreadsheet, `data/*model_request.csv`), the pipeline:

1. Builds a forced 2D depth-averaged hydrodynamic simulation of the Florida
   Keys / Florida Bay region covering that cruise's sampling window.
2. Releases particles at three Everglades freshwater outflow points (Shark
   River, McCormick Creek, Trout Creek) at the start of the window.
3. Tracks them forward through the simulated currents for the length of the
   window, with a modest random-walk perturbation layered on top.
4. Renders the result as a play/pause/scrubber animation, and publishes all
   8 as a static site via Quarto + GitHub Pages.

The original ask was backward tracking from a water sample to find its
origin; it was later changed to forward tracking from known freshwater
sources to see where that water is likely to go — see git history on
`particles/forward_track.py` for context if reviving backward tracking is
ever useful again (it's a straightforward `dt < 0` change to the same
tracker call).

## Pipeline layout

```
mesh/           domain + mesh generation (seamsh/gmsh), coastline sources
data/
  bathy/        BlueTopo -> mesh-node bathymetry
  tides/        FES2014 -> SLIM4/TPXO-format adapter
  wind/         ERA5 download
  currents/     Copernicus Marine (CMEMS) download, per cruise
  forcing/      per-cruise combined forcing files (built by prepro/)
  keys_checkpoints*.{json,csv}   the 8 cruise windows, extracted from the
                                 original request spreadsheet
prepro/         builds wind stress + open-boundary eta/uv per cruise
run/            hydro simulation driver + shared fixes (velocity_cap.py)
particles/      forward Lagrangian particle tracking
viz/            frame rendering + self-contained HTML viewer
report/         Quarto project (the published site)
run_all_cruises.py   top-level driver: one cruise, or all 8 concurrently
```

Each per-cruise step writes into `data/forcing/<cruise>/`,
`run/output/<cruise>/`, `particles/output/<cruise>/`, `viz/frames/<cruise>/`,
`viz/viewer_<cruise>.html`. Run a single cruise with:

```
python3 run_all_cruises.py WS23011
```

or all 8 (concurrently, one process per cruise — see "Concurrency" below):

```
python3 run_all_cruises.py --all -j 4
```

## How SLIM4 is used here

- **Model**: `slim4.slim2d.ShallowWater` — 2D depth-averaged shallow water
  equations (not 3D; sufficient for surface/near-surface transport and far
  cheaper to run across 8 windows). `g=9.80616`, `rho_0=1000`.
- **Build**: CPU-only (`-DAVA_TARGET=cpu`), MPI-capable build
  (`-DCOMM_TYPE=MPI`) but **not actually run under MPI** — see
  "Why not MPI" below. `-DIMPLICIT=ON -DENABLE_PETSC=ON` (built in case an
  implicit run is ever wanted; the production runs use the explicit
  integrator). `-DENABLE_FP16=OFF` (the installed GDAL is too old for
  SLIM4's FP16 GeoTIFF export path).
- **Mesh**: `mesh/build_mesh.py`, via `seamsh`/`gmsh`. Real (non-clipped)
  south Florida mainland + Keys/Marquesas/Dry Tortugas coastline from
  GSHHG, closed by a hand-drawn open-ocean boundary through the Gulf and
  Straits of Florida. Element size grades with distance from the coast:
  `size = clip(400 + 0.35*d, 400, 6000)` meters. Result: 32,044 triangles,
  18,029 nodes. Sizing is **not** bathymetry-aware (unlike e.g. the
  bundled `testcases/3d/gbr` example) — this is the direct cause of the
  velocity-spike artifact documented below.
- **Time integration**: explicit low-storage Runge-Kutta
  (`slim.iterate_low_storage_runge_kutta`, stability parameter `2/13`),
  not the implicit DIRK2 path. `dt` is set from `compute_cfl()` with an
  0.8 safety factor, rechecked every 24 simulated hours and only ever
  allowed to shrink. An implicit run was tried first and abandoned: on the
  original 353k-element mesh it made no visible progress in hours; even
  after coarsening to the current mesh, DIRK2 was not clearly faster than
  explicit and added real per-step failure modes (Newton non-convergence)
  that the explicit scheme doesn't have.
- **Wetting/drying**: enabled, `Hthin=0.2` — required once real (very
  shallow, min-depth-clipped) Florida Bay bathymetry was in play; without
  it, one production run went unstable (NaN) at day ~11 of a 14-day window.
- **Dissipation**: bulk bottom drag, `Cd=2.5e-3`, spatially uniform.
- **Viscosity**: Smagorinsky, coefficient `0.01`.
- **Boundaries**: `"coast"` (no-slip wall) and `"open"` (imposed eta + u,
  velocity not transport, 1-day linear ramp).

### Why not MPI

`slim2d.partition_mesh()` + per-rank MPI runs were tried first, matching
the pattern in SLIM4's own examples. It requires every per-node forcing
file (wind, tides+currents, bathymetry) to be built against the *same*
mesh partition a given rank will use — the forcing pipeline here builds
those on the single unpartitioned mesh, so an MPI run silently loads
mismatched per-rank data (`DataStatic.set(): Invalid shape for v`) unless
the whole forcing step is redone under `mpirun` too. Given 8 independent,
embarrassingly-parallel cruises, it was simpler and just as fast in
aggregate to run cruises concurrently as separate single-core processes
(`run_all_cruises.py -j N`) than to make forcing generation
partition-aware. `-j` should match **physical** cores, not logical/SMT
threads — running one process per logical core on a 4-core/8-thread
machine caused severe memory-bandwidth contention (each cruise ran ~4-7x
slower than in isolation) until concurrency was dropped to 4.

## Forcing data

| Component | Source | Notes |
|---|---|---|
| Open-boundary currents & SSH | Copernicus Marine — GLORYS12 reanalysis, `cmems_mod_glo_phy_my_0.083deg_P1D-m` | Daily mean, surface level (~0.49 m), bbox lon [-84,-79] lat [23,26]. `data/currents/download_cmems.py` |
| Tides | FES2014 | 8 major constituents: M2, S2, N2, K2, K1, O1, P1, Q1 (others available in the source data — see `data/tides/build_tpxo_nc.py:CONSTITUENTS` — but omitted for build simplicity, not for a physical reason). Converted from AVISO's per-constituent NetCDFs into the combined multi-constituent format `slim4.tpxo.GridTPXO` expects. |
| Wind | ERA5 reanalysis | Hourly 10m u/v, `data/wind/download_era5.py`, converted to surface stress via Smith-Banke (`atm_density=1.25`, `f0=0, f1=6.3e-4, f2=6.6e-5`) |
| Bathymetry | NOAA BlueTopo (COG GeoTIFF, `~/Documents/bluetopo/`) | Interpolated onto mesh nodes, clipped to 1.5 m minimum depth; the ~15% of nodes outside BlueTopo's survey extent are filled by nearest-neighbor from the nearest valid node (`data/bathy/interp_bathy.py`) — this nearest-neighbor fill is what produces the sharp depth discontinuities behind the velocity-spike artifact below. |

Simulated window = cruise's model window, **capped to 14 days**, plus a
1-day spinup/ramp before it. The cruise windows (from the request
spreadsheet) run 10-14 days, so in practice this cap is a no-op — every
cruise runs its full original window. An earlier version of this pipeline
capped to 7 days as a cost/detail tradeoff (each cruise takes many hours
even running 4-way concurrent); reverted once that tradeoff wasn't worth
losing half of each cruise's real window.

## Particle tracking

`particles/forward_track.py`. Three sources, 200 particles each (600
total), released as a single pulse at the start of the (post-spinup)
window:

| Source | Lat, Lon |
|---|---|
| Shark River | 25.356690, -81.125499 |
| McCormick Creek | 25.148599, -80.720987 |
| Trout Creek | 25.213100, -80.520919 |

Integration: `Tracker2d`, RK4, substeps capped at 900s (15 min).
Positions exported **hourly for the full window** — a 14-day run produces
337 export checkpoints. (An earlier version of this pipeline used a
15-min/6-hour fine/coarse split, then a uniform 15-min cadence throughout;
both were tried while the window was capped to 7 days. Hourly is the
current setting.)

Diffusivity ("minor random perturbation" on top of the resolved currents):
fixed at `kh=2.0 m²/s` using SLIM4's `"direct"` formula (kh applied as a
flat constant), **not** `"okubo"` (kh scaled by local velocity shear) — see
the artifact writeup below for why.

## Known artifact: localized spurious velocity spikes

**Symptom**: particles occasionally traveled much farther than the
resolved currents should allow — a handful of trajectories per cruise
ending up 200+ km from their source in a week, well beyond what the
calibrated tidal (~0.2-0.45 m/s) and open-boundary CMEMS (~1.4 m/s peak)
currents should produce.

**Root cause**: the mesh grades element size by distance from the coast
only (see "Mesh" above), not by bathymetry. In deep, coarse (up to 6000m)
offshore elements, this occasionally puts a huge depth range inside a
single triangle — one investigated cruise (WS23011) had 520 triangles
with a >100m depth range across one element, two of them spanning nearly
600m (almost certainly the edge of BlueTopo's survey coverage meeting the
nearest-neighbor-filled deep water beyond it, rather than a real feature
the model is resolving). The shallow-water solver responds to a depth
discontinuity that severe with locally very high — but bounded, non-NaN —
velocity: up to ~9 m/s at the worst cells, against a domain where the
99.9th percentile of the whole solved field is normally ~1.1 m/s. The
anomaly ramps in with the boundary-forcing ramp over the first 1-2 days
and then holds at a roughly steady elevated level for the rest of the run
— it doesn't blow up, which is why it survived silently rather than
crashing the simulation. All 8 cruises showed a similar-magnitude count of
affected values (roughly 9,000-12,000 out of ~18.5 million exported
(timestep x DG-node) values, i.e. ~0.05-0.07%) at a handful of different
locations each — this is a structural property of the mesh/bathymetry
combination, not a one-off tied to a single cruise's forcing.

**Why it moved particles so much more than its raw magnitude suggests**:
SLIM4's `"okubo"` diffusivity formula scales the random-walk kick by local
velocity *shear*. A capped-but-still-elevated cell next to its normal
neighbors is itself a large local shear, so `"okubo"` was turning even a
tamed velocity spike into an outsized diffusive kick — capping raw speed
alone (see below) barely changed the particle statistics until the
diffusivity formula was also switched away from shear-scaling.

**Fix** (`run/velocity_cap.py`), applied twice:

1. **A soft-knee speed limiter** on every exported hydro velocity field.
   Values at or below `THRESHOLD=1.5 m/s` pass through completely
   unchanged (bit-for-bit); the excess above threshold is smoothly
   compressed toward an asymptotic `CEILING=1.8 m/s`, so there's no new
   hard discontinuity introduced at the knee. Both constants sit close to
   the domain's own legitimate top end (not a loose multiple of it) —
   because the artifact is *persistent* over hours, not a single-step
   spike, a generous ceiling would still let a capped-but-sustained
   artifact move a particle a long way. Applied live in `run_hydro.py` for
   future runs, and retroactively to the 8 already-computed hydro outputs
   via `run/reprocess_hydro_cap.py` (reads the archived export, applies
   the cap, rewrites it — no need to re-run the expensive shallow-water
   solve).
2. **Diffusivity formula changed from `"okubo"` to `"direct"`** (see
   above) in `particles/forward_track.py`. This is the fix that actually
   mattered: with it, a test cruise's mean 1-week particle displacement
   dropped from ~88 km to ~23 km, closely matching a pure-advection
   (kh=0) control run, while still keeping a physically-motivated
   background dispersion.

Both are deliberately *diagnosis-agnostic*: they don't patch this one
location, they bound any future artifact of this general shape (a real or
numerical velocity spike, wherever the mesh/bathymetry combination
produces one) rather than special-casing the one cruise where it was
found. The actual fix for the underlying cause would be a
bathymetry-aware mesh sizing function (as in `testcases/3d/gbr/mesh.py`)
so no element ever spans a depth discontinuity that severe — not done
here, out of scope for the current effort budget.

If you re-run the pipeline with different sources, a different mesh, or a
much longer window, re-check for this class of artifact rather than
assuming the current thresholds are still appropriate: `run/reprocess_hydro_cap.py`
prints how many (timestep, DG-node) values it capped per cruise, and a
count that's a much larger fraction of the field than the ~0.05-0.07% seen
here is worth a fresh look rather than just re-running with the same caps.

## Visualization

`viz/render_frames.py` renders one PNG per particle export checkpoint
(coastline + colored scatter per source); `viz/build_viewer.py` bundles
them into a single self-contained HTML page (frames embedded as base64,
play/pause/prev/next/scrubber, arrow-key and spacebar controls). Source
colors: Shark River `#e63946` (red), McCormick Creek `#2a9d8f` (teal),
Trout Creek `#9d4edd` (purple) — Trout Creek was originally a blue
(`#457b9d`) too close to the water fill and to McCormick Creek's teal to
tell apart at a glance.

Frames are rendered at 8x5.6in / 90dpi rather than a larger/sharper size,
chosen to keep the viewer HTML under GitHub's 100MB per-file push limit
even at the densest cadence tried during development (15-min, 673
frames/cruise, ~62-66MB each). At the current hourly cadence over a 14-day
window (337 frames/cruise) each viewer is well under half that.

## Report

`report/` is a Quarto website (`_quarto.yml`, `index.qmd`, one `.qmd` per
cruise under `cruises/`, each embedding its `viz/viewer_<cruise>.html` copy
via an iframe from `report/viewers/`). Rebuild and publish with:

```
cd report
quarto render                        # sanity-check the build first
quarto publish gh-pages --no-browser
```

The rendered site is pushed to the `gh-pages` branch (not `main` — the
large per-cruise viewer HTML files are `.gitignore`d on `main` and only
ever live in the published site and in local `viz/`/`report/viewers/`
working copies).
