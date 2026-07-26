"""Collision detection between a discrete base trajectory and one or
more collider meshes.

We rely on Maya's ``MFnMesh.closestIntersection`` to do the actual
ray-mesh test. The projectile is treated as a point — a full swept-
sphere test would be more accurate but is overkill for the prototype
and doesn't change the artistic workflow: the animator adjusts the
final hit position with the offset controllers anyway.
"""

from __future__ import annotations

import math
from typing import Iterable, List, Optional, Sequence, Tuple

try:
    from maya import cmds  # type: ignore
    from maya.api import OpenMaya as _om  # type: ignore
except ImportError:  # pragma: no cover
    cmds = None  # type: ignore
    _om = None  # type: ignore


Vec3 = Tuple[float, float, float]


class ImpactInfo:
    """Where / when / how the projectile hit a collider."""

    __slots__ = ("frame", "sub_frame", "position", "normal",
                 "collider", "velocity")

    def __init__(self,
                 frame: int,
                 sub_frame: float,
                 position: Vec3,
                 normal: Vec3,
                 collider: str,
                 velocity: Vec3):
        self.frame = frame
        self.sub_frame = sub_frame        # frame + fractional (0..1)
        self.position = position
        self.normal = normal              # surface normal at hit point
        self.collider = collider          # mesh name
        self.velocity = velocity          # base velocity vector at impact

    def __repr__(self) -> str:
        return (f"<Impact f={self.sub_frame:.2f} on {self.collider!r} "
                f"pos={self.position}>")


def _mfn_mesh(mesh_name: str) -> "_om.MFnMesh":
    sel = _om.MSelectionList()
    sel.add(mesh_name)
    dag = sel.getDagPath(0)
    if dag.node().apiType() == _om.MFn.kTransform:
        dag.extendToShape()
    return _om.MFnMesh(dag)


def _raycast_segment(
    mesh_name: str,
    origin: Sequence[float],
    direction: Sequence[float],
    max_dist: float,
) -> Optional[Tuple[Vec3, Vec3, float]]:
    """Cast a ray from ``origin`` in ``direction`` (unit vector) up to
    ``max_dist`` scene units. Returns ``(hit_position, hit_normal,
    ray_param)`` on hit, or ``None`` if the ray misses.

    ``ray_param`` is the distance along the ray, in scene units, from
    origin to hit point (0..max_dist).
    """
    mfn = _mfn_mesh(mesh_name)
    ray_src = _om.MFloatPoint(float(origin[0]), float(origin[1]), float(origin[2]))
    ray_dir = _om.MFloatVector(float(direction[0]), float(direction[1]),
                               float(direction[2]))
    result = mfn.closestIntersection(
        ray_src, ray_dir,
        _om.MSpace.kWorld,
        float(max_dist),
        False,       # testBothDirections
    )
    if result is None:
        return None
    hit_pt, hit_ray_param, hit_face, _hit_tri, _b1, _b2 = result
    if hit_face < 0:
        return None
    normal = mfn.getPolygonNormal(hit_face, _om.MSpace.kWorld)
    return (
        (hit_pt.x, hit_pt.y, hit_pt.z),
        (normal.x, normal.y, normal.z),
        float(hit_ray_param),
    )


def detect_impact(
    positions: Sequence[Vec3],
    velocities: Sequence[Vec3],
    start_frame: int,
    collision_meshes: Iterable[str],
) -> Optional[ImpactInfo]:
    """Walk consecutive trajectory segments and return the *first* hit,
    or ``None`` if the projectile never touches any collider in the
    sampled range.

    ``positions`` and ``velocities`` are the per-frame base samples the
    system builds; ``start_frame`` is the frame index of ``positions[0]``.
    """
    if cmds is None or _om is None:
        raise RuntimeError("detect_impact must be called from within Maya.")

    colliders: List[str] = [m for m in collision_meshes if m]
    if not colliders or len(positions) < 2:
        return None

    for i in range(len(positions) - 1):
        p0 = positions[i]
        p1 = positions[i + 1]
        dx, dy, dz = p1[0] - p0[0], p1[1] - p0[1], p1[2] - p0[2]
        seg_len = math.sqrt(dx * dx + dy * dy + dz * dz)
        if seg_len < 1e-6:
            continue
        direction = (dx / seg_len, dy / seg_len, dz / seg_len)

        best: Optional[Tuple[str, Vec3, Vec3, float]] = None
        for mesh in colliders:
            if not cmds.objExists(mesh):
                continue
            hit = _raycast_segment(mesh, p0, direction, seg_len)
            if hit is None:
                continue
            pos, nrm, param = hit
            if best is None or param < best[3]:
                best = (mesh, pos, nrm, param)

        if best is None:
            continue

        mesh, pos, nrm, param = best
        frac = max(0.0, min(1.0, param / seg_len))
        sub_frame = float(start_frame + i) + frac
        frame_int = int(math.floor(sub_frame))
        v = velocities[min(i, len(velocities) - 1)]
        return ImpactInfo(
            frame=frame_int,
            sub_frame=sub_frame,
            position=pos,
            normal=nrm,
            collider=mesh,
            velocity=v,
        )

    return None
