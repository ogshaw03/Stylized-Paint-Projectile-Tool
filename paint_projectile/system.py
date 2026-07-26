"""Projectile system creation.

Builds the DAG + DG network for a single projectile:

    <name>_GRP                       (top group)
        <name>_CTRL                  (nurbs-curve controller with all keyable attrs)
        <name>_projectile            (transform driven by the combined position)
            <mesh>                   (duplicated user projectile mesh)

Hidden helper nodes (parented under <name>_GRP):

    <name>_baseX / _baseY / _baseZ   (animCurveUL, base parabola samples;
                                      input = trajectoryTime, output = position)
    <name>_velX  / _velY  / _velZ    (animCurveUL, base velocity samples)
    <name>_camMult                   (pointMatrixMult, camera-space offset -> world)
    <name>_sum                       (plusMinusAverage, base + world + camera)
    <name>_velMag                    (distanceBetween, |velocity|)

Non-destructive:
    * Base curves are set once at generation time and never touched again.
    * Animator adjustments (worldOffset*, cameraOffset*, cameraDepth,
      trajectoryTime) are on the controller and can be freely keyed.
"""

from __future__ import annotations

from typing import Iterable, List, Optional, Sequence, Tuple

from . import collision as _collision
from . import impact as _impact
from . import splat as _splat
from . import trajectory as _traj

try:
    from maya import cmds  # type: ignore
except ImportError:  # pragma: no cover - allow import outside Maya for docs / tests
    cmds = None  # type: ignore


# --------------------------------------------------------------------------- #
# Controller attribute schema
# --------------------------------------------------------------------------- #

def _add_separator(node: str, label: str) -> None:
    attr = f"__{label.replace(' ', '_')}"
    if not cmds.attributeQuery(attr, node=node, exists=True):
        cmds.addAttr(node, ln=attr, nn=f"── {label} ──", at="enum",
                     en="────────:", k=False)
        cmds.setAttr(f"{node}.{attr}", channelBox=True, lock=True)


def _add_float(node: str, name: str, default: float = 0.0,
               keyable: bool = True, min_val: Optional[float] = None,
               max_val: Optional[float] = None) -> None:
    if cmds.attributeQuery(name, node=node, exists=True):
        return
    kwargs = {"ln": name, "at": "double", "dv": float(default), "k": keyable}
    if min_val is not None:
        kwargs["min"] = min_val
    if max_val is not None:
        kwargs["max"] = max_val
    cmds.addAttr(node, **kwargs)


def _add_bool(node: str, name: str, default: bool = True) -> None:
    if cmds.attributeQuery(name, node=node, exists=True):
        return
    cmds.addAttr(node, ln=name, at="bool", dv=int(default), k=True)


def _build_controller_attributes(ctrl: str) -> None:
    _add_separator(ctrl, "WORLD OFFSET")
    _add_float(ctrl, "worldOffsetX")
    _add_float(ctrl, "worldOffsetY")
    _add_float(ctrl, "worldOffsetZ")

    _add_separator(ctrl, "CAMERA OFFSET")
    _add_float(ctrl, "cameraOffsetX")
    _add_float(ctrl, "cameraOffsetY")
    _add_float(ctrl, "cameraDepth")

    _add_separator(ctrl, "TIMING")
    _add_float(ctrl, "trajectoryTime", default=0.0)

    _add_separator(ctrl, "AUTO SMEAR")
    _add_bool(ctrl, "autoSmear", default=True)
    # Readonly-ish outputs (driven by network; leave editable so animator can
    # still poke or key-block them if they want a manual value).
    _add_float(ctrl, "velocityMagnitude", default=0.0, keyable=False)
    cmds.setAttr(f"{ctrl}.velocityMagnitude", channelBox=True)
    _add_float(ctrl, "velocityX", default=0.0, keyable=False)
    cmds.setAttr(f"{ctrl}.velocityX", channelBox=True)
    _add_float(ctrl, "velocityY", default=0.0, keyable=False)
    cmds.setAttr(f"{ctrl}.velocityY", channelBox=True)
    _add_float(ctrl, "velocityZ", default=0.0, keyable=False)
    cmds.setAttr(f"{ctrl}.velocityZ", channelBox=True)


# --------------------------------------------------------------------------- #
# animCurveUL helpers
# --------------------------------------------------------------------------- #

