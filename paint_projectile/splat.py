"""Splat geometry (§16).

Two things happen here:

    1. Shape — instead of a plain disc, generate a procedural water-
       splash n-gon: a spiky perimeter (jagged silhouette) plus
       satellite droplets scattered around the main blob. Users can
       still pass their own template mesh(es); the procedural shape is
       just the default.

    2. Orientation + deformation — the splat is oriented so its local
       +Y axis aligns with the surface normal (flat side on the wall),
       then rotated around that normal so local +X points along the
       projectile's tangential velocity. A perpendicular hit produces
       a symmetric splash; a grazing hit gets stretched along the
       direction of travel and squeezed across it — same visual read
       as real water hitting a surface.

Scale is driven by the projectile's own size: whatever bounding radius
the source ball has, the splat comes out proportional to it, so a small
ball leaves a small splash and a big ball leaves a big one.
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


# --------------------------------------------------------------------------- #
# Procedural splash shape
# --------------------------------------------------------------------------- #

def _create_droplet_facet(name: str, radius: float, rng: random.Random) -> str:
    num = rng.randint(6, 9)
    verts = []
    for i in range(num):
        angle = (i / num) * math.tau
        r = radius * (0.75 + rng.uniform(-0.15, 0.15))
        verts.append((r * math.cos(angle), 0.0, r * math.sin(angle)))
    return cmds.polyCreateFacet(p=verts, ch=False, n=name)[0]


def _create_splash_facet(
    name: str,
    base_radius: float,
    num_spikes: int = 11,
    spike_length: float = 0.55,
    valley_depth: float = 0.25,
    droplet_count: int = 6,
    droplet_min_dist: float = 1.35,
    droplet_max_dist: float = 2.0,
    asymmetry: float = 0.0,
    seed: Optional[int] = None,
) -> str:
    """Build the reference-image-style splash: irregular spike perimeter
    with satellite droplets scattered around. Everything lives in the
    XZ plane at y=0 so the caller can orient it as a flat splat on the
    surface.

    ``asymmetry`` (0..1) biases the spike lengths so vertices facing
    the +X direction (which the caller aligns with the ball's forward
    tangent) reach further and vertices facing -X are shortened. At 0
    the splash is radially symmetric; at 1 the -X side is pulled in
    to ~30 % of its symmetric radius, giving a comet-like teardrop.
    Satellite droplets follow the same bias so nothing scatters behind
    the impact point.
    """
    rng = random.Random(seed)

    def _forward_mult(angle: float) -> float:
        # cos(angle) is +1 in the +X direction (forward), -1 in -X.
        forward = (math.cos(angle) + 1.0) * 0.5     # 0..1
        return 1.0 - asymmetry * (1.0 - forward) * 0.7

    # Perimeter: for each spike, three vertices (valley → peak → valley)
    # so the silhouette actually has sharp points instead of a smooth
    # star.
    verts = []
    total_verts = num_spikes * 3
    for i in range(total_verts):
        angle = (i / total_verts) * math.tau
        stage = i % 3
        if stage == 1:
            # Peak — spike outward
            r = base_radius * (1.0 + spike_length * rng.uniform(0.6, 1.3))
        else:
            # Valley — pulled in
            r = base_radius * (1.0 - valley_depth * rng.uniform(0.7, 1.1))
        # Slight per-vertex jitter so the outline reads as organic
        r *= 1.0 + rng.uniform(-0.05, 0.05)
        r *= _forward_mult(angle)
        verts.append((r * math.cos(angle), 0.0, r * math.sin(angle)))

    main = cmds.polyCreateFacet(p=verts, ch=False, n=f"{name}_main")[0]

    droplets = []
    for i in range(droplet_count):
        if asymmetry > 0.0:
            # Bias droplet placement forward so no drops fly behind the
            # impact when the hit is grazing.
            angle = rng.uniform(-math.pi * (1.0 - asymmetry * 0.8),
                                 math.pi * (1.0 - asymmetry * 0.8))
        else:
            angle = rng.uniform(0.0, math.tau)
        dist = base_radius * rng.uniform(droplet_min_dist, droplet_max_dist)
        dist *= _forward_mult(angle)
        r = base_radius * rng.uniform(0.06, 0.16)
        d = _create_droplet_facet(f"{name}_drop{i}", r, rng)
        cmds.setAttr(f"{d}.translateX", dist * math.cos(angle))
        cmds.setAttr(f"{d}.translateZ", dist * math.sin(angle))
        droplets.append(d)

    if droplets:
        pieces = [main] + droplets
        combined = cmds.polyUnite(pieces, ch=False)[0]
        cmds.delete(combined, ch=True)
        combined = cmds.rename(combined, name)
        return combined
    return cmds.rename(main, name)


def _create_default_splat_mesh(name: str, base_radius: float = 1.0,
                                asymmetry: float = 0.0,
                                seed: Optional[int] = None) -> str:
    return _create_splash_facet(name=name, base_radius=base_radius,
                                asymmetry=asymmetry, seed=seed)


# --------------------------------------------------------------------------- #
# Orientation helpers
# --------------------------------------------------------------------------- #

def _orient_transform_to_normal(node: str, normal: Vec3) -> None:
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


def _align_local_x_to_tangent(node: str, normal: Vec3, tangent_world: Vec3) -> None:
    """After ``_orient_transform_to_normal`` has aligned local +Y to the
    normal, rotate the node around that same axis so local +X points
    along ``tangent_world`` projected into the surface plane."""
    n_vec = _om.MVector(*normal).normal()
    t_vec = _om.MVector(*tangent_world)
    # Project out any component along the normal (should already be
    # perpendicular, but be safe).
    t_vec = t_vec - n_vec * (t_vec * n_vec)
    if t_vec.length() < 1e-6:
        return
    t_vec = t_vec.normal()

    # Current world-space direction of local +X on the node.
    sel = _om.MSelectionList()
    sel.add(node)
    dag = sel.getDagPath(0)
    world_mat = dag.inclusiveMatrix()
    # MMatrix indexing: (row, column). Local axis vectors are rows 0..2.
    local_x_world = _om.MVector(world_mat.getElement(0, 0),
                                world_mat.getElement(0, 1),
                                world_mat.getElement(0, 2)).normal()

    # Signed angle from local_x_world to t_vec around n_vec.
    cross = local_x_world ^ t_vec
    sin_a = cross * n_vec
    cos_a = local_x_world * t_vec
    angle = math.atan2(sin_a, cos_a)
    if abs(angle) < 1e-4:
        return
    cmds.rotate(0.0, math.degrees(angle), 0.0, node, r=True, os=True)


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #

def create_splat(
    name: str,
    position: Vec3,
    normal: Vec3,
    template_mesh: Optional[str] = None,
    parent: Optional[str] = None,
    surface_offset: float = 0.01,
    spawn_frame: int = 0,
    grow_frames: int = 2,
    base_scale: float = 1.0,
    stretch_along_tangent: float = 1.0,
    stretch_perp_tangent: float = 1.0,
    tangent_direction: Optional[Vec3] = None,
    forward_offset: float = 0.0,
    shape_asymmetry: float = 0.0,
    rotation_jitter_degrees: float = 0.0,
    seed: Optional[int] = None,
) -> str:
    """Create a splat mesh at the given impact position.

    Parameters
    ----------
    base_scale : float
        Uniform scale for the splat before per-axis stretch is applied
        — normally set to the projectile's bounding radius times a
        multiplier so the splash reads as proportional to the ball.
    stretch_along_tangent, stretch_perp_tangent : float
        Per-axis multipliers on top of ``base_scale``. Multiply local
        +X by ``stretch_along_tangent`` (the direction of travel across
        the surface) and local +Z by ``stretch_perp_tangent``.
    tangent_direction : Vec3, optional
        World-space direction along which to align local +X. Usually
        the projectile's tangential velocity at impact. If omitted the
        splat picks a random rotation around the normal instead.
    forward_offset : float
        Distance to shift the splat's spawn position along
        ``tangent_direction`` after applying the surface-normal offset.
        Set to ``base_scale * stretch_along_tangent`` for "impact at
        back edge, splash trails forward" (the physically-plausible
        behavior for a projectile whose momentum keeps carrying paint
        along the surface). No-op when ``tangent_direction`` is None.
    shape_asymmetry : float (0..1)
        Only meaningful for the procedural default shape: biases the
        spike lengths and satellite droplet placement so more of the
        material extends forward (+X) than backward (-X). 0 =
        radially symmetric, 1 = strong teardrop.
    """
    if cmds is None or _om is None:
        raise RuntimeError("create_splat must run inside Maya.")

    if template_mesh and cmds.objExists(template_mesh):
        dup = cmds.duplicate(template_mesh, n=name, rr=True)[0]
        for axis in "XYZ":
            try:
                cmds.setAttr(f"{dup}.translate{axis}", 0)
                cmds.setAttr(f"{dup}.rotate{axis}", 0)
            except Exception:
                pass
        splat = dup
    else:
        splat = _create_default_splat_mesh(name, base_radius=1.0,
                                           asymmetry=shape_asymmetry,
                                           seed=seed)

    if parent:
        splat = cmds.parent(splat, parent)[0]

    # Position with normal offset (avoid Z-fight) plus forward-tangent
    # offset (impact at back edge of the splat when grazing).
    n_len = math.sqrt(normal[0] ** 2 + normal[1] ** 2 + normal[2] ** 2) or 1.0
    nx, ny, nz = normal[0] / n_len, normal[1] / n_len, normal[2] / n_len
    pos_x = position[0] + nx * surface_offset
    pos_y = position[1] + ny * surface_offset
    pos_z = position[2] + nz * surface_offset
    if tangent_direction is not None and forward_offset != 0.0:
        tx, ty, tz = tangent_direction
        t_len = math.sqrt(tx * tx + ty * ty + tz * tz) or 1.0
        pos_x += (tx / t_len) * forward_offset
        pos_y += (ty / t_len) * forward_offset
        pos_z += (tz / t_len) * forward_offset
    cmds.xform(splat, ws=True, t=(pos_x, pos_y, pos_z))

    _orient_transform_to_normal(splat, (nx, ny, nz))

    if tangent_direction is not None:
        _align_local_x_to_tangent(splat, (nx, ny, nz), tangent_direction)
    if rotation_jitter_degrees > 0.0:
        jitter = random.uniform(-rotation_jitter_degrees,
                                rotation_jitter_degrees)
        cmds.rotate(0.0, jitter, 0.0, splat, r=True, os=True)

    # Grow animation with directional stretch baked into the end key.
    hide_before = max(0, spawn_frame - 1)
    cmds.setKeyframe(splat, at="visibility", t=hide_before, v=0)
    cmds.setKeyframe(splat, at="visibility", t=spawn_frame, v=1)
    cmds.keyTangent(splat, at="visibility",
                    time=(hide_before, spawn_frame),
                    itt="stepnext", ott="step")

    final_x = base_scale * stretch_along_tangent
    final_y = base_scale                          # thickness (kept neutral)
    final_z = base_scale * stretch_perp_tangent
    for axis in "XYZ":
        cmds.setKeyframe(splat, at=f"scale{axis}", t=spawn_frame, v=0.0)
    end_frame = spawn_frame + max(1, int(grow_frames))
    cmds.setKeyframe(splat, at="scaleX", t=end_frame, v=final_x)
    cmds.setKeyframe(splat, at="scaleY", t=end_frame, v=final_y)
    cmds.setKeyframe(splat, at="scaleZ", t=end_frame, v=final_z)

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
    are skipped; if none remain the default splash shape is used."""
    valid = [m for m in template_candidates
             if m and cmds.objExists(m)]
    template = random.choice(valid) if valid else None
    return create_splat(base_name, position, normal,
                        template_mesh=template, **kwargs)


