"""Ballistic trajectory math.

Pure Python, no Maya dependencies — kept separate so it can be unit-tested
outside of Maya.
"""

from __future__ import annotations

import math
from typing import Sequence, Tuple, List

Vec3 = Tuple[float, float, float]


def solve_ballistic(
    start: Sequence[float],
    target: Sequence[float],
    speed: float,
    gravity: float,
    prefer_low_arc: bool = True,
) -> Vec3:
    """Solve for an initial velocity vector that launches a projectile from
    ``start`` toward ``target`` at the given ``speed`` under constant
    ``gravity`` (acting on -Y).

    If the target is unreachable at the requested speed, falls back to a
    direct-aim vector so the tool always produces *some* usable trajectory
    (over/undershoot is acceptable — the animator will adjust it anyway).
    """
    sx, sy, sz = float(start[0]), float(start[1]), float(start[2])
    tx, ty, tz = float(target[0]), float(target[1]), float(target[2])

    dx = tx - sx
    dy = ty - sy
    dz = tz - sz

    horizontal = math.sqrt(dx * dx + dz * dz)
    s = float(speed)
    g = float(gravity)

    if horizontal < 1e-6:
        # Straight up (or already at target). Launch straight up.
        return (0.0, s, 0.0)

    if g <= 1e-9:
        # No gravity: aim direct.
        length = math.sqrt(dx * dx + dy * dy + dz * dz)
        return (dx / length * s, dy / length * s, dz / length * s)

    discriminant = s ** 4 - g * (g * horizontal * horizontal + 2.0 * dy * s * s)
    if discriminant < 0:
        # Unreachable at this speed: direct aim.
        length = math.sqrt(dx * dx + dy * dy + dz * dz)
        return (dx / length * s, dy / length * s, dz / length * s)

    root = math.sqrt(discriminant)
    numerator = s * s - root if prefer_low_arc else s * s + root
    angle = math.atan2(numerator, g * horizontal)

    hdir_x = dx / horizontal
    hdir_z = dz / horizontal
    v_h = s * math.cos(angle)
    v_y = s * math.sin(angle)
    return (v_h * hdir_x, v_y, v_h * hdir_z)


def generate_positions(
    start: Sequence[float],
    v0: Sequence[float],
    gravity: float,
    num_frames: int,
    fps: float = 24.0,
) -> List[Vec3]:
    """Sample the projectile position for ``num_frames`` consecutive frames,
    starting at t=0. Returns a list of ``(x, y, z)`` tuples.

    ``gravity`` is applied on -Y.
    """
    if num_frames < 1:
        return []
    dt = 1.0 / float(fps)
    sx, sy, sz = float(start[0]), float(start[1]), float(start[2])
    vx, vy, vz = float(v0[0]), float(v0[1]), float(v0[2])
    g = float(gravity)

    positions: List[Vec3] = []
    for i in range(num_frames):
        t = i * dt
        px = sx + vx * t
        py = sy + vy * t - 0.5 * g * t * t
        pz = sz + vz * t
        positions.append((px, py, pz))
    return positions


def central_difference_velocity(
    positions: Sequence[Vec3],
    dt: float,
) -> List[Vec3]:
    """Compute per-frame velocity via central difference. First/last frames
    use forward/backward difference. Result has the same length as input."""
    n = len(positions)
    if n == 0:
        return []
    if n == 1:
        return [(0.0, 0.0, 0.0)]

    vels: List[Vec3] = []
    for i in range(n):
        if i == 0:
            a, b = positions[0], positions[1]
            scale = 1.0 / dt
        elif i == n - 1:
            a, b = positions[n - 2], positions[n - 1]
            scale = 1.0 / dt
        else:
            a, b = positions[i - 1], positions[i + 1]
            scale = 0.5 / dt
        vels.append((
            (b[0] - a[0]) * scale,
            (b[1] - a[1]) * scale,
            (b[2] - a[2]) * scale,
        ))
    return vels


def frames_per_second_from_maya_unit(unit: str) -> float:
    """Map a Maya time unit string (as returned by ``cmds.currentUnit(query=True, time=True)``)
    to an fps value. Falls back to 24 for unknown units."""
    mapping = {
        "game": 15.0,
        "film": 24.0,
        "pal": 25.0,
        "ntsc": 30.0,
        "show": 48.0,
        "palf": 50.0,
        "ntscf": 60.0,
        "23.976fps": 23.976,
        "29.97fps": 29.97,
        "59.94fps": 59.94,
    }
    if unit in mapping:
        return mapping[unit]
    if unit.endswith("fps"):
        try:
            return float(unit[:-3])
        except ValueError:
            pass
    return 24.0
