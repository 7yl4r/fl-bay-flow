"""
Build a self-contained HTML flipbook viewer (play/pause + prev/next) from a
directory of rendered frame PNGs, for one cruise's forward particle-drift
animation.

Usage: python3 build_viewer.py <frames_dir> <particles_dir> <cruise_id> <out_html>
"""
import os
import sys
import glob
import base64
import calendar
import datetime

sys.path.insert(0, os.path.dirname(__file__))
from read_particles_xdmf import read_particle_frames


def main():
    frames_dir, particles_dir, cruise_id, out_html = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]

    frame_files = sorted(glob.glob(os.path.join(frames_dir, "frame_*.png")))
    frames_meta = read_particle_frames(os.path.join(particles_dir, "particles2d.xdmf"))
    assert len(frame_files) == len(frames_meta), f"{len(frame_files)} pngs vs {len(frames_meta)} xdmf frames"

    t_release = frames_meta[0]["t"]
    t_end = frames_meta[-1]["t"]
    release_str = datetime.datetime.fromtimestamp(t_release, datetime.timezone.utc).strftime("%Y-%m-%d")
    end_str = datetime.datetime.fromtimestamp(t_end, datetime.timezone.utc).strftime("%Y-%m-%d")

    b64_frames = []
    timestamps = []
    for fpath, meta in zip(frame_files, frames_meta):
        with open(fpath, "rb") as f:
            b64_frames.append(base64.b64encode(f.read()).decode("ascii"))
        dt = datetime.datetime.fromtimestamp(meta["t"], datetime.timezone.utc)
        elapsed_h = (meta["t"] - t_release) / 3600.0
        timestamps.append({"iso": dt.strftime("%Y-%m-%d %H:%M UTC"), "elapsed": f"+{elapsed_h:.0f}h"})

    frames_js = ",".join(f'"data:image/png;base64,{b}"' for b in b64_frames)
    meta_js = ",".join(f'{{iso:"{t["iso"]}",elapsed:"{t["elapsed"]}"}}' for t in timestamps)

    html = HTML_TEMPLATE.format(
        cruise_id=cruise_id,
        release_str=release_str,
        end_str=end_str,
        n_frames=len(frame_files),
        n_frames_minus_1=len(frame_files) - 1,
        frames_js=frames_js,
        meta_js=meta_js,
    )

    with open(out_html, "w") as f:
        f.write(html)
    size_mb = os.path.getsize(out_html) / 1e6
    print(f"wrote {out_html} ({size_mb:.1f} MB, {len(frame_files)} frames)")