def _make_ul_curve(name: str, samples: Sequence[Tuple[float, float]]) -> str:
    """Create an animCurveUL and set ``(input, value)`` samples on it.
    Returns the node name."""
    node = cmds.createNode("animCurveUL", n=name)
    for input_val, value in samples:
        cmds.setKeyframe(node, float=input_val, value=value,
                         inTangentType="linear", outTangentType="linear")
    return node


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #

class ProjectileSystem:
    """Handle to a generated projectile system. Wraps the created nodes so
    callers can query / clean up after generation."""

    def __init__(self, name: str, group: str, controller: str, projectile: str,
                 mesh: str, base_curves: Tuple[str, str, str],
                 velocity_curves: Tuple[str, str, str],
                 impact: Optional["_collision.ImpactInfo"] = None,
                 splat: Optional[str] = None):
        self.name = name
        self.group = group
        self.controller = controller
        self.projectile = projectile
        self.mesh = mesh
        self.base_curves = base_curves
        self.velocity_curves = velocity_curves
        self.impact = impact       # ImpactInfo or None if no collision
        self.splat = splat         # splat transform name or None

    def __repr__(self) -> str:
        return f"<ProjectileSystem {self.name!r} ctrl={self.controller!r}>"


def _unique(base: str) -> str:
    """Return ``base`` if free, else ``base1``, ``base2`` etc."""
    if not cmds.objExists(base):
        return base
    i = 1
    while cmds.objExists(f"{base}{i}"):
        i += 1
    return f"{base}{i}"


def _active_camera_shape() -> Optional[str]:
    """Best-effort: return the active model panel's camera shape, or None."""
    try:
        panel = cmds.getPanel(withFocus=True)
    except Exception:
        panel = None
    if panel and cmds.getPanel(typeOf=panel) == "modelPanel":
        cam = cmds.modelPanel(panel, q=True, camera=True)
    else:
        cams = cmds.ls(type="camera")
        cam = None
        for c in cams:
            if cmds.getAttr(f"{c}.renderable"):
                cam = c
                break
        if cam is None and cams:
            cam = cams[0]
    if cam is None:
        return None
    if cmds.nodeType(cam) == "transform":
        shapes = cmds.listRelatives(cam, s=True, type="camera") or []
        return shapes[0] if shapes else None
    return cam


