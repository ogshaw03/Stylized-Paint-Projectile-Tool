"""Stylized Paint Projectile Tool - Prototype.

Maya 2023 / Python.

Implements the Section 24 prototype scope of the spec:

    1. Specify a Projectile mesh.
    2. Specify Start / Target locators.
    3. Generate a base parabolic trajectory.
    4. Drive the projectile geometry along the trajectory.
    5. Add an Animator Offset Controller.
    6. Non-destructive frame-by-frame position adjustment via the offset controller.
    7. Trajectory Time attribute.
    8. Timing warp via keyed Trajectory Time.
    9. Camera Space Offset.
    10. Auto Smear values computed from projectile velocity.

Design principle: the base trajectory is stored on hidden animation curves that
are never modified after generation. All animator adjustments happen on separate
keyable attributes on the controller and are combined with the base at
evaluation time.
"""

from .system import create_projectile_system, ProjectileSystem
from .trajectory import solve_ballistic, generate_positions

__all__ = [
    "create_projectile_system",
    "ProjectileSystem",
    "solve_ballistic",
    "generate_positions",
]

__version__ = "0.2.0"
