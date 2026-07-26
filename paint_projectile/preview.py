"""Live 3D preview in the Maya viewport.

Rebuilds an in-scene approximation of what GENERATE would produce, so
the animator can see the ball flying at the real speed / gravity, hit
the timeline play button, and iterate on sliders. Nothing here is
meant to survive past preview — GENERATE creates a fresh permanent
system when the user is happy with what they see.

Design notes:

* All preview nodes live under a single group named
  ``PREVIEW_GROUP_NAME``. Rebuild deletes and recreates the whole
  group; caller wrapper suspends undo around the delete/create so the
  undo queue doesn't fill with intermediate states.

* Ball motion is keyed per-frame on ``translate`` so scrubbing the
  timeline shows the real ballistic arc. This is much cheaper than
  wiring up the full offset/timing/camera pipeline that GENERATE
  builds — the preview only needs to *look* right, not be editable.

* If colliders are supplied AND the ray-cast hits one, an impact
  animation + splat mesh are generated at that point using the same
  code paths as the real system, so the preview shape matches the
  eventual output exactly (given the same shape seed).
"""

from __future__ import annotations

import math
from typing import Iterable, Optional, Sequence

from . import collision as _collision
from . import impact as _impact
from . import splat as _splat
from . import trajectory as _traj

try:
    from maya import cmds  # type: ignore
except ImportError:  # pragma: no cover
    cmds = None  # type: ignore


PREVIEW_GROUP_NAME = "paint_projectile_LIVE_PREVIEW_GRP"
_TRAJECTORY_CURVE = "paint_projectile_preview_trajectory"


def clear_preview() -> None:
    """Delete all preview nodes if any exist."""
    if cmds is None:
        return
    if cmds.objExists(PREVIEW_GROUP_NAME):
        try:
            cmds.delete(PREVIEW_GROUP_NAME)
        except Exception:
            pass


def _safe_world_pos(node: str, default=(0.0, 0.0, 0.0)):
    if not node or not cmds.objExists(node):
        return default
    try:
        return tuple(cmds.xform(node, q=True, ws=True, t=True))
    except Exception:
        return default


def _make_trajectory_curve(name: str, positions: Sequence, parent: str) -> str:
    """A degree-1 (linear) NURBS curve through the trajectory samples —
    a visual guide showing the arc the ball will follow. Cheap to
    build and doesn't affect evaluation."""
    if len(positions) < 2:
        return ""
    curve = cmds.curve(n=name, d=1, p=[tuple(p) for p in positions])
    curve = cmds.parent(curve, parent)[0]
    try:
        shape = cmds.listRelatives(curve, s=True)[0]
        cmds.setAttr(f"{shape}.overrideEnabled", 1)
        cmds.setAttr(f"{shape}.overrideColor", 18)   # cyan
    except Exception:
        pass
    return curve


def rebuild(
    mesh: str,
    start_node: str,
    target_node: str,
    speed: float,
    gravity: float,
    start_frame: int,
    end_frame: int,
    collision_meshes: Optional[Iterable[str]] = None,
    splat_templates: Optional[Iterable[str]] = None,
    splat_scale: float = 3.0,
    splat_surface_offset: float = 0.01,
    splat_grow_frames: int = 2,
    splat_max_stretch: float = 1.8,
    splat_min_squeeze: float = 0.55,
    splat_rotation_jitter: float = 12.0,
    splat_forward_bias: float = 1.0,
    splat_thickness: float = 0.08,
    impact_squash_frames: int = 1,
    shape_seed: int = 0,
) -> Optional[str]:
    """Delete any existing preview and rebuild fresh.

    Returns the preview group name, or None if a preview couldn't be
    made (missing mesh / start / target).
    """
    if cmds is None:
        return None

    # Wrap the whole rebuild in an undo chunk so a single Ctrl-Z from
    # the user undoes everything at once (or, better, so intermediate
    # deletes don't spam the undo history with dozens of tiny steps).
    cmds.undoInfo(openChunk=True, chunkName="paint_projectile preview rebuild")
    try:
        return _rebuild_impl(
            mesh, start_node, target_node,
            speed, gravity, start_frame, end_frame,
            list(collision_meshes) if collision_meshes else [],
            list(splat_templates) if splat_templates else [],
            splat_scale, splat_surface_offset, splat_grow_frames,
            splat_max_stretch, splat_min_squeeze, splat_rotation_jitter,
            splat_forward_bias, splat_thickness, impact_squash_frames,
            int(shape_seed),
        )
    finally:
        cmds.undoInfo(closeChunk=True)


