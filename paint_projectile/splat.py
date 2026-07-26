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
# Splash geometry: pure-data generator + Maya-poly builder
# --------------------------------------------------------------------------- #
#
# compute_splash_geometry returns a dict of 2-D vertex lists, so it can be
# reused for both the Maya poly build and the in-UI PySide preview without
# duplicating the shape logic — same seed / params yields the same shape
# in both.

def compute_splash_geometry(
    base_radius: float = 1.0,
    blob_points: int = 22,
    blob_irregularity: float = 0.28,
    ray_count_range: Tuple[int, int] = (5, 10),
    ray_length_range: Tuple[float, float] = (1.25, 2.0),
    ray_long_prob: float = 0.25,
    ray_long_range: Tuple[float, float] = (2.4, 3.6),
    ray_width_range: Tuple[float, float] = (2.5, 6.0),
    droplet_count: int = 5,
    droplet_min_dist: float = 1.35,
    droplet_max_dist: float = 2.4,
    asymmetry: float = 0.0,
    seed: Optional[int] = None,
) -> dict:
    """Compute an ink-splash silhouette without touching Maya.

    Returns::

        {
          'blob':     [(x, z), ...]                # closed polygon perimeter
          'rays':     [[(x, z), (x, z), (x, z)],   # triangle strips
                       ...]
          'droplets': [[(x, z), ...],              # closed polygons
                       ...]
        }

    All coordinates lie in the XZ plane centred on (0, 0). ``asymmetry``
    (0..1) biases the shape forward along +X.
    """
    rng = random.Random(seed)

    def _forward_mult(angle: float) -> float:
        forward = (math.cos(angle) + 1.0) * 0.5     # 0..1
        return 1.0 - asymmetry * (1.0 - forward) * 0.7

    # ----- Main irregular blob body -----
    harmonics = [(2, 0.55), (3, 0.35), (5, 0.20), (7, 0.10)]
    phases = [rng.uniform(0.0, math.tau) for _ in harmonics]
    blob = []
    for i in range(blob_points):
        angle = (i / blob_points) * math.tau
        noise = sum(amp * math.sin(n * angle + ph)
                    for (n, amp), ph in zip(harmonics, phases))
        r = base_radius * (1.0 + blob_irregularity * noise)
        r *= _forward_mult(angle)
        blob.append((r * math.cos(angle), r * math.sin(angle)))

    # ----- Long thin rays -----
    rays = []
    num_rays = rng.randint(*ray_count_range)
    for _ in range(num_rays):
        angle = rng.uniform(0.0, math.tau)
        if asymmetry > 0.0 and math.cos(angle) < 0.0 \
                and rng.random() < asymmetry * 0.7:
            # Reflect back-hemisphere rays forward.
            angle = math.pi - angle
        if rng.random() < ray_long_prob:
            length_mult = rng.uniform(*ray_long_range)
        else:
            length_mult = rng.uniform(*ray_length_range)
        length_mult *= _forward_mult(angle)
        outer = base_radius * length_mult
        inner = base_radius * 0.85
        width_deg = rng.uniform(*ray_width_range)
        tip_curl = rng.uniform(-4.0, 4.0)
        half_w = math.radians(width_deg) * 0.5
        tip_ang = angle + math.radians(tip_curl)
        tip = (outer * math.cos(tip_ang), outer * math.sin(tip_ang))
        left = (inner * math.cos(angle + half_w),
                inner * math.sin(angle + half_w))
        right = (inner * math.cos(angle - half_w),
                 inner * math.sin(angle - half_w))
        rays.append([left, tip, right])

    # ----- Satellite droplets -----
    droplets = []
    for _ in range(droplet_count):
        if asymmetry > 0.0:
            drop_angle = rng.uniform(-math.pi * (1.0 - asymmetry * 0.8),
                                      math.pi * (1.0 - asymmetry * 0.8))
        else:
            drop_angle = rng.uniform(0.0, math.tau)
        dist = base_radius * rng.uniform(droplet_min_dist, droplet_max_dist)
        dist *= _forward_mult(drop_angle)
        drop_r = base_radius * rng.uniform(0.06, 0.16)
        cx = dist * math.cos(drop_angle)
        cz = dist * math.sin(drop_angle)
        num_verts = rng.randint(6, 9)
        drop_poly = []
        for i in range(num_verts):
            a = (i / num_verts) * math.tau
            r = drop_r * (0.75 + rng.uniform(-0.15, 0.15))
            drop_poly.append((cx + r * math.cos(a), cz + r * math.sin(a)))
        droplets.append(drop_poly)

    return {"blob": blob, "rays": rays, "droplets": droplets}