def create_projectile_system(
    mesh: str,
    start: str,
    target: str,
    speed: float = 20.0,
    gravity: float = 9.8,
    start_frame: Optional[int] = None,
    end_frame: Optional[int] = None,
    name: str = "paintBall",
    camera: Optional[str] = None,
    collision_meshes: Optional[Iterable[str]] = None,
    splat_template: Optional[str] = None,
    splat_templates: Optional[Iterable[str]] = None,
    splat_scale: float = 3.0,
    splat_surface_offset: float = 0.01,
    splat_grow_frames: int = 2,
    splat_max_stretch: float = 1.8,
    splat_min_squeeze: float = 0.55,
    splat_rotation_jitter: float = 12.0,
    splat_forward_bias: float = 1.0,
    impact_squash_frames: int = 1,
) -> ProjectileSystem:
    """Generate a projectile system.

    Parameters
    ----------
    mesh : str
        Transform name of the source mesh to use as the projectile. It is
        duplicated; the original is left untouched.
    start, target : str
        Transform names (locators, controllers, anything with a world
        position). Their world positions at scene evaluation time drive the
        ballistic solve.
    speed : float
        Initial launch speed in scene units per second.
    gravity : float
        Gravitational acceleration in scene units per second squared, applied
        on -Y.
    start_frame, end_frame : int, optional
        Frame range for the base trajectory. Defaults to the current playback
        range.
    name : str
        Base name for the created nodes.
    camera : str, optional
        Camera transform or shape whose orientation drives the camera-space
        offset. Defaults to the active viewport camera.
    collision_meshes : iterable of str, optional
        Collider meshes to ray-cast the base trajectory against. If given
        and a hit is detected, the projectile squashes and hides at
        impact and a splat mesh is spawned on the hit surface.
    splat_template, splat_templates : optional
        Either a single template mesh (``splat_template``) or a list of
        candidates (``splat_templates``) — one is picked at random.
        If neither is provided a default flat disc is generated.
    splat_scale : float
        Splat size *as a multiplier of the projectile's bounding
        radius*. Default 3.0 = splat radius is roughly 3× the ball
        radius; a small ball leaves a small splash, a big ball leaves
        a big one.
    splat_surface_offset : float
        Distance to offset the splat along the surface normal to avoid
        Z-fighting with the collider.
    splat_grow_frames : int
        Number of frames over which the splat scales from 0 to full.
    splat_max_stretch, splat_min_squeeze : float
        How much the splat deforms on a grazing hit. Perpendicular hit
        → 1.0/1.0. Fully grazing hit → stretch = max_stretch along the
        direction of travel, squeeze = min_squeeze perpendicular.
    splat_rotation_jitter : float
        Random Y-axis rotation (degrees) applied on top of the
        tangent alignment so multiple splats don't read as identical.
    splat_forward_bias : float (0..1)
        How aggressively to push the splat forward from the impact
        point so it trails in the direction of travel instead of
        radiating symmetrically around impact. 0 = symmetric (splat
        centered on impact), 1 = impact sits at the back edge of the
        stretched splat, with the whole splash extending forward.
        Only affects grazing hits — a perpendicular hit stays
        symmetric regardless of this value.
    impact_squash_frames : int
        Number of frames after impact before the projectile hides.
    """
    if cmds is None:
        raise RuntimeError("This function must be called from within Maya.")

    for node in (mesh, start, target):
        if not cmds.objExists(node):
            raise ValueError(f"Node does not exist: {node!r}")

    # Frame range
    if start_frame is None:
        start_frame = int(cmds.playbackOptions(q=True, min=True))
    if end_frame is None:
        end_frame = int(cmds.playbackOptions(q=True, max=True))
    if end_frame < start_frame:
        raise ValueError("end_frame must be >= start_frame")

    # World positions (evaluate at the start frame for a stable solve)
    cmds.currentTime(start_frame, edit=True)
    start_pos = cmds.xform(start, q=True, ws=True, t=True)
    target_pos = cmds.xform(target, q=True, ws=True, t=True)

    # Solve ballistic
    v0 = _traj.solve_ballistic(start_pos, target_pos, speed, gravity)

    fps = _traj.frames_per_second_from_maya_unit(
        cmds.currentUnit(q=True, time=True)
    )
    dt = 1.0 / fps
    num_frames = int(end_frame - start_frame + 1)
    positions = _traj.generate_positions(start_pos, v0, gravity, num_frames, fps=fps)
    velocities = _traj.central_difference_velocity(positions, dt)

    # ------------------------------------------------------------------ #
    # DAG creation
    # ------------------------------------------------------------------ #
    name = _unique(f"{name}_GRP").replace("_GRP", "")
    group = cmds.group(em=True, n=f"{name}_GRP")

    # Controller: a small nurbs circle so it's selectable in the viewport.
    # With ch=False the return list has just the transform (no history node),
    # so index rather than 2-tuple-unpack.
    ctrl = cmds.circle(n=f"{name}_CTRL", nr=(0, 1, 0), r=1.0, ch=False)[0]
    cmds.parent(ctrl, group)
    _build_controller_attributes(ctrl)

    # Projectile transform + duplicated mesh. We reparent, then explicitly
    # zero *only translate* on the mesh — rotation/scale might be part of
    # the mesh's authored orientation and shouldn't be flattened.
    proj_xform = cmds.createNode("transform", n=f"{name}_projectile", p=group)
    dup = cmds.duplicate(mesh, n=f"{name}_mesh", rr=True)[0]
    dup = cmds.parent(dup, proj_xform)[0]
    for axis in "XYZ":
        try:
            cmds.setAttr(f"{dup}.translate{axis}", 0)
        except Exception:
            pass

    # ------------------------------------------------------------------ #
    # Base + velocity animation curves (input = trajectoryTime)
    # ------------------------------------------------------------------ #
    frames = [float(start_frame + i) for i in range(num_frames)]
    base_x = _make_ul_curve(f"{name}_baseX", list(zip(frames, [p[0] for p in positions])))
    base_y = _make_ul_curve(f"{name}_baseY", list(zip(frames, [p[1] for p in positions])))
    base_z = _make_ul_curve(f"{name}_baseZ", list(zip(frames, [p[2] for p in positions])))

    vel_x = _make_ul_curve(f"{name}_velX", list(zip(frames, [v[0] for v in velocities])))
    vel_y = _make_ul_curve(f"{name}_velY", list(zip(frames, [v[1] for v in velocities])))
    vel_z = _make_ul_curve(f"{name}_velZ", list(zip(frames, [v[2] for v in velocities])))

    # ------------------------------------------------------------------ #
    # Trajectory Time: identity keys so default = frame, animator can remap
    # ------------------------------------------------------------------ #
    # Explicit start and end keys give the animator two handles to grab in
    # the Graph Editor without touching anything else.
    cmds.setKeyframe(ctrl, at="trajectoryTime", t=start_frame,
                     v=float(start_frame), inTangentType="linear",
                     outTangentType="linear")
    cmds.setKeyframe(ctrl, at="trajectoryTime", t=end_frame,
                     v=float(end_frame), inTangentType="linear",
                     outTangentType="linear")

    # trajectoryTime -> baseCurve.input (evaluate base at the warped time)
    for curve in (base_x, base_y, base_z, vel_x, vel_y, vel_z):
        cmds.connectAttr(f"{ctrl}.trajectoryTime", f"{curve}.input", f=True)

    # ------------------------------------------------------------------ #
    # Camera Space Offset -> world-space delta via pointMatrixMult
    # ------------------------------------------------------------------ #
    # cameraOffset is a 3-vector in camera-local space: (cx, cy, -depth).
    # A pointMatrixMult with vectorMultiply=1 transforms that as a direction
    # by the camera's worldMatrix — no translation component — giving the
    # world-space delta to add to the base position.
    cam_shape = None
    if camera:
        cam_shape = camera
        if cmds.nodeType(cam_shape) == "transform":
            shapes = cmds.listRelatives(cam_shape, s=True, type="camera") or []
            cam_shape = shapes[0] if shapes else None
    if cam_shape is None:
        cam_shape = _active_camera_shape()

    cam_mult = None
    if cam_shape is not None:
        cam_mult = cmds.createNode("pointMatrixMult", n=f"{name}_camMult")
        cmds.setAttr(f"{cam_mult}.vectorMultiply", 1)
        # Negate depth so positive depth = "farther from camera along -Z view axis".
        neg_depth = cmds.createNode("multiplyDivide", n=f"{name}_negDepth")
        cmds.setAttr(f"{neg_depth}.input2X", -1.0)
        cmds.connectAttr(f"{ctrl}.cameraDepth", f"{neg_depth}.input1X", f=True)

        cmds.connectAttr(f"{ctrl}.cameraOffsetX", f"{cam_mult}.inPointX", f=True)
        cmds.connectAttr(f"{ctrl}.cameraOffsetY", f"{cam_mult}.inPointY", f=True)
        cmds.connectAttr(f"{neg_depth}.outputX", f"{cam_mult}.inPointZ", f=True)
        cam_xform = cmds.listRelatives(cam_shape, p=True, f=False)[0]
        cmds.connectAttr(f"{cam_xform}.worldMatrix[0]", f"{cam_mult}.inMatrix", f=True)

    # ------------------------------------------------------------------ #
    # Final sum: base + worldOffset + cameraOffsetWorld  ->  projectile.translate
    # ------------------------------------------------------------------ #
    sum_node = cmds.createNode("plusMinusAverage", n=f"{name}_sum")
    cmds.setAttr(f"{sum_node}.operation", 1)  # sum

    cmds.connectAttr(f"{base_x}.output", f"{sum_node}.input3D[0].input3Dx", f=True)
    cmds.connectAttr(f"{base_y}.output", f"{sum_node}.input3D[0].input3Dy", f=True)
    cmds.connectAttr(f"{base_z}.output", f"{sum_node}.input3D[0].input3Dz", f=True)

    cmds.connectAttr(f"{ctrl}.worldOffsetX", f"{sum_node}.input3D[1].input3Dx", f=True)
    cmds.connectAttr(f"{ctrl}.worldOffsetY", f"{sum_node}.input3D[1].input3Dy", f=True)
    cmds.connectAttr(f"{ctrl}.worldOffsetZ", f"{sum_node}.input3D[1].input3Dz", f=True)

    if cam_mult is not None:
        cmds.connectAttr(f"{cam_mult}.outputX", f"{sum_node}.input3D[2].input3Dx", f=True)
        cmds.connectAttr(f"{cam_mult}.outputY", f"{sum_node}.input3D[2].input3Dy", f=True)
        cmds.connectAttr(f"{cam_mult}.outputZ", f"{sum_node}.input3D[2].input3Dz", f=True)

    cmds.connectAttr(f"{sum_node}.output3Dx", f"{proj_xform}.translateX", f=True)
    cmds.connectAttr(f"{sum_node}.output3Dy", f"{proj_xform}.translateY", f=True)
    cmds.connectAttr(f"{sum_node}.output3Dz", f"{proj_xform}.translateZ", f=True)

    # ------------------------------------------------------------------ #
    # Velocity outputs on the controller (raw + magnitude)
    # ------------------------------------------------------------------ #
    cmds.connectAttr(f"{vel_x}.output", f"{ctrl}.velocityX", f=True)
    cmds.connectAttr(f"{vel_y}.output", f"{ctrl}.velocityY", f=True)
    cmds.connectAttr(f"{vel_z}.output", f"{ctrl}.velocityZ", f=True)

    vmag = cmds.createNode("distanceBetween", n=f"{name}_velMag")
    cmds.connectAttr(f"{vel_x}.output", f"{vmag}.point1X", f=True)
    cmds.connectAttr(f"{vel_y}.output", f"{vmag}.point1Y", f=True)
    cmds.connectAttr(f"{vel_z}.output", f"{vmag}.point1Z", f=True)
    cmds.connectAttr(f"{vmag}.distance", f"{ctrl}.velocityMagnitude", f=True)

    # ------------------------------------------------------------------ #
    # Collision detection -> Impact animation -> Splat geometry (§14-16)
    # ------------------------------------------------------------------ #
    impact_info = None
    splat_name = None
    colliders = list(collision_meshes) if collision_meshes else []
    if colliders:
        impact_info = _collision.detect_impact(
            positions=positions,
            velocities=velocities,
            start_frame=start_frame,
            collision_meshes=colliders,
        )
        if impact_info is not None:
            # Freeze the projectile at the impact frame: squash + hide.
            _impact.apply_impact_animation(
                projectile_xform=proj_xform,
                impact_frame=impact_info.frame,
                squash_frames=impact_squash_frames,
            )
            # Also freeze trajectory time so worldOffset / cameraOffset
            # keys the animator adds after impact don't drag a hidden
            # ball around behind the splat.
            cmds.setKeyframe(ctrl, at="trajectoryTime",
                             t=impact_info.frame,
                             v=float(impact_info.frame),
                             inTangentType="linear",
                             outTangentType="linear")
            hold_frame = impact_info.frame + impact_squash_frames + 1
            if hold_frame <= end_frame:
                cmds.setKeyframe(ctrl, at="trajectoryTime",
                                 t=hold_frame,
                                 v=float(impact_info.frame),
                                 inTangentType="linear",
                                 outTangentType="linear")

            # Spawn the splat under the same group so the whole shot is
            # one selectable unit.
            candidates = []
            if splat_templates:
                candidates = [m for m in splat_templates if m]
            elif splat_template:
                candidates = [splat_template]

            # Splat sizing follows the projectile's own radius, so a
            # small ball → small splash, big ball → big splash.
            projectile_radius = _splat.projectile_bounding_radius(mesh)
            splat_base_scale = projectile_radius * float(splat_scale)

            # Velocity-driven directional stretch + forward bias.
            stretch_along, stretch_perp, tan_dir, grazing = \
                _splat.compute_splat_stretch(
                    velocity=impact_info.velocity,
                    normal=impact_info.normal,
                    max_stretch=splat_max_stretch,
                    min_squeeze=splat_min_squeeze,
                )
            # Shift the splat forward along the tangent so the impact
            # point sits at (or near) the trailing edge instead of the
            # centre — grazing hits get the whole splash extending in
            # the direction of travel, perpendicular hits stay centred.
            forward_offset = (grazing * stretch_along
                              * splat_base_scale
                              * float(splat_forward_bias))
            # Also bake a matching teardrop bias into the default
            # procedural shape so backward spikes shrink to nothing on
            # a grazing hit.
            shape_asymmetry = grazing * float(splat_forward_bias)

            splat_name = _splat.create_splats_from_candidates(
                base_name=f"{name}_splat",
                position=impact_info.position,
                normal=impact_info.normal,
                template_candidates=candidates,
                parent=group,
                surface_offset=splat_surface_offset,
                spawn_frame=impact_info.frame + impact_squash_frames,
                grow_frames=splat_grow_frames,
                base_scale=splat_base_scale,
                stretch_along_tangent=stretch_along,
                stretch_perp_tangent=stretch_perp,
                tangent_direction=tan_dir,
                forward_offset=forward_offset,
                shape_asymmetry=shape_asymmetry,
                rotation_jitter_degrees=splat_rotation_jitter,
                seed=impact_info.frame,
            )

    # Snap current time so the animator sees the first sample immediately.
    cmds.currentTime(start_frame, edit=True)

    return ProjectileSystem(
        name=name,
        group=group,
        controller=ctrl,
        projectile=proj_xform,
        mesh=dup,
        base_curves=(base_x, base_y, base_z),
        velocity_curves=(vel_x, vel_y, vel_z),
        impact=impact_info,
        splat=splat_name,
    )