# --------------------------------------------------------------------------- #
# Helpers used by system.py
# --------------------------------------------------------------------------- #

def projectile_bounding_radius(mesh: str) -> float:
    """Approximate radius = half of the largest bounding-box extent."""
    bbox = cmds.exactWorldBoundingBox(mesh)
    dx = bbox[3] - bbox[0]
    dy = bbox[4] - bbox[1]
    dz = bbox[5] - bbox[2]
    r = max(dx, dy, dz) * 0.5
    return r if r > 1e-6 else 1.0


def compute_splat_stretch(
    velocity: Vec3,
    normal: Vec3,
    max_stretch: float = 1.8,
    min_squeeze: float = 0.55,
) -> Tuple[float, float, Optional[Tuple[float, float, float]], float]:
    """From impact velocity + surface normal, return
    ``(stretch_along_tangent, stretch_perp_tangent,
    tangent_direction_world, grazing_factor)``.

    * Perpendicular hit (velocity antiparallel to normal, no tangential
      component) → ``(1.0, 1.0, None, 0.0)`` — symmetric splash.
    * Grazing hit → stretch approaches ``max_stretch`` along tangent,
      squeeze approaches ``min_squeeze`` across it, grazing → 1.0.

    ``grazing`` (0..1) is the fraction of velocity that lies in the
    surface plane. Callers use it to bias splat position and shape
    forward — a fully perpendicular hit has no "forward" to bias
    toward, a grazing hit has all of it.
    """
    vx, vy, vz = float(velocity[0]), float(velocity[1]), float(velocity[2])
    nx, ny, nz = float(normal[0]), float(normal[1]), float(normal[2])
    v_dot_n = vx * nx + vy * ny + vz * nz
    tx = vx - v_dot_n * nx
    ty = vy - v_dot_n * ny
    tz = vz - v_dot_n * nz
    tan_mag = math.sqrt(tx * tx + ty * ty + tz * tz)
    v_mag = math.sqrt(vx * vx + vy * vy + vz * vz)
    if v_mag < 1e-6:
        return 1.0, 1.0, None, 0.0
    grazing = min(1.0, tan_mag / v_mag)
    stretch = 1.0 + grazing * (max_stretch - 1.0)
    squeeze = 1.0 - grazing * (1.0 - min_squeeze)
    if tan_mag < 1e-6:
        return stretch, squeeze, None, grazing
    return stretch, squeeze, (tx / tan_mag, ty / tan_mag, tz / tan_mag), grazing