def _extrude_facet(node: str, thickness: float) -> None:
    """Give a flat facet real dome-shaped volume by extruding it in
    several small steps, each with a progressively tighter taper. The
    resulting side profile is a rounded pillow — thickest at the
    centre, curving smoothly down to zero at the perimeter — instead
    of the straight prism you'd get from a single-shot extrude.

    Steps are chosen so the total height still equals ``thickness`` and
    the ratio of consecutive scales approximates a cos(θ) fall-off
    (dense taper near the top, gentle near the base). Final polySoftEdge
    smooths shading across the resulting side rings.
    """
    if thickness <= 0.0:
        return
    faces = f"{node}.f[*]"

    # (height fraction of `thickness`, relative scale applied to top
    # face each step). Cumulative scale after all steps ≈ 0.94 · 0.78
    # · 0.55 · 0.30 ≈ 0.12 — nearly a point at the summit, so the
    # profile domes without leaving a visible flat top.
    steps = (
        (0.32, 0.94),   # base → lower shoulder: barely taper
        (0.30, 0.80),   # lower → mid
        (0.24, 0.60),   # mid → upper
        (0.14, 0.35),   # upper → cap
    )
    for height_frac, scale_frac in steps:
        step_h = thickness * height_frac
        try:
            cmds.polyExtrudeFacet(faces, ltz=step_h,
                                  keepFacesTogether=True,
                                  localScaleX=scale_frac,
                                  localScaleZ=scale_frac,
                                  ch=False)
        except Exception:
            try:
                cmds.polyExtrudeFace(faces, ltz=step_h,
                                     keepFacesTogether=True,
                                     localScaleX=scale_frac,
                                     localScaleZ=scale_frac,
                                     ch=False)
            except Exception:
                break

    # Smooth shading so the multi-step side rings read as one
    # continuous curved surface instead of a stack of visible bands.
    try:
        cmds.polySoftEdge(node, angle=180, ch=False)
    except Exception:
        pass


def _create_splash_facet(
    name: str,
    base_radius: float,
    thickness: float = 0.05,
    **geometry_kwargs,
) -> str:
    """Build the splash as real Maya polys: one facet per piece (blob,
    rays, droplets), each extruded upward by ``thickness`` × base_radius
    so the splat has a bit of volume, then polyUnited into a single
    selectable mesh.
    """
    geom = compute_splash_geometry(base_radius=base_radius, **geometry_kwargs)

    pieces = []

    body = cmds.polyCreateFacet(
        p=[(x, 0.0, z) for x, z in geom["blob"]],
        ch=False, n=f"{name}_body",
    )[0]
    _extrude_facet(body, thickness * base_radius)
    pieces.append(body)

    for i, ray_verts in enumerate(geom["rays"]):
        ray = cmds.polyCreateFacet(
            p=[(x, 0.0, z) for x, z in ray_verts],
            ch=False, n=f"{name}_ray{i}",
        )[0]
        # Rays are thinner in silhouette; give them a proportional
        # (slightly thinner) extrude so they don't visually dominate.
        _extrude_facet(ray, thickness * base_radius * 0.6)
        pieces.append(ray)

    for i, drop_verts in enumerate(geom["droplets"]):
        drop = cmds.polyCreateFacet(
            p=[(x, 0.0, z) for x, z in drop_verts],
            ch=False, n=f"{name}_drop{i}",
        )[0]
        _extrude_facet(drop, thickness * base_radius * 0.5)
        pieces.append(drop)

    if len(pieces) > 1:
        combined = cmds.polyUnite(pieces, ch=False)[0]
        cmds.delete(combined, ch=True)
        combined = cmds.rename(combined, name)
        return combined
    return cmds.rename(pieces[0], name)


def _create_default_splat_mesh(name: str, base_radius: float = 1.0,
                                asymmetry: float = 0.0,
                                thickness: float = 0.05,
                                seed: Optional[int] = None) -> str:
    return _create_splash_facet(name=name, base_radius=base_radius,
                                thickness=thickness,
                                asymmetry=asymmetry, seed=seed)


# --------------------------------------------------------------------------- #
# Orientation helpers
# --------------------------------------------------------------------------- #

def _orient_splat(node: str, normal: Vec3,
                  tangent_world: Optional[Vec3] = None) -> None:
    """Set the splat's world rotation so its local basis matches the
    surface frame in one shot, avoiding the numerical drift and
    quaternion-axis ambiguity of a two-step orient-then-rotate:

        local +Y  =  normal
        local +X  =  tangent (projected perpendicular to normal)
        local +Z  =  normal × tangent          (right-handed complement)

    When ``tangent_world`` is None or degenerate we pick any world
    vector perpendicular to normal so the frame is still well-defined
    — orientation is arbitrary around normal in that case (rotation
    jitter takes over after this).
    """
    n = _om.MVector(float(normal[0]), float(normal[1]),
                    float(normal[2])).normal()

    if tangent_world is not None:
        t = _om.MVector(float(tangent_world[0]),
                        float(tangent_world[1]),
                        float(tangent_world[2]))
        # Project out any component parallel to the normal — the
        # tangent must lie in the surface plane.
        t = t - n * (t * n)
        if t.length() < 1e-6:
            t = None
        else:
            t = t.normal()
    else:
        t = None

    if t is None:
        # Pick an arbitrary perpendicular. Choosing world +X when it's
        # not near-parallel to the normal, otherwise world +Z.
        seed = _om.MVector(1.0, 0.0, 0.0) if abs(n.x) < 0.9 \
            else _om.MVector(0.0, 0.0, 1.0)
        t = (seed - n * (seed * n)).normal()

    z = (n ^ t).normal()   # normal × tangent = binormal (local +Z)

    # Maya's MMatrix layout — each "row" is a basis vector in world.
    mat = _om.MMatrix((
        t.x, t.y, t.z, 0.0,
        n.x, n.y, n.z, 0.0,
        z.x, z.y, z.z, 0.0,
        0.0, 0.0, 0.0, 1.0,
    ))
    euler = _om.MTransformationMatrix(mat).rotation()
    cmds.xform(node, ws=True, ro=(
        math.degrees(euler.x),
        math.degrees(euler.y),
        math.degrees(euler.z),
    ))


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
    thickness: float = 0.05,
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
                                           thickness=thickness,
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

    _orient_splat(splat, (nx, ny, nz), tangent_direction)

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
