"""
Shared velocity-magnitude safeguard applied to every exported depth-averaged
current field (hydro output, used directly by particle tracking).

Why: the mesh grades from 400m (coast) to 6000m (offshore) based on distance
from the coast alone, not on bathymetry. In a handful of offshore elements
this means one triangle spans a huge, poorly-resolved depth range (e.g. the
edge of the BlueTopo survey coverage meeting real deep water, or a genuine
but under-resolved shelf-break) -- one cruise had 520 triangles with a
>100m depth range across a single element, two of them spanning nearly 600m.
The shallow-water solver responds to such an unresolved gradient with
locally very high (but bounded, non-NaN) velocity -- observed up to ~9 m/s
against a domain where FES2014 tidal currents and CMEMS boundary currents
both stay under ~1.5 m/s, and where the 99.9th percentile of the whole
solved field is ~1.1 m/s. See README.md ("Known artifact: localized
spurious velocity spikes") for the full investigation.

This is a diagnosis-agnostic safeguard, not a fix for the underlying mesh
resolution. It is a soft-knee limiter, not a uniform rescaling: speeds at or
below THRESHOLD pass through with zero change (bit-for-bit identical), and
only the excess above THRESHOLD is smoothly compressed toward an asymptotic
CEILING. This matters because a naive tanh(speed/ceiling) rescaling touches
*every* value, however small -- it would quietly shave a couple percent off
completely ordinary currents everywhere in the domain, not just the outliers
this is meant to catch.
"""
import numpy as np

THRESHOLD = 1.5  # m/s -- below this, values are untouched. Above the
                  # calibrated tidal (~0.45 m/s) currents and in line with the
                  # CMEMS boundary current's own 99.9th percentile (~1.1-1.4 m/s),
                  # so real flow in this domain is essentially never affected.
CEILING = 1.8     # m/s -- asymptotic maximum for anything above THRESHOLD. Kept
                  # close to THRESHOLD deliberately: an artifact that persists for
                  # hours (not a single spike) can still move a particle a long
                  # way even when capped, so the ceiling stays near the domain's
                  # own legitimate top end rather than a loose multiple of it.


def cap_speed(uv, threshold=THRESHOLD, ceiling=CEILING):
    """Soft-knee-limit the magnitude of a (2, ...) velocity array: values at
    or below `threshold` are returned unchanged; the excess above threshold
    is smoothly compressed so speed approaches (but never exceeds) `ceiling`.
    Direction is always preserved."""
    speed = np.hypot(uv[0], uv[1])
    excess = np.maximum(speed - threshold, 0.0)
    headroom = ceiling - threshold
    capped_speed = np.where(
        speed > threshold,
        threshold + headroom * np.tanh(excess / headroom),
        speed,
    )
    safe_speed = np.maximum(speed, 1e-12)
    scale = capped_speed / safe_speed
    return uv * scale[None, ...]