def _rebuild_impl(
    mesh, start_node, target_node,
    speed, gravity, start_frame, end_frame,
    colliders, splat_templates,
    splat_scale, splat_surface_offset, splat_grow_frames,
    splat_max_stretch, splat_min_squeeze, splat_rotation_jitter,
    splat_forward_bias, splat_thickness, impact_squash_frames,
    shape_seed,
):
    if end_frame < start_frame:
        end_frame = start_frame + 1

    if not mesh or not cmds.objExists(mesh):
        clear_preview()
        return None

    start_pos = _safe_world_pos(start_node)
    target_pos = _safe_world_pos(target_node, default=(start_pos[0] + 5.0,
                                                        start_pos[1],
                                                        start_pos[2]))

    # Solve ballistic + sample positions/velocities.
    v0 = _traj.solve_ballistic(start_pos, target_pos, speed, gravity)
    try:
        fps = _traj.frames_per_second_from_maya_unit(
            cmds.currentUnit(q=True, time=True))
    except Exception:
        fps = 24.0
    num_frames = int(end_frame - start_frame + 1)
    positions = _traj.generate_positions(start_pos, v0, gravity, num_frames,
                                          fps=fps)
    velocities = _traj.central_difference_velocity(positions, dt=1.0 / fps)
    if not positions:
        clear_preview()
        return None

    # Wipe the old preview and start fresh.
    clear_preview()
    grp = cmds.group(em=True, n=PREVIEW_GROUP_NAME)
    try:
        cmds.setAttr(f"{grp}.overrideEnabled", 1)
        cmds.setAttr(f"{grp}.overrideDisplayType", 0)   # keep selectable
    except Exception:
        pass

    # Trajectory guide curve.
    _make_trajectory_curve(_TRAJECTORY_CURVE, positions, grp)

    # Duplicate the source mesh as the preview ball; zero its local
    # transform so the keyframes are authoritative.
    ball = cmds.duplicate(mesh, n="paint_projectile_preview_ball", rr=True)[0]
    ball = cmds.parent(ball, grp)[0]
    for axis in "XYZ":
        try:
            cmds.setAttr(f"{ball}.translate{axis}", 0)
        except Exception:
            pass

    # Keyframe ball translate along the trajectory.
    for i, pos in enumerate(positions):
        frame = start_frame + i
        for axis, val in zip("XYZ", pos):
            cmds.setKeyframe(ball, at=f"translate{axis}", t=frame, v=float(val))

    # Optional collision + impact animation + splat.
    impact_info = None
    if colliders:
        try:
            impact_info = _collision.detect_impact(
                positions=positions, velocities=velocities,
                start_frame=start_frame, collision_meshes=colliders,
            )
        except Exception:
            impact_info = None

    if impact_info is not None:
        # The base-trajectory samples land ON frame boundaries, but
        # the ray-cast hit sits BETWEEN two samples (sub_frame). Left
        # alone, the ball would key to positions[impact_frame] one
        # sample short of the actual contact point, so the ball
        # visibly floats a few units away from where the splat lands.
        # Overwrite the impact-frame key with the exact hit position
        # so the two land on top of each other.
        for axis, val in zip("XYZ", impact_info.position):
            cmds.setKeyframe(ball, at=f"translate{axis}",
                             t=impact_info.frame, v=float(val))
        try:
            _impact.apply_impact_animation(
                projectile_xform=ball,
                impact_frame=impact_info.frame,
                squash_frames=impact_squash_frames,
            )
        except Exception:
            pass

        try:
            projectile_radius = _splat.projectile_bounding_radius(mesh)
        except Exception:
            projectile_radius = 1.0
        splat_base_scale = projectile_radius * float(splat_scale)
        stretch_along, stretch_perp, tan_dir, grazing = \
            _splat.compute_splat_stretch(
                velocity=impact_info.velocity,
                normal=impact_info.normal,
                max_stretch=splat_max_stretch,
                min_squeeze=splat_min_squeeze,
            )
        forward_offset = (grazing * stretch_along
                          * splat_base_scale * float(splat_forward_bias))
        shape_asymmetry = grazing * float(splat_forward_bias)
        try:
            _splat.create_splats_from_candidates(
                base_name="paint_projectile_preview_splat",
                position=impact_info.position,
                normal=impact_info.normal,
                template_candidates=splat_templates,
                parent=grp,
                surface_offset=splat_surface_offset,
                spawn_frame=impact_info.frame + impact_squash_frames,
                grow_frames=splat_grow_frames,
                base_scale=splat_base_scale,
                stretch_along_tangent=stretch_along,
                stretch_perp_tangent=stretch_perp,
                tangent_direction=tan_dir,
                forward_offset=forward_offset,
                shape_asymmetry=shape_asymmetry,
                thickness=splat_thickness,
                rotation_jitter_degrees=splat_rotation_jitter,
                seed=shape_seed,
            )
        except Exception:
            pass

    # Snap the playback range to cover the preview so the user can
    # hit spacebar immediately and see the whole shot.
    try:
        cmds.playbackOptions(min=start_frame, max=end_frame,
                             ast=start_frame, aet=end_frame)
        cmds.currentTime(start_frame, edit=True)
    except Exception:
        pass

    return grp
