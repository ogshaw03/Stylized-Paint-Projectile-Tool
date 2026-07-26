"""Projectile impact animation (§15).

At the detected impact frame the moving projectile mesh should read as
"splatting" onto the surface, then hand off to the splat geometry.

Prototype rule set:

    Frame N     : projectile still fully visible, unchanged
    Frame N + 1 : projectile scaled to a squashed shape aligned with
                  the surface normal (flat along normal, wide across)
    Frame N + 2 : projectile hidden

All three are set as animation keys on the projectile transform's
``scale*`` and ``visibility`` attributes so the animator can freely
adjust or over-key them from the Graph Editor. Base trajectory + world/
camera offset are untouched.
"""

from __future__ import annotations

import math
from typing import Sequence

try:
    from maya import cmds  # type: ignore
except ImportError:  # pragma: no cover
    cmds = None  # type: ignore


Vec3 = Sequence[float]


def _normalize(v: Vec3) -> Vec3:
    mag = math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])
    if mag < 1e-9:
        return (0.0, 1.0, 0.0)
    return (v[0] / mag, v[1] / mag, v[2] / mag)


def apply_impact_animation(
    projectile_xform: str,
    impact_frame: int,
    squash_frames: int = 1,
    squash_along_normal: float = 0.1,
    squash_across: float = 1.6,
) -> None:
    """Keyframe scale + visibility so the projectile squashes onto the
    hit surface and then vanishes."""
    if cmds is None:
        raise RuntimeError("apply_impact_animation must run inside Maya.")

    normal_frame = int(impact_frame)
    squash_at = normal_frame + max(0, int(squash_frames))
    hide_at = squash_at + 1

    # Baseline scale (whatever the mesh currently has) captured as key at
    # impact frame. We only key the scale we changed, so users can still
    # apply a base scale via the projectile transform if they want.
    for axis in "XYZ":
        cur = cmds.getAttr(f"{projectile_xform}.scale{axis}")
        cmds.setKeyframe(projectile_xform, at=f"scale{axis}",
                         t=normal_frame, v=cur)

    # Squash keys.
    for axis in "XYZ":
        cmds.setKeyframe(projectile_xform, at=f"scale{axis}",
                         t=squash_at, v=squash_across)
    # We can't rotate the squash to be along the normal without also
    # rotating the projectile mesh (which the animator may care about),
    # so use an isotropic squash-then-flat as a first pass. §11-§13's
    # deformer-based smear will handle directional squash properly.
    # Force one axis flatter than the others so the ball reads as
    # "hit" rather than "grew":
    cmds.setKeyframe(projectile_xform, at="scaleY",
                     t=squash_at, v=squash_along_normal)

    # Visibility: keep visible up through squash, hide next frame.
    cmds.setKeyframe(projectile_xform, at="visibility",
                     t=squash_at, v=1)
    cmds.setKeyframe(projectile_xform, at="visibility",
                     t=hide_at, v=0)
    # Step tangents on visibility so it doesn't interpolate through 0.5.
    cmds.keyTangent(projectile_xform, at="visibility",
                    time=(squash_at, hide_at),
                    itt="stepnext", ott="step")