HTML_TEMPLATE = """<title>Florida Bay Drift</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,500;9..144,600&family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
  :root {{
    --paper: #f4efe3;
    --panel: #fffdf7;
    --ink: #1c2b30;
    --ink-soft: #52646a;
    --accent: #1f7a72;
    --accent-2: #b8862f;
    --line: #d8cfb8;
    --focus: #1f7a72;
  }}
  @media (prefers-color-scheme: dark) {{
    :root:not([data-theme="light"]) {{
      --paper: #0d1a1f;
      --panel: #142226;
      --ink: #e7ecec;
      --ink-soft: #9db0b5;
      --accent: #4fd1c0;
      --accent-2: #e0b354;
      --line: #24373d;
      --focus: #4fd1c0;
    }}
  }}
  :root[data-theme="dark"] {{
    --paper: #0d1a1f;
    --panel: #142226;
    --ink: #e7ecec;
    --ink-soft: #9db0b5;
    --accent: #4fd1c0;
    --accent-2: #e0b354;
    --line: #24373d;
    --focus: #4fd1c0;
  }}

  * {{ box-sizing: border-box; }}
  body {{
    background: var(--paper);
    color: var(--ink);
    font-family: "IBM Plex Sans", system-ui, sans-serif;
    margin: 0;
    padding: 2rem 1.5rem 3rem;
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 1.25rem;
    min-height: 100vh;
  }}

  header {{
    max-width: 46rem;
    width: 100%;
    display: flex;
    flex-direction: column;
    gap: 0.35rem;
  }}
  h1 {{
    font-family: "Fraunces", Georgia, serif;
    font-weight: 600;
    font-size: clamp(1.6rem, 3vw, 2.1rem);
    margin: 0;
    text-wrap: balance;
    letter-spacing: -0.01em;
  }}
  .subtitle {{
    color: var(--ink-soft);
    font-size: 0.95rem;
    line-height: 1.5;
    max-width: 65ch;
  }}
  .legend {{
    display: flex;
    gap: 1.1rem;
    flex-wrap: wrap;
    font-size: 0.85rem;
    color: var(--ink-soft);
    margin-top: 0.15rem;
  }}
  .legend span {{ display: inline-flex; align-items: center; gap: 0.4rem; }}
  .swatch {{ width: 0.65rem; height: 0.65rem; border-radius: 50%; display: inline-block; }}

  .stage {{
    width: 100%;
    max-width: 46rem;
    background: var(--panel);
    border: 1px solid var(--line);
    border-radius: 0.5rem;
    padding: 0.6rem;
    box-shadow: 0 1px 3px rgba(0,0,0,0.06);
  }}
  .frame-wrap {{
    position: relative;
    width: 100%;
    aspect-ratio: 10 / 7;
    background: var(--paper);
    border-radius: 0.3rem;
    overflow: hidden;
  }}
  .frame-wrap img {{
    position: absolute;
    inset: 0;
    width: 100%;
    height: 100%;
    object-fit: contain;
  }}

  .controls {{
    width: 100%;
    max-width: 46rem;
    display: flex;
    align-items: center;
    gap: 0.85rem;
    background: var(--panel);
    border: 1px solid var(--line);
    border-radius: 0.5rem;
    padding: 0.7rem 0.9rem;
  }}
  button.ctrl {{
    all: unset;
    cursor: pointer;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 2.4rem;
    height: 2.4rem;
    border-radius: 50%;
    background: var(--paper);
    border: 1px solid var(--line);
    color: var(--ink);
    flex: none;
    transition: background 120ms ease, transform 80ms ease;
  }}
  button.ctrl:hover {{ background: var(--accent); color: var(--panel); }}
  button.ctrl:active {{ transform: scale(0.94); }}
  button.ctrl:focus-visible {{ outline: 2px solid var(--focus); outline-offset: 2px; }}
  button.ctrl svg {{ width: 1.05rem; height: 1.05rem; fill: currentColor; }}
  #play {{ background: var(--accent); color: var(--panel); border-color: var(--accent); }}
  #play:hover {{ opacity: 0.88; background: var(--accent); }}

  #scrub {{
    flex: 1;
    -webkit-appearance: none;
    appearance: none;
    height: 3px;
    border-radius: 2px;
    background: var(--line);
    outline: none;
  }}
  #scrub::-webkit-slider-thumb {{
    -webkit-appearance: none;
    width: 0.85rem;
    height: 0.85rem;
    border-radius: 50%;
    background: var(--accent-2);
    cursor: pointer;
    border: 2px solid var(--panel);
    box-shadow: 0 0 0 1px var(--accent-2);
  }}
  #scrub::-moz-range-thumb {{
    width: 0.85rem;
    height: 0.85rem;
    border-radius: 50%;
    background: var(--accent-2);
    cursor: pointer;
    border: 2px solid var(--panel);
  }}

  .readout {{
    font-family: "IBM Plex Mono", ui-monospace, monospace;
    font-variant-numeric: tabular-nums;
    font-size: 0.82rem;
    color: var(--ink-soft);
    text-align: right;
    flex: none;
    min-width: 11.5rem;
    line-height: 1.35;
  }}
  .readout .elapsed {{ color: var(--accent); font-weight: 500; }}

  .hint {{
    font-size: 0.78rem;
    color: var(--ink-soft);
    opacity: 0.75;
  }}

  @media (prefers-reduced-motion: reduce) {{
    button.ctrl {{ transition: none; }}
  }}
</style>

<header>
  <h1>Florida Bay forward drift &mdash; cruise {cruise_id}</h1>
  <p class="subtitle">
    Simulated freshwater drift from three Everglades outflow points, tracked forward
    through a 2D depth-averaged tide + current model from {release_str} to {end_str}.
  </p>
  <div class="legend">
    <span><i class="swatch" style="background:#e63946"></i>Shark River</span>
    <span><i class="swatch" style="background:#2a9d8f"></i>Mccormick Creek</span>
    <span><i class="swatch" style="background:#9d4edd"></i>Trout Creek</span>
  </div>
</header>

<div class="stage">
  <div class="frame-wrap">
    <img id="frame" alt="Particle positions frame">
  </div>
</div>

<div class="controls">
  <button class="ctrl" id="prev" aria-label="Previous frame" title="Previous frame">
    <svg viewBox="0 0 24 24"><path d="M15.41 7.41 14 6l-6 6 6 6 1.41-1.41L10.83 12z"/></svg>
  </button>
  <button class="ctrl" id="play" aria-label="Play" title="Play / pause">
    <svg id="play-icon" viewBox="0 0 24 24"><path d="M8 5v14l11-7z"/></svg>
    <svg id="pause-icon" viewBox="0 0 24 24" style="display:none"><path d="M6 5h4v14H6zm8 0h4v14h-4z"/></svg>
  </button>
  <button class="ctrl" id="next" aria-label="Next frame" title="Next frame">
    <svg viewBox="0 0 24 24"><path d="M8.59 16.59 10 18l6-6-6-6-1.41 1.41L13.17 12z"/></svg>
  </button>
  <input type="range" id="scrub" min="0" max="{n_frames_minus_1}" value="0" step="1" aria-label="Frame scrubber">
  <div class="readout">
    <div id="date-readout">&mdash;</div>
    <div class="elapsed" id="elapsed-readout">&mdash;</div>
  </div>
</div>
<p class="hint">Space to play/pause &middot; arrow keys to step &middot; {n_frames} frames, hourly cadence</p>

<script>
  const frames = [{frames_js}];
  const meta = [{meta_js}];
  let idx = 0;
  let playing = false;
  let timer = null;

  const img = document.getElementById("frame");
  const scrub = document.getElementById("scrub");
  const dateReadout = document.getElementById("date-readout");
  const elapsedReadout = document.getElementById("elapsed-readout");
  const playBtn = document.getElementById("play");
  const playIcon = document.getElementById("play-icon");
  const pauseIcon = document.getElementById("pause-icon");

  function render() {{
    img.src = frames[idx];
    scrub.value = idx;
    dateReadout.textContent = meta[idx].iso;
    elapsedReadout.textContent = meta[idx].elapsed;
  }}

  function step(delta) {{
    idx = (idx + delta + frames.length) % frames.length;
    render();
  }}

  function setPlaying(v) {{
    playing = v;
    playIcon.style.display = playing ? "none" : "";
    pauseIcon.style.display = playing ? "" : "none";
    playBtn.setAttribute("aria-label", playing ? "Pause" : "Play");
    if (playing) {{
      timer = setInterval(() => step(1), 220);
    }} else {{
      clearInterval(timer);
    }}
  }}

  document.getElementById("prev").addEventListener("click", () => {{ setPlaying(false); step(-1); }});
  document.getElementById("next").addEventListener("click", () => {{ setPlaying(false); step(1); }});
  playBtn.addEventListener("click", () => setPlaying(!playing));
  scrub.addEventListener("input", (e) => {{ setPlaying(false); idx = parseInt(e.target.value, 10); render(); }});

  document.addEventListener("keydown", (e) => {{
    if (e.code === "Space") {{ e.preventDefault(); setPlaying(!playing); }}
    else if (e.code === "ArrowLeft") {{ setPlaying(false); step(-1); }}
    else if (e.code === "ArrowRight") {{ setPlaying(false); step(1); }}
  }});

  render();
</script>
"""


if __name__ == "__main__":
    main()
