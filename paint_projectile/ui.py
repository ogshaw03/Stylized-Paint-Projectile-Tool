"""Minimal Maya UI for the prototype.

Deliberately small — enough surface to run the Section 24 workflow without
touching Python:

    * pick projectile mesh, start locator, target locator (and optional camera)
    * dial speed / gravity / frame range
    * hit GENERATE
"""

from __future__ import annotations

import math
from typing import Optional

from . import __version__ as _pkg_version
from . import splat as _splat
from . import system as _system

# QLabel widget used for the in-UI preview. Populated lazily on the
# first Preview click so importing this module outside Maya still works.
_PREVIEW_LABEL = None

_GITHUB_OWNER = "ogshaw03"
_GITHUB_REPO = "Stylized-Paint-Projectile-Tool"
_GITHUB_BRANCH = "main"
_GITHUB_API = f"https://api.github.com/repos/{_GITHUB_OWNER}/{_GITHUB_REPO}"
_GITHUB_RAW_BASE = f"https://raw.githubusercontent.com/{_GITHUB_OWNER}/{_GITHUB_REPO}"


def _resolve_latest_sha_ui() -> str:
    """Look up the current tip commit of the default branch via the
    GitHub API. Returns the SHA, or the branch name if the API is
    unreachable (that path still hits the CDN-cached copy, which is
    what we're trying to avoid — but at least the tool tries)."""
    import json
    import random
    import time
    import urllib.request

    salt = f"{time.time():.6f}_{random.randint(0, 2 ** 32)}"
    req = urllib.request.Request(
        f"{_GITHUB_API}/branches/{_GITHUB_BRANCH}?_={salt}",
        headers={
            "Accept": "application/vnd.github+json",
            "Cache-Control": "no-cache",
            "User-Agent": f"paint_projectile-updater/{salt}",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        return payload["commit"]["sha"]
    except Exception as exc:
        print(f"[paint_projectile] SHA lookup failed ({exc}); "
              f"falling back to {_GITHUB_BRANCH}")
        return _GITHUB_BRANCH

try:
    from maya import cmds  # type: ignore
except ImportError:  # pragma: no cover
    cmds = None  # type: ignore


WINDOW = "stylizedProjectileToolWin"


def _pick_single(text_field: str, node_type_filter: Optional[str] = None) -> None:
    sel = cmds.ls(sl=True, l=False) or []
    if not sel:
        cmds.warning("Nothing selected.")
        return
    node = sel[0]
    if node_type_filter == "mesh":
        # Accept a transform whose descendants include a mesh shape.
        shapes = cmds.listRelatives(node, ad=True, s=True, type="mesh") or []
        if not shapes:
            cmds.warning(f"{node} has no mesh shape underneath.")
            return
    cmds.textFieldButtonGrp(text_field, e=True, text=node)


def _pick_multi(text_field: str, node_type_filter: Optional[str] = None) -> None:
    """Append every selected mesh-carrying transform to the field as a
    comma-separated list. Duplicates are skipped."""
    sel = cmds.ls(sl=True, l=False) or []
    if not sel:
        cmds.warning("Nothing selected.")
        return
    existing = cmds.textFieldButtonGrp(text_field, q=True, text=True).strip()
    current = [s.strip() for s in existing.split(",") if s.strip()]
    added = 0
    for node in sel:
        if node_type_filter == "mesh":
            shapes = cmds.listRelatives(node, ad=True, s=True,
                                        type="mesh") or []
            if not shapes:
                continue
        if node not in current:
            current.append(node)
            added += 1
    cmds.textFieldButtonGrp(text_field, e=True, text=", ".join(current))
    if added == 0:
        cmds.warning("No new mesh-carrying selection to add.")


def _clear_field(text_field: str) -> None:
    cmds.textFieldButtonGrp(text_field, e=True, text="")


def _parse_csv(text: str) -> list:
    return [s.strip() for s in text.split(",") if s.strip()]


def _on_generate(fields):
    mesh = cmds.textFieldButtonGrp(fields["mesh"], q=True, text=True).strip()
    start = cmds.textFieldButtonGrp(fields["start"], q=True, text=True).strip()
    target = cmds.textFieldButtonGrp(fields["target"], q=True, text=True).strip()
    cam = cmds.textFieldButtonGrp(fields["cam"], q=True, text=True).strip()

    if not mesh or not start or not target:
        cmds.warning("Mesh, Start and Target are required.")
        return

    speed = cmds.floatSliderGrp(fields["speed"], q=True, v=True)
    gravity = cmds.floatSliderGrp(fields["gravity"], q=True, v=True)
    start_frame = int(cmds.intFieldGrp(fields["startFrame"], q=True, v1=True))
    end_frame = int(cmds.intFieldGrp(fields["endFrame"], q=True, v1=True))
    name = cmds.textFieldGrp(fields["name"], q=True, text=True).strip() or "paintBall"

    colliders = _parse_csv(cmds.textFieldButtonGrp(
        fields["colliders"], q=True, text=True))
    splat_templates = _parse_csv(cmds.textFieldButtonGrp(
        fields["splatTemplates"], q=True, text=True))
    splat_scale = cmds.floatSliderGrp(fields["splatScale"], q=True, v=True)
    splat_offset = cmds.floatSliderGrp(fields["splatOffset"], q=True, v=True)
    splat_grow = int(cmds.intFieldGrp(fields["splatGrow"], q=True, v1=True))
    splat_stretch = cmds.floatSliderGrp(fields["splatStretch"], q=True, v=True)
    splat_squeeze = cmds.floatSliderGrp(fields["splatSqueeze"], q=True, v=True)
    splat_forward_bias = cmds.floatSliderGrp(fields["splatForwardBias"],
                                              q=True, v=True)
    splat_jitter = cmds.floatSliderGrp(fields["splatJitter"], q=True, v=True)
    splat_thickness = cmds.floatSliderGrp(fields["splatThickness"],
                                           q=True, v=True)
    squash_frames = int(cmds.intFieldGrp(fields["squashFrames"], q=True, v1=True))

    result = _system.create_projectile_system(
        mesh=mesh,
        start=start,
        target=target,
        speed=speed,
        gravity=gravity,
        start_frame=start_frame,
        end_frame=end_frame,
        name=name,
        camera=cam or None,
        collision_meshes=colliders or None,
        splat_templates=splat_templates or None,
        splat_scale=splat_scale,
        splat_surface_offset=splat_offset,
        splat_grow_frames=splat_grow,
        splat_max_stretch=splat_stretch,
        splat_min_squeeze=splat_squeeze,
        splat_rotation_jitter=splat_jitter,
        splat_forward_bias=splat_forward_bias,
        splat_thickness=splat_thickness,
        impact_squash_frames=squash_frames,
    )
    cmds.select(result.controller, r=True)

    if colliders:
        if result.impact is not None:
            cmds.inViewMessage(
                amg=(f"Generated <hl>{result.controller}</hl>  |  "
                     f"impact f={result.impact.frame} on "
                     f"<hl>{result.impact.collider}</hl>"),
                pos="topCenter", fade=True)
        else:
            cmds.inViewMessage(
                amg=(f"Generated <hl>{result.controller}</hl>  |  "
                     "no collision detected on base trajectory"),
                pos="topCenter", fade=True)
    else:
        cmds.inViewMessage(
            amg=f"Generated <hl>{result.controller}</hl>",
            pos="topCenter", fade=True)


def _update_from_github(*_args) -> None:
    """User-facing Update handler. Immediately returns so Maya can finish
    the button callback and tear down / re-render UI cleanly, then
    performs the actual fetch-install-reopen sequence via
    ``evalDeferred``.

    Doing the work inline caused Maya to leave the tool window in a
    zombie state: the callback deleted the very window that owned the
    button, install()'s confirmDialog then ran while the parent was
    mid-teardown, and the follow-up ``show()`` occasionally silently
    no-op'd or produced a hidden window."""
    cmds.evalDeferred(_run_update, lowestPriority=True)


def _run_update() -> None:
    """Deferred: fetch install.py, run it, then queue up the reopen."""
    import sys
    import traceback
    import urllib.request

    sha = _resolve_latest_sha_ui()
    url = f"{_GITHUB_RAW_BASE}/{sha}/install.py"
    print(f"[paint_projectile] update: fetching {url}")
    try:
        req = urllib.request.Request(url, headers={
            "Cache-Control": "no-cache",
            "User-Agent": f"paint_projectile-updater/{sha[:10]}",
        })
        source = urllib.request.urlopen(req, timeout=30).read()
    except Exception as exc:
        traceback.print_exc()
        cmds.confirmDialog(
            title="Update failed",
            message=f"Could not fetch install.py:\n{exc}",
            button=["OK"],
        )
        return

    # Close ourselves cleanly BEFORE running install.py. install() also
    # tries to close us, but doing it here first means the exec'd
    # install.py never sees a window mid-teardown.
    if cmds.window(WINDOW, exists=True):
        try:
            cmds.deleteUI(WINDOW)
        except Exception:
            pass

    ns = {"__name__": "install", "__file__": "<github>"}
    try:
        exec(compile(source, "install.py (from GitHub)", "exec"), ns)
    except Exception as exc:
        traceback.print_exc()
        cmds.confirmDialog(
            title="Update failed",
            message=(
                "install.py raised an exception while running:\n"
                f"{type(exc).__name__}: {exc}\n\n"
                "See Script Editor for the full traceback."
            ),
            button=["OK"],
        )
        return

    # Drop the running package so the very next import reads the freshly
    # overwritten files. install() already does this once; a second pass
    # is cheap and defensive.
    for _m in [k for k in list(sys.modules)
               if k == "paint_projectile" or k.startswith("paint_projectile.")
               or k == "paint_projectile_launch"]:
        sys.modules.pop(_m, None)

    # Queue the reopen on the *next* idle so install()'s confirmDialog
    # has fully dismissed and Maya's UI thread is settled. Calling
    # show() inline right after the modal returned sometimes produced
    # a window that never became visible.
    cmds.evalDeferred(_reopen_after_update, lowestPriority=True)


_PREVIEW_SIZE = 260   # square px on-screen


def _render_splash_pixmap(geom: dict, stretch_x: float, stretch_z: float,
                          forward_offset: float, size: int = _PREVIEW_SIZE):
    """Render the splash geometry to a QPixmap for in-UI display.

    Bounds are auto-computed from the transformed geometry so the
    splash always fills the preview area regardless of scale.
    """
    from PySide2 import QtCore, QtGui  # Maya 2023 ships with PySide2

    def _tx(pt):
        x, z = pt
        return (x * stretch_x + forward_offset, z * stretch_z)

    all_polys = [[_tx(p) for p in geom["blob"]]]
    for ray in geom["rays"]:
        all_polys.append([_tx(p) for p in ray])
    for drop in geom["droplets"]:
        all_polys.append([_tx(p) for p in drop])

    all_pts = [pt for poly in all_polys for pt in poly]
    all_pts.append((0.0, 0.0))   # ensure impact origin is in frame
    xs = [p[0] for p in all_pts]
    zs = [p[1] for p in all_pts]
    minx, maxx = min(xs), max(xs)
    minz, maxz = min(zs), max(zs)
    span = max(maxx - minx, maxz - minz, 1e-3)
    pad = span * 0.10
    span_padded = span + 2.0 * pad
    scale = (size - 20) / span_padded
    cx = (minx + maxx) * 0.5
    cz = (minz + maxz) * 0.5

    def to_canvas(pt):
        x = size * 0.5 + (pt[0] - cx) * scale
        # invert z so +Z on the surface plane goes UP in the preview
        y = size * 0.5 - (pt[1] - cz) * scale
        return QtCore.QPointF(x, y)

    pixmap = QtGui.QPixmap(size, size)
    pixmap.fill(QtGui.QColor(38, 38, 42))
    painter = QtGui.QPainter(pixmap)
    painter.setRenderHint(QtGui.QPainter.Antialiasing, True)

    # Faint origin cross-hair for reference.
    painter.setPen(QtGui.QPen(QtGui.QColor(90, 90, 100), 1, QtCore.Qt.DotLine))
    painter.drawLine(QtCore.QPointF(0, size * 0.5),
                     QtCore.QPointF(size, size * 0.5))
    painter.drawLine(QtCore.QPointF(size * 0.5, 0),
                     QtCore.QPointF(size * 0.5, size))

    painter.setPen(QtCore.Qt.NoPen)
    painter.setBrush(QtGui.QColor(210, 60, 60))
    for poly in all_polys:
        qpath = QtGui.QPainterPath()
        first = True
        for pt in poly:
            cp = to_canvas(pt)
            if first:
                qpath.moveTo(cp)
                first = False
            else:
                qpath.lineTo(cp)
        qpath.closeSubpath()
        painter.drawPath(qpath)

    # Impact point marker (world origin, before any forward_offset).
    origin_canvas = to_canvas((0.0, 0.0))
    painter.setBrush(QtGui.QColor(230, 220, 100))
    painter.setPen(QtCore.Qt.NoPen)
    painter.drawEllipse(origin_canvas, 4.0, 4.0)

    # Tangent (+X = ball travel) arrow, projected into the preview.
    painter.setPen(QtGui.QPen(QtGui.QColor(230, 220, 100), 2))
    tip_world = ((maxx - minx) * 0.35, 0.0)
    tip_canvas = to_canvas(tip_world)
    painter.drawLine(origin_canvas, tip_canvas)
    dx = tip_canvas.x() - origin_canvas.x()
    dy = tip_canvas.y() - origin_canvas.y()
    ang = math.atan2(dy, dx)
    head_len = 8.0
    for h_ang in (ang + math.pi * 0.85, ang - math.pi * 0.85):
        hx = tip_canvas.x() + head_len * math.cos(h_ang)
        hy = tip_canvas.y() + head_len * math.sin(h_ang)
        painter.drawLine(tip_canvas, QtCore.QPointF(hx, hy))

    # Legend text
    painter.setPen(QtGui.QColor(200, 200, 210))
    font = painter.font()
    font.setPointSize(8)
    painter.setFont(font)
    painter.drawText(6, size - 6, "yellow = impact + travel direction (+X)")

    painter.end()
    return pixmap


def _find_preview_qlabel():
    """Locate the preview QLabel we anchored in show() via its
    objectName. Returns None if the label isn't reachable (e.g., UI
    was rebuilt but this module still has an old handle)."""
    try:
        from PySide2 import QtWidgets
        from maya import OpenMayaUI
        from shiboken2 import wrapInstance
    except ImportError:
        return None
    ptr = OpenMayaUI.MQtUtil.findControl("paint_projectile_preview_anchor")
    if not ptr:
        return None
    anchor = wrapInstance(int(ptr), QtWidgets.QWidget)
    return anchor.findChild(QtWidgets.QLabel, "paint_projectile_preview_label")


def _preview_splat(fields) -> None:
    """Render a preview of the current SPLAT settings into the QLabel
    embedded in the tool window. No viewport nodes are created."""
    label = _find_preview_qlabel()
    if label is None:
        cmds.warning("[paint_projectile] preview widget not found; "
                     "close and reopen the tool window.")
        return

    splat_scale = cmds.floatSliderGrp(fields["splatScale"], q=True, v=True)
    splat_stretch = cmds.floatSliderGrp(fields["splatStretch"], q=True, v=True)
    splat_squeeze = cmds.floatSliderGrp(fields["splatSqueeze"], q=True, v=True)
    splat_forward_bias = cmds.floatSliderGrp(fields["splatForwardBias"],
                                              q=True, v=True)

    mesh = cmds.textFieldButtonGrp(fields["mesh"], q=True, text=True).strip()
    if mesh and cmds.objExists(mesh):
        try:
            projectile_radius = _splat.projectile_bounding_radius(mesh)
        except Exception:
            projectile_radius = 1.0
    else:
        projectile_radius = 1.0
    base_scale = projectile_radius * splat_scale

    # Fully-grazing synthetic hit so every "grazing" slider shows max effect.
    forward_offset = (1.0 * splat_stretch * base_scale
                      * float(splat_forward_bias))
    shape_asymmetry = 1.0 * float(splat_forward_bias)

    geom = _splat.compute_splash_geometry(
        base_radius=base_scale,
        asymmetry=shape_asymmetry,
        seed=None,   # reroll shape variation on every click
    )
    pixmap = _render_splash_pixmap(
        geom,
        stretch_x=splat_stretch,
        stretch_z=splat_squeeze,
        forward_offset=forward_offset,
    )
    label.setPixmap(pixmap)


def _clear_splat_preview() -> None:
    label = _find_preview_qlabel()
    if label is not None:
        label.clear()
        label.setText("(no preview)")


def _install_preview_label_if_needed() -> None:
    """First-click helper: inject a named QLabel inside the anchor cmds
    control so subsequent ``_find_preview_qlabel`` calls can locate it.
    Idempotent — re-runs harmless."""
    try:
        from PySide2 import QtCore, QtWidgets
        from maya import OpenMayaUI
        from shiboken2 import wrapInstance
    except ImportError:
        cmds.warning("[paint_projectile] PySide2 not available — "
                     "preview unavailable in this Maya build.")
        return
    ptr = OpenMayaUI.MQtUtil.findControl("paint_projectile_preview_anchor")
    if not ptr:
        return
    anchor = wrapInstance(int(ptr), QtWidgets.QWidget)
    existing = anchor.findChild(QtWidgets.QLabel,
                                "paint_projectile_preview_label")
    if existing is not None:
        return
    # cmds.text has a QLabel already; we don't replace it — we add a
    # sibling QLabel and hide the anchor text so the pixmap owns the
    # space. Simpler: just wrap the anchor's own QLabel-like widget
    # and set its objectName so _find_preview_qlabel can grab it.
    label = QtWidgets.QLabel(anchor)
    label.setObjectName("paint_projectile_preview_label")
    label.setAlignment(QtCore.Qt.AlignCenter)
    label.setFixedSize(_PREVIEW_SIZE, _PREVIEW_SIZE)
    layout = anchor.layout()
    if layout is None:
        layout = QtWidgets.QVBoxLayout(anchor)
        layout.setContentsMargins(0, 0, 0, 0)
    layout.addWidget(label, alignment=QtCore.Qt.AlignCenter)
    # Hide the placeholder text label(s) that cmds.text put in the
    # anchor so they don't sit above the pixmap.
    for child in anchor.findChildren(QtWidgets.QLabel):
        if child is label:
            continue
        child.hide()


def _reopen_after_update() -> None:
    import traceback
    try:
        import paint_projectile_launch
        paint_projectile_launch.show()
    except Exception as exc:
        traceback.print_exc()
        cmds.confirmDialog(
            title="Reopen failed",
            message=(
                "Update finished but the tool window could not be "
                f"reopened:\n{type(exc).__name__}: {exc}\n\n"
                "Click the PaintFX shelf button to open the new "
                "version manually."
            ),
            button=["OK"],
        )


def show() -> str:
    """Open (or re-open) the tool window."""
    if cmds is None:
        raise RuntimeError("show() must be called inside Maya.")

    if cmds.window(WINDOW, exists=True):
        cmds.deleteUI(WINDOW)

    win = cmds.window(
        WINDOW,
        t=f"Stylized Projectile FX (Prototype)  —  v{_pkg_version}",
        w=420, mnb=True, mxb=False, s=True,
    )
    cmds.columnLayout(adj=True, rs=4, cat=("both", 8))

    cmds.frameLayout(l="PROJECTILE", cll=False, mh=6, mw=6)
    cmds.columnLayout(adj=True, rs=4)
    fields = {}
    fields["mesh"] = cmds.textFieldButtonGrp(
        l="Mesh", bl="Set Selected",
        bc=lambda *_: _pick_single(fields["mesh"], node_type_filter="mesh"),
        cw=[(1, 60), (2, 220), (3, 100)])
    fields["start"] = cmds.textFieldButtonGrp(
        l="Start", bl="Set Selected",
        bc=lambda *_: _pick_single(fields["start"]),
        cw=[(1, 60), (2, 220), (3, 100)])
    fields["target"] = cmds.textFieldButtonGrp(
        l="Target", bl="Set Selected",
        bc=lambda *_: _pick_single(fields["target"]),
        cw=[(1, 60), (2, 220), (3, 100)])
    fields["cam"] = cmds.textFieldButtonGrp(
        l="Camera", bl="Set Selected",
        bc=lambda *_: _pick_single(fields["cam"]),
        cw=[(1, 60), (2, 220), (3, 100)])
    cmds.setParent("..")
    cmds.setParent("..")

    cmds.frameLayout(l="MOTION", cll=False, mh=6, mw=6)
    cmds.columnLayout(adj=True, rs=4)
    fields["speed"] = cmds.floatSliderGrp(
        l="Speed", f=True, min=0.0, max=200.0, fmn=0.0, fmx=1000.0,
        v=20.0, pre=2)
    fields["gravity"] = cmds.floatSliderGrp(
        l="Gravity", f=True, min=0.0, max=50.0, fmn=0.0, fmx=200.0,
        v=9.8, pre=2)
    fields["startFrame"] = cmds.intFieldGrp(l="Start Frame", nf=1,
                                            v1=int(cmds.playbackOptions(q=True, min=True)))
    fields["endFrame"] = cmds.intFieldGrp(l="End Frame", nf=1,
                                          v1=int(cmds.playbackOptions(q=True, max=True)))
    fields["name"] = cmds.textFieldGrp(l="Name", tx="paintBall")
    cmds.setParent("..")
    cmds.setParent("..")

    cmds.frameLayout(l="COLLISION", cll=True, cl=False, mh=6, mw=6)
    cmds.columnLayout(adj=True, rs=4)
    fields["colliders"] = cmds.textFieldButtonGrp(
        l="Colliders", bl="Add Selected",
        annotation=("Meshes to ray-cast the base trajectory against. "
                    "Comma-separated. Add-Selected appends selected "
                    "mesh transforms."),
        bc=lambda *_: _pick_multi(fields["colliders"], "mesh"),
        cw=[(1, 60), (2, 220), (3, 100)])
    cmds.button(l="Clear Colliders", h=22,
                c=lambda *_: _clear_field(fields["colliders"]))
    cmds.setParent("..")
    cmds.setParent("..")

    cmds.frameLayout(l="IMPACT", cll=True, cl=False, mh=6, mw=6)
    cmds.columnLayout(adj=True, rs=4)
    fields["squashFrames"] = cmds.intFieldGrp(
        l="Squash Frames", nf=1, v1=1,
        annotation=("Frames after impact before the projectile hides. "
                    "The squash key lands squash_frames after impact, "
                    "then vanishes the frame after that."))
    cmds.setParent("..")
    cmds.setParent("..")

    cmds.frameLayout(l="SPLAT", cll=True, cl=False, mh=6, mw=6)
    cmds.columnLayout(adj=True, rs=4)
    fields["splatTemplates"] = cmds.textFieldButtonGrp(
        l="Templates", bl="Add Selected",
        annotation=("Optional splat template meshes; one is picked at "
                    "random per shot. Leave empty for a default flat "
                    "disc."),
        bc=lambda *_: _pick_multi(fields["splatTemplates"], "mesh"),
        cw=[(1, 60), (2, 220), (3, 100)])
    cmds.button(l="Clear Templates", h=22,
                c=lambda *_: _clear_field(fields["splatTemplates"]))
    fields["splatScale"] = cmds.floatSliderGrp(
        l="Size (× ball)", f=True, min=0.5, max=10.0, fmn=0.0, fmx=1000.0,
        v=3.0, pre=2,
        annotation=("Splat radius as a multiplier of the projectile's "
                    "bounding radius. 3.0 = splat is ~3× the ball."))
    fields["splatOffset"] = cmds.floatSliderGrp(
        l="Surface Offset", f=True, min=0.0, max=1.0, fmn=0.0, fmx=100.0,
        v=0.01, pre=3,
        annotation=("Distance the splat is nudged along the surface "
                    "normal so it doesn't Z-fight the collider."))
    fields["splatGrow"] = cmds.intFieldGrp(
        l="Grow Frames", nf=1, v1=2,
        annotation="Frames over which the splat scales 0 -> full.")
    fields["splatStretch"] = cmds.floatSliderGrp(
        l="Grazing Stretch", f=True, min=1.0, max=3.0, fmn=1.0, fmx=10.0,
        v=1.8, pre=2,
        annotation=("How much the splat stretches along the direction "
                    "of travel on a fully-grazing hit. 1.0 = no "
                    "directional deformation."))
    fields["splatSqueeze"] = cmds.floatSliderGrp(
        l="Grazing Squeeze", f=True, min=0.1, max=1.0, fmn=0.0, fmx=1.0,
        v=0.55, pre=2,
        annotation=("How much the splat squeezes perpendicular to the "
                    "direction of travel on a fully-grazing hit."))
    fields["splatForwardBias"] = cmds.floatSliderGrp(
        l="Forward Bias", f=True, min=0.0, max=1.0, fmn=0.0, fmx=1.0,
        v=1.0, pre=2,
        annotation=("How far to push the splat forward from the impact "
                    "point along the direction of travel. 0 = splat "
                    "centered on impact (extends both forward and "
                    "backward). 1 = impact at back edge of splat "
                    "(splash trails forward only, like a comet). "
                    "Only affects grazing hits."))
    fields["splatJitter"] = cmds.floatSliderGrp(
        l="Rot Jitter", f=True, min=0.0, max=90.0, fmn=0.0, fmx=180.0,
        v=12.0, pre=1,
        annotation=("Random rotation (deg) around the surface normal, "
                    "so repeat splats don't read as identical shapes."))
    fields["splatThickness"] = cmds.floatSliderGrp(
        l="Thickness", f=True, min=0.0, max=0.5, fmn=0.0, fmx=2.0,
        v=0.08, pre=3,
        annotation=("Extrude depth for the splat, as a fraction of the "
                    "splat's base radius. 0 = flat facet, 0.08 ≈ a thin "
                    "paint layer, higher = chunky puddle."))

    # ---- In-UI preview: anchor + QLabel populated on demand ----
    cmds.separator(h=6, style="none")
    cmds.rowLayout(nc=1, adj=1, cw=(1, _PREVIEW_SIZE))
    # `cmds.text` reserves a widget slot with a stable name; PySide2
    # then attaches / re-uses a QLabel inside it for the pixmap.
    cmds.text("paint_projectile_preview_anchor",
              l="(click Preview Splat)", h=_PREVIEW_SIZE, al="center")
    cmds.setParent("..")
    cmds.rowLayout(nc=2, adj=1, cw2=(200, 130))
    cmds.button(l="Preview Splat", h=26,
                annotation=("Draw a preview of the current SPLAT "
                            "settings inside the tool window using a "
                            "synthetic fully-grazing hit. Re-click to "
                            "reroll shape variation. Yellow dot = "
                            "impact, arrow = ball travel direction."),
                c=lambda *_: (_install_preview_label_if_needed(),
                              _preview_splat(fields)))
    cmds.button(l="Clear Preview", h=26,
                c=lambda *_: _clear_splat_preview())
    cmds.setParent("..")

    cmds.setParent("..")
    cmds.setParent("..")

    cmds.separator(h=8, style="none")
    cmds.button(l="GENERATE", h=36, c=lambda *_: _on_generate(fields))
    cmds.separator(h=6, style="none")

    cmds.text(
        l="After generate: select the *_CTRL and key worldOffset* /\n"
          "cameraOffset* / trajectoryTime to art-direct the shot.\n"
          "Base curves under the *_GRP are frozen — never overwritten.",
        al="left")

    cmds.separator(h=8, style="in")
    cmds.rowLayout(nc=3, adj=1,
                   cw3=(1, 200, 130))
    cmds.text(l="", al="left")   # left spacer stretches
    cmds.text(l=f"paint_projectile  v{_pkg_version}",
              al="right", fn="smallObliqueLabelFont",
              annotation="Installed package version.")
    cmds.button(l="Update from GitHub",
                h=22,
                annotation=("Fetch install.py from GitHub, reinstall, "
                            "and reopen this window with the new version."),
                c=_update_from_github)
    cmds.setParent("..")

    cmds.showWindow(win)
    return win
