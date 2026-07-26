"""Splat geometry (§16).

Creates a small polygon splat at the impact position, oriented so its
Y-up axis aligns with the surface normal (i.e. the flat side lies on
the surface). A user-supplied template mesh is duplicated as-is; if
none is provided a flat cylinder disc is generated as the default
splat shape.

The splat is offset slightly along the normal to avoid Z-fighting with
the collider, and animated to "grow" from zero over a configurable
number of frames so the animator sees a snap-in rather than a pop-in.
"""

from __future__ import annotations

import math
import random
from typing import Iterable, Optional, Sequence, Tuple

try:
    from maya import cmds  # type: ignore
    from maya.api import OpenMaya as _om  # type: ignore
except ImportError:  # pragma: no cover
    cmds = None  # type: ignore
    _om = None  # type: ignore


Vec3 = Sequence[float]


def _create_default_splat_mesh(name: str) -> str:
    """A wide, flat disc as a stand-in when no user template mesh is
    provided. Uses polyDisc when available (Maya 2019+), otherwise a
    squashed polyCylinder as a fallback."""
    try:
        result = cmds.polyDisc(sides=8, subdivisionsMode=1,
                               subdivisions=1, radius=1.0, ch=False)
        node = result[0] if isinstance(result, (list, tuple)) else result
        return cmds.rename(node, name)
    except Exception:
        pass
    result = cmds.polyCylinder(n=name, h=0.02, sy=1, sx=16, r=1.0, ch=False)
    return result[0]


def _orient_transform_to_normal(node: str, normal: Vec3) -> None:
    """Rotate ``node`` so its local +Y axis points along ``normal``."""
    up = _om.MVector(0.0, 1.0, 0.0)
    target = _om.MVector(float(normal[0]), float(normal[1]),
                         float(normal[2])).normal()
    quat = _om.MQuaternion(up, target)
    euler = quat.asEulerRotation()
    cmds.xform(node, ws=True, ro=(
        math.degrees(euler.x),
        math.degrees(euler.y),
        math.degrees(euler.z),
    ))


def create_splat(
    name: str,
    position: Vec3,
    normal: Vec3,
    template_mesh: Optional[str] = None,
    parent: Optional[str] = None,
    surface_offset: float = 0.01,
    spawn_frame: int = 0,
    grow_frames: int = 2,
    scale: float = 1.0,
    random_rotation: bool = True,
    random_scale_variance: float = 0.0,
) -> str:
    """Create a splat mesh at the given impact position.

    Returns the splat transform's name.
    """
    if cmds is None or _om is None:
        raise RuntimeError("create_splat must run inside Maya.")

    if template_mesh and cmds.objExists(template_mesh):
        dup = cmds.duplicate(template_mesh, n=name, rr=True)[0]
        # Zero the copy's local translate/rotate so ``xform`` below is
        # authoritative.
        for axis in "XYZ":
            try:
                cmds.setAttr(f"{dup}.translate{axis}", 0)
                cmds.setAttr(f"{dup}.rotate{axis}", 0)
            except Exception:
                pass
        splat = dup
    else:
        splat = _create_default_splat_mesh(name)

    if parent:
        splat = cmds.parent(splat, parent)[0]

    # Position: nudge along the surface normal a hair to avoid
    # Z-fighting with the collider.
    n = normal
    mag = math.sqrt(n[0] * n[0] + n[1] * n[1] + n[2] * n[2]) or 1.0
    nx, ny, nz = n[0] / mag, n[1] / mag, n[2] / mag
    pos = (
        position[0] + nx * surface_offset,
        position[1] + ny * surface_offset,
        position[2] + nz * surface_offset,
    )
    cmds.xform(splat, ws=True, t=pos)
    _orient_transform_to_normal(splat, (nx, ny, nz))

    if random_rotation:
        # Random spin around the surface normal so multiple splats don't
        # read as copies of the same shape.
        spin = random.uniform(0.0, 360.0)
        cmds.rotate(0, spin, 0, splat, r=True, os=True)

    final_scale = scale
    if random_scale_variance > 0.0:
        jitter = 1.0 + random.uniform(-random_scale_variance,
                                      random_scale_variance)
        final_scale *= max(0.01, jitter)

    # Grow-in animation: hidden before spawn_frame, 0-scale on spawn,
    # full scale grow_frames later.
    hide_before = spawn_frame - 1
    if hide_before < 0:
        hide_before = 0
    cmds.setKeyframe(splat, at="visibility", t=hide_before, v=0)
    cmds.setKeyframe(splat, at="visibility", t=spawn_frame, v=1)
    cmds.keyTangent(splat, at="visibility",
                    time=(hide_before, spawn_frame),
                    itt="stepnext", ott="step")

    for axis in "XYZ":
        cmds.setKeyframe(splat, at=f"scale{axis}",
                         t=spawn_frame, v=0.0)
        cmds.setKeyframe(splat, at=f"scale{axis}",
                         t=spawn_frame + max(1, int(grow_frames)),
                         v=final_scale)

    return splat


def create_splats_from_candidates(
    base_name: str,
    position: Vec3,
    normal: Vec3,
    template_candidates: Iterable[str],
    **kwargs,
) -> str:
    """Pick one template mesh at random from ``template_candidates`` and
    hand off to :func:`create_splat`. Empty / non-existent candidates
    are skipped; if none remain the default splat is used."""
    valid = [m for m in template_candidates
             if m and cmds.objExists(m)]
    template = random.choice(valid) if valid else None
    return create_splat(base_name, position, normal,
                        template_mesh=template, **kwargs)
