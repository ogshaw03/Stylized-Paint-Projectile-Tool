"""日本語 UI + ライブプレビュー版。

EmberGen 風のワークフローに寄せた作りに変更。左に設定パネル、右に
ライブプレビュー (軌道 + Splat 上面) を並べ、スライダーを動かした
その場でプレビューが更新される。GENERATE を押すまでシーンには何も
書かない。
"""

from __future__ import annotations

import math
from typing import Optional

from . import __version__ as _pkg_version
from . import preview as _preview
from . import splat as _splat
from . import system as _system
from . import trajectory as _traj

try:
    from maya import cmds  # type: ignore
except ImportError:  # pragma: no cover
    cmds = None  # type: ignore

WINDOW = "stylizedProjectileToolWin"

_TRAJECTORY_ANCHOR = "paint_projectile_traj_preview_anchor"
_SPLAT_ANCHOR = "paint_projectile_splat_preview_anchor"
_TRAJ_LABEL_NAME = "paint_projectile_traj_preview_label"
_SPLAT_LABEL_NAME = "paint_projectile_splat_preview_label"

_PREVIEW_W = 400
_PREVIEW_TRAJ_H = 260
_PREVIEW_SPLAT_H = 220

_GITHUB_OWNER = "ogshaw03"
_GITHUB_REPO = "Stylized-Paint-Projectile-Tool"
_GITHUB_BRANCH = "main"
_GITHUB_API = f"https://api.github.com/repos/{_GITHUB_OWNER}/{_GITHUB_REPO}"
_GITHUB_RAW_BASE = f"https://raw.githubusercontent.com/{_GITHUB_OWNER}/{_GITHUB_REPO}"


# --------------------------------------------------------------------------- #
# GitHub update flow (unchanged from previous versions)
# --------------------------------------------------------------------------- #

def _resolve_latest_sha_ui() -> str:
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


def _update_from_github(*_args) -> None:
    cmds.evalDeferred(_run_update, lowestPriority=True)


def _run_update() -> None:
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
        cmds.confirmDialog(title="更新失敗",
                           message=f"install.py の取得に失敗しました:\n{exc}",
                           button=["OK"])
        return

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
            title="更新失敗",
            message=(
                "install.py の実行中に例外が発生しました:\n"
                f"{type(exc).__name__}: {exc}\n\n"
                "詳細は Script Editor を確認してください。"
            ),
            button=["OK"],
        )
        return

    for _m in [k for k in list(sys.modules)
               if k == "paint_projectile" or k.startswith("paint_projectile.")
               or k == "paint_projectile_launch"]:
        sys.modules.pop(_m, None)

    cmds.evalDeferred(_reopen_after_update, lowestPriority=True)


def _reopen_after_update() -> None:
    import traceback
    try:
        import paint_projectile_launch
        paint_projectile_launch.show()
    except Exception as exc:
        traceback.print_exc()
        cmds.confirmDialog(
            title="再オープン失敗",
            message=(
                "更新は完了しましたがツールウィンドウの再オープンに失敗しました:\n"
                f"{type(exc).__name__}: {exc}\n\n"
                "シェルフの PaintFX ボタンから開き直してください。"
            ),
            button=["OK"],
        )


# --------------------------------------------------------------------------- #
# Selection helpers
# --------------------------------------------------------------------------- #

def _pick_single(text_field: str, node_type_filter: Optional[str] = None,
                 fields=None) -> None:
    sel = cmds.ls(sl=True, l=False) or []
    if not sel:
        cmds.warning("何も選択されていません。")
        return
    node = sel[0]
    if node_type_filter == "mesh":
        shapes = cmds.listRelatives(node, ad=True, s=True, type="mesh") or []
        if not shapes:
            cmds.warning(f"{node} にメッシュ形状が含まれていません。")
            return
    cmds.textFieldButtonGrp(text_field, e=True, text=node)
    if fields is not None:
        _schedule_live_preview(fields)


def _pick_multi(text_field: str, node_type_filter: Optional[str] = None,
                fields=None) -> None:
    sel = cmds.ls(sl=True, l=False) or []
    if not sel:
        cmds.warning("何も選択されていません。")
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
        cmds.warning("追加できるメッシュ選択がありません。")
    if fields is not None:
        _schedule_live_preview(fields)


def _clear_field(text_field: str, fields=None) -> None:
    cmds.textFieldButtonGrp(text_field, e=True, text="")
    if fields is not None:
        _schedule_live_preview(fields)


def _parse_csv(text: str) -> list:
    return [s.strip() for s in text.split(",") if s.strip()]


# --------------------------------------------------------------------------- #
# Preview scene aggregator
# --------------------------------------------------------------------------- #

def _safe_world_pos(node: str, default=(0.0, 0.0, 0.0)):
    if not node or not cmds.objExists(node):
        return default
    try:
        return tuple(cmds.xform(node, q=True, ws=True, t=True))
    except Exception:
        return default


def _compute_preview_scene(fields) -> dict:
    """Sample every UI value and derive the geometry / timing needed to
    draw the live preview. All values are computed analytically — no
    scene mutation, no ray-cast — so it's cheap enough to call on
    every slider drag."""
    mesh = cmds.textFieldButtonGrp(fields["mesh"], q=True, text=True).strip()
    start_node = cmds.textFieldButtonGrp(fields["start"], q=True, text=True).strip()
    target_node = cmds.textFieldButtonGrp(fields["target"], q=True, text=True).strip()

    start_pos = _safe_world_pos(start_node, (-5.0, 0.0, 0.0))
    target_pos = _safe_world_pos(target_node, (5.0, 0.0, 0.0))

    speed = cmds.floatSliderGrp(fields["speed"], q=True, v=True)
    gravity = cmds.floatSliderGrp(fields["gravity"], q=True, v=True)
    start_frame = int(cmds.intField(fields["startFrame"], q=True, v=True))
    end_frame = int(cmds.intField(fields["endFrame"], q=True, v=True))
    if end_frame < start_frame:
        end_frame = start_frame + 1
    num_frames = end_frame - start_frame + 1

    # Analytic ballistic solve — same as generation-time.
    v0 = _traj.solve_ballistic(start_pos, target_pos, speed, gravity)
    try:
        fps_unit = cmds.currentUnit(q=True, time=True)
        fps = _traj.frames_per_second_from_maya_unit(fps_unit)
    except Exception:
        fps = 24.0
    positions = _traj.generate_positions(start_pos, v0, gravity, num_frames, fps=fps)
    velocities = _traj.central_difference_velocity(positions, dt=1.0 / fps)

    # Approximation: preview always treats the target as the impact
    # point with an upward normal. Actual collision detection runs on
    # GENERATE against real colliders.
    impact_pos = target_pos
    # Find the frame index whose position is closest to the target.
    impact_frame_idx = min(
        range(len(positions)),
        key=lambda i: sum((positions[i][k] - target_pos[k]) ** 2
                           for k in range(3)),
    ) if positions else 0
    impact_velocity = velocities[impact_frame_idx] if velocities else (0.0, 0.0, 0.0)
    impact_normal = (0.0, 1.0, 0.0)

    # Splat sizing / deformation ­— matches system.py's derivation.
    splat_scale_mult = cmds.floatSliderGrp(fields["splatScale"], q=True, v=True)
    splat_stretch = cmds.floatSliderGrp(fields["splatStretch"], q=True, v=True)
    splat_squeeze = cmds.floatSliderGrp(fields["splatSqueeze"], q=True, v=True)
    splat_forward_bias = cmds.floatSliderGrp(fields["splatForwardBias"],
                                              q=True, v=True)

    if mesh and cmds.objExists(mesh):
        try:
            projectile_radius = _splat.projectile_bounding_radius(mesh)
        except Exception:
            projectile_radius = 1.0
    else:
        projectile_radius = 1.0
    base_scale = projectile_radius * splat_scale_mult

    stretch, squeeze, tan_dir, grazing = _splat.compute_splat_stretch(
        velocity=impact_velocity,
        normal=impact_normal,
        max_stretch=splat_stretch,
        min_squeeze=splat_squeeze,
    )
    forward_offset = grazing * stretch * base_scale * float(splat_forward_bias)
    shape_asymmetry = grazing * float(splat_forward_bias)

    splat_geom = _splat.compute_splash_geometry(
        base_radius=base_scale,
        asymmetry=shape_asymmetry,
        seed=None,   # reroll per redraw so animator can see variation
    )

    return {
        "start_pos": start_pos,
        "target_pos": target_pos,
        "trajectory": positions,
        "velocities": velocities,
        "start_frame": start_frame,
        "end_frame": end_frame,
        "fps": fps,
        "projectile_radius": projectile_radius,
        "impact_pos": impact_pos,
        "impact_frame_idx": impact_frame_idx,
        "impact_velocity": impact_velocity,
        "impact_normal": impact_normal,
        "splat_geom": splat_geom,
        "splat_base_scale": base_scale,
        "splat_stretch": stretch,
        "splat_squeeze": squeeze,
        "splat_forward_offset": forward_offset,
        "grazing": grazing,
        "tangent_dir": tan_dir,
    }


# --------------------------------------------------------------------------- #
# Trajectory preview (side view — X on horizontal, Y on vertical)
# --------------------------------------------------------------------------- #

def _render_trajectory_pixmap(scene, size_w=_PREVIEW_W, size_h=_PREVIEW_TRAJ_H):
    from PySide2 import QtCore, QtGui

    positions = scene["trajectory"]
    start_pos = scene["start_pos"]
    target_pos = scene["target_pos"]
    impact_pos = scene["impact_pos"]
    impact_vel = scene["impact_velocity"]
    grazing = scene["grazing"]

    # Bounds in world (side view uses X and Y).
    def _xy(p):
        return (p[0], p[1])
    key_pts = [_xy(p) for p in positions] + [_xy(start_pos), _xy(target_pos)]
    if not key_pts:
        key_pts = [(0.0, 0.0)]
    xs = [p[0] for p in key_pts]
    ys = [p[1] for p in key_pts]
    minx, maxx = min(xs), max(xs)
    miny, maxy = min(ys), max(ys)
    span_x = max(maxx - minx, 1e-3)
    span_y = max(maxy - miny, 1e-3)
    span = max(span_x, span_y)
    pad = span * 0.15
    span_padded = span + 2 * pad
    scale = min((size_w - 40) / span_padded, (size_h - 40) / span_padded)
    cx = (minx + maxx) * 0.5
    cy = (miny + maxy) * 0.5

    def to_canvas(pt):
        x = size_w * 0.5 + (pt[0] - cx) * scale
        # Y up in world → Y up in canvas → invert canvas y
        y = size_h * 0.5 - (pt[1] - cy) * scale
        return QtCore.QPointF(x, y)

    pixmap = QtGui.QPixmap(size_w, size_h)
    pixmap.fill(QtGui.QColor(38, 38, 42))
    painter = QtGui.QPainter(pixmap)
    painter.setRenderHint(QtGui.QPainter.Antialiasing, True)

    # Grid: 1-unit lines around origin.
    painter.setPen(QtGui.QPen(QtGui.QColor(60, 60, 66), 1, QtCore.Qt.DotLine))
    step_world = 1.0 * max(1, round(span_padded / 10.0))   # ~10 lines
    x0 = math.floor(minx / step_world) * step_world
    while x0 <= maxx + step_world:
        p0 = to_canvas((x0, miny))
        p1 = to_canvas((x0, maxy))
        painter.drawLine(p0, p1)
        x0 += step_world
    y0 = math.floor(miny / step_world) * step_world
    while y0 <= maxy + step_world:
        p0 = to_canvas((minx, y0))
        p1 = to_canvas((maxx, y0))
        painter.drawLine(p0, p1)
        y0 += step_world

    # Ground line at Y = target's Y (assumption for preview).
    painter.setPen(QtGui.QPen(QtGui.QColor(120, 90, 70), 2))
    ground_y = target_pos[1]
    painter.drawLine(to_canvas((minx - span, ground_y)),
                     to_canvas((maxx + span, ground_y)))

    # Trajectory arc.
    if len(positions) >= 2:
        painter.setPen(QtGui.QPen(QtGui.QColor(120, 180, 240), 2))
        prev = to_canvas(_xy(positions[0]))
        for p in positions[1:]:
            cur = to_canvas(_xy(p))
            painter.drawLine(prev, cur)
            prev = cur

    # Ball marker at each sampled frame (small dot).
    painter.setPen(QtCore.Qt.NoPen)
    painter.setBrush(QtGui.QColor(200, 220, 255))
    step = max(1, len(positions) // 12)
    for i in range(0, len(positions), step):
        painter.drawEllipse(to_canvas(_xy(positions[i])), 2.5, 2.5)

    # Start / Target markers.
    def _dot(painter, world_pt, color, radius=6, label=None):
        painter.setBrush(QtGui.QColor(*color))
        painter.setPen(QtCore.Qt.NoPen)
        cp = to_canvas(world_pt)
        painter.drawEllipse(cp, radius, radius)
        if label:
            painter.setPen(QtGui.QColor(*color))
            painter.drawText(cp + QtCore.QPointF(8, 4), label)
    _dot(painter, _xy(start_pos), (120, 220, 130), radius=6, label="Start")
    _dot(painter, _xy(target_pos), (240, 150, 150), radius=6, label="Target")

    # Impact marker (yellow) with velocity arrow.
    painter.setPen(QtCore.Qt.NoPen)
    painter.setBrush(QtGui.QColor(240, 220, 90))
    impact_c = to_canvas(_xy(impact_pos))
    painter.drawEllipse(impact_c, 5, 5)

    if abs(impact_vel[0]) + abs(impact_vel[1]) > 1e-6:
        painter.setPen(QtGui.QPen(QtGui.QColor(240, 220, 90), 2))
        vmag = math.sqrt(impact_vel[0] ** 2 + impact_vel[1] ** 2)
        arrow_len_world = span * 0.15
        vx = impact_vel[0] / vmag * arrow_len_world
        vy = impact_vel[1] / vmag * arrow_len_world
        tip_world = (impact_pos[0] + vx, impact_pos[1] + vy)
        tip_c = to_canvas(tip_world)
        painter.drawLine(impact_c, tip_c)
        dx = tip_c.x() - impact_c.x()
        dy = tip_c.y() - impact_c.y()
        ang = math.atan2(dy, dx)
        for h_ang in (ang + math.pi * 0.85, ang - math.pi * 0.85):
            hx = tip_c.x() + 8 * math.cos(h_ang)
            hy = tip_c.y() + 8 * math.sin(h_ang)
            painter.drawLine(tip_c, QtCore.QPointF(hx, hy))

    # Text info bar.
    painter.setPen(QtGui.QColor(200, 200, 210))
    font = painter.font()
    font.setPointSize(8)
    painter.setFont(font)
    duration = scene["end_frame"] - scene["start_frame"] + 1
    vmag = math.sqrt(sum(v ** 2 for v in impact_vel))
    grazing_pct = int(round(grazing * 100))
    painter.drawText(6, 14,
                     f"Frames: {duration}  |  着弾速度: {vmag:.1f} u/s"
                     f"  |  Grazing: {grazing_pct}%")
    painter.drawText(6, size_h - 6,
                     "側面ビュー (X-Y)  |  緑=Start  赤=Target  黄=着弾")

    painter.end()
    return pixmap


# --------------------------------------------------------------------------- #
# Splat preview (top view — from directly above the surface)
# --------------------------------------------------------------------------- #

def _render_splash_pixmap(scene, size_w=_PREVIEW_W, size_h=_PREVIEW_SPLAT_H):
    from PySide2 import QtCore, QtGui

    geom = scene["splat_geom"]
    stretch_x = scene["splat_stretch"]
    stretch_z = scene["splat_squeeze"]
    forward_offset = scene["splat_forward_offset"]

    def _tx(pt):
        return (pt[0] * stretch_x + forward_offset, pt[1] * stretch_z)

    all_polys = [[_tx(p) for p in geom["blob"]]]
    for ray in geom["rays"]:
        all_polys.append([_tx(p) for p in ray])
    for drop in geom["droplets"]:
        all_polys.append([_tx(p) for p in drop])

    all_pts = [pt for poly in all_polys for pt in poly] + [(0.0, 0.0)]
    xs = [p[0] for p in all_pts]
    zs = [p[1] for p in all_pts]
    minx, maxx = min(xs), max(xs)
    minz, maxz = min(zs), max(zs)
    span = max(maxx - minx, maxz - minz, 1e-3)
    pad = span * 0.10
    span_padded = span + 2 * pad
    scale = min((size_w - 20) / span_padded, (size_h - 20) / span_padded)
    cx = (minx + maxx) * 0.5
    cz = (minz + maxz) * 0.5

    def to_canvas(pt):
        x = size_w * 0.5 + (pt[0] - cx) * scale
        y = size_h * 0.5 - (pt[1] - cz) * scale
        return QtCore.QPointF(x, y)

    pixmap = QtGui.QPixmap(size_w, size_h)
    pixmap.fill(QtGui.QColor(38, 38, 42))
    painter = QtGui.QPainter(pixmap)
    painter.setRenderHint(QtGui.QPainter.Antialiasing, True)

    # Cross-hair for reference.
    painter.setPen(QtGui.QPen(QtGui.QColor(60, 60, 70), 1, QtCore.Qt.DotLine))
    painter.drawLine(QtCore.QPointF(0, size_h * 0.5),
                     QtCore.QPointF(size_w, size_h * 0.5))
    painter.drawLine(QtCore.QPointF(size_w * 0.5, 0),
                     QtCore.QPointF(size_w * 0.5, size_h))

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

    origin_c = to_canvas((0.0, 0.0))
    painter.setBrush(QtGui.QColor(240, 220, 90))
    painter.drawEllipse(origin_c, 4.0, 4.0)

    painter.setPen(QtGui.QPen(QtGui.QColor(240, 220, 90), 2))
    tip_c = to_canvas(((maxx - minx) * 0.35, 0.0))
    painter.drawLine(origin_c, tip_c)
    dx = tip_c.x() - origin_c.x()
    dy = tip_c.y() - origin_c.y()
    ang = math.atan2(dy, dx)
    for h_ang in (ang + math.pi * 0.85, ang - math.pi * 0.85):
        hx = tip_c.x() + 8 * math.cos(h_ang)
        hy = tip_c.y() + 8 * math.sin(h_ang)
        painter.drawLine(tip_c, QtCore.QPointF(hx, hy))

    painter.setPen(QtGui.QColor(200, 200, 210))
    font = painter.font()
    font.setPointSize(8)
    painter.setFont(font)
    painter.drawText(6, size_h - 6,
                     "上面ビュー (面上)  |  黄=着弾点+進行方向")

    painter.end()
    return pixmap


# --------------------------------------------------------------------------- #
# QLabel management
# --------------------------------------------------------------------------- #

def _find_qlabel(anchor_name: str, label_name: str):
    try:
        from PySide2 import QtWidgets
        from maya import OpenMayaUI
        from shiboken2 import wrapInstance
    except ImportError:
        return None
    ptr = OpenMayaUI.MQtUtil.findControl(anchor_name)
    if not ptr:
        return None
    anchor = wrapInstance(int(ptr), QtWidgets.QWidget)
    return anchor.findChild(QtWidgets.QLabel, label_name)


def _install_qlabel(anchor_name: str, label_name: str, w: int, h: int):
    try:
        from PySide2 import QtCore, QtWidgets
        from maya import OpenMayaUI
        from shiboken2 import wrapInstance
    except ImportError:
        return None
    ptr = OpenMayaUI.MQtUtil.findControl(anchor_name)
    if not ptr:
        return None
    anchor = wrapInstance(int(ptr), QtWidgets.QWidget)
    existing = anchor.findChild(QtWidgets.QLabel, label_name)
    if existing is not None:
        return existing
    label = QtWidgets.QLabel(anchor)
    label.setObjectName(label_name)
    label.setAlignment(QtCore.Qt.AlignCenter)
    label.setFixedSize(w, h)
    layout = anchor.layout()
    if layout is None:
        layout = QtWidgets.QVBoxLayout(anchor)
        layout.setContentsMargins(0, 0, 0, 0)
    layout.addWidget(label, alignment=QtCore.Qt.AlignCenter)
    for child in anchor.findChildren(QtWidgets.QLabel):
        if child is label:
            continue
        child.hide()
    return label


# --------------------------------------------------------------------------- #
# Live preview update
# --------------------------------------------------------------------------- #

# Coalesce rapid slider events (drag command fires 30+ Hz) into a
# single deferred rebuild — no point rebuilding 30 times per second.
_preview_pending = False


def _schedule_live_preview(fields, *_) -> None:
    """Called from every slider dc/cc. Queues one deferred rebuild;
    additional calls while a rebuild is pending are coalesced."""
    global _preview_pending
    if _preview_pending:
        return
    _preview_pending = True
    cmds.evalDeferred(lambda: _do_live_preview(fields), lowestPriority=True)


def _do_live_preview(fields) -> None:
    global _preview_pending
    _preview_pending = False
    try:
        _rebuild_3d_preview(fields)
    except Exception as exc:
        import traceback
        print(f"[paint_projectile] preview rebuild failed: {exc}")
        traceback.print_exc()


def _clear_3d_preview(*_) -> None:
    _preview.clear_preview()


def _rebuild_3d_preview(fields) -> None:
    """Read the current UI values and hand them to preview.rebuild()."""
    mesh = cmds.textFieldButtonGrp(fields["mesh"], q=True, text=True).strip()
    start_node = cmds.textFieldButtonGrp(fields["start"], q=True, text=True).strip()
    target_node = cmds.textFieldButtonGrp(fields["target"], q=True, text=True).strip()

    # Give the animator explicit feedback when the setup is incomplete
    # — the previous behavior of silently returning made it look like
    # the preview was broken.
    missing = []
    if not mesh:
        missing.append("メッシュ")
    elif not cmds.objExists(mesh):
        missing.append(f"メッシュ '{mesh}' (シーンに存在しない)")
    if not start_node:
        missing.append("発射位置")
    elif not cmds.objExists(start_node):
        missing.append(f"発射位置 '{start_node}' (シーンに存在しない)")
    if not target_node:
        missing.append("ターゲット")
    elif not cmds.objExists(target_node):
        missing.append(f"ターゲット '{target_node}' (シーンに存在しない)")
    if missing:
        cmds.inViewMessage(
            amg=(f"<hl>ライブプレビュー未構築</hl>: 未設定 → "
                 + " / ".join(missing)),
            pos="midCenter", fade=True, alpha=0.9)
        return

    colliders = _parse_csv(cmds.textFieldButtonGrp(
        fields["colliders"], q=True, text=True))
    splat_templates = _parse_csv(cmds.textFieldButtonGrp(
        fields["splatTemplates"], q=True, text=True))

    grp = _preview.rebuild(
        mesh=mesh,
        start_node=start_node,
        target_node=target_node,
        speed=cmds.floatSliderGrp(fields["speed"], q=True, v=True),
        gravity=cmds.floatSliderGrp(fields["gravity"], q=True, v=True),
        start_frame=int(cmds.intField(fields["startFrame"], q=True, v=True)),
        end_frame=int(cmds.intField(fields["endFrame"], q=True, v=True)),
        collision_meshes=colliders or None,
        splat_templates=splat_templates or None,
        splat_scale=cmds.floatSliderGrp(fields["splatScale"], q=True, v=True),
        splat_surface_offset=cmds.floatSliderGrp(
            fields["splatOffset"], q=True, v=True),
        splat_grow_frames=int(cmds.intFieldGrp(
            fields["splatGrow"], q=True, v1=True)),
        splat_max_stretch=cmds.floatSliderGrp(
            fields["splatStretch"], q=True, v=True),
        splat_min_squeeze=cmds.floatSliderGrp(
            fields["splatSqueeze"], q=True, v=True),
        splat_rotation_jitter=cmds.floatSliderGrp(
            fields["splatJitter"], q=True, v=True),
        splat_forward_bias=cmds.floatSliderGrp(
            fields["splatForwardBias"], q=True, v=True),
        splat_thickness=cmds.floatSliderGrp(
            fields["splatThickness"], q=True, v=True),
        impact_squash_frames=int(cmds.intField(
            fields["squashFrames"], q=True, v=True)),
        shape_seed=int(cmds.intField(fields["shapeSeed"], q=True, v=True)),
    )

    if grp and cmds.objExists(grp):
        # Frame the preview group in the active viewport so the user
        # doesn't have to hunt for it, and select the group so its
        # bounds are highlighted.
        try:
            cmds.select(grp, r=True)
            cmds.viewFit(grp, all=False, animate=False)
        except Exception:
            pass
        cmds.inViewMessage(
            amg=(f"<hl>プレビュー更新</hl>: "
                 f"'{_preview.PREVIEW_GROUP_NAME}' 以下に配置しました。"
                 "  ▶ Space で再生 → 実速度で確認。"),
            pos="topCenter", fade=True, alpha=0.9)


def _reroll_shape_seed(fields) -> None:
    """Increment the shape seed field by 1 to get a fresh random shape
    while keeping every other slider's value fixed."""
    current = int(cmds.intField(fields["shapeSeed"], q=True, v=True))
    cmds.intField(fields["shapeSeed"], e=True, v=current + 1)
    _schedule_live_preview(fields)


# --------------------------------------------------------------------------- #
# Generate
# --------------------------------------------------------------------------- #

def _on_generate(fields):
    mesh = cmds.textFieldButtonGrp(fields["mesh"], q=True, text=True).strip()
    start = cmds.textFieldButtonGrp(fields["start"], q=True, text=True).strip()
    target = cmds.textFieldButtonGrp(fields["target"], q=True, text=True).strip()
    cam = cmds.textFieldButtonGrp(fields["cam"], q=True, text=True).strip()

    if not mesh or not start or not target:
        cmds.warning("Mesh / Start / Target を指定してください。")
        return

    speed = cmds.floatSliderGrp(fields["speed"], q=True, v=True)
    gravity = cmds.floatSliderGrp(fields["gravity"], q=True, v=True)
    start_frame = int(cmds.intField(fields["startFrame"], q=True, v=True))
    end_frame = int(cmds.intField(fields["endFrame"], q=True, v=True))
    name = cmds.textField(fields["name"], q=True, tx=True).strip() or "paintBall"

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
    shape_seed = int(cmds.intField(fields["shapeSeed"], q=True, v=True))
    squash_frames = int(cmds.intField(fields["squashFrames"], q=True, v=True))

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
        splat_seed=shape_seed,
        impact_squash_frames=squash_frames,
    )
    # Clear the live preview so it doesn't stack under the real one.
    _preview.clear_preview()
    cmds.select(result.controller, r=True)

    if colliders:
        if result.impact is not None:
            cmds.inViewMessage(
                amg=(f"生成: <hl>{result.controller}</hl>  |  "
                     f"着弾 f={result.impact.frame} on "
                     f"<hl>{result.impact.collider}</hl>"),
                pos="topCenter", fade=True)
        else:
            cmds.inViewMessage(
                amg=(f"生成: <hl>{result.controller}</hl>  |  "
                     "着弾検出なし (基準軌道上でヒットしませんでした)"),
                pos="topCenter", fade=True)
    else:
        cmds.inViewMessage(
            amg=f"生成: <hl>{result.controller}</hl>",
            pos="topCenter", fade=True)


# --------------------------------------------------------------------------- #
# Window
# --------------------------------------------------------------------------- #

def _play_toggle(*_) -> None:
    cmds.play(state=not cmds.play(q=True, state=True), forward=True)


def show() -> str:
    """ツールウィンドウを開く / 開き直す。

    EmberGen 風レイアウト:

        ┌── 🎯 セットアップ (常時表示) ─────────────┐
        │ Mesh / Start / Target / Camera             │
        ├── タブ (弾道 / 着弾 / スプラット / 詳細) ─┤
        │  (選択タブのパラメータ)                    │
        ├── 🔄 プレビュー アクション バー (常時) ───┤
        │ [ 再構築 ] [ 削除 ] [ ▶ 再生 ]              │
        ├── ▶ GENERATE (大きなボタン) ──────────────┤
        └── バージョン + GitHub 更新 ────────────────┘
    """
    if cmds is None:
        raise RuntimeError("show() must be called inside Maya.")

    if cmds.window(WINDOW, exists=True):
        cmds.deleteUI(WINDOW)

    win = cmds.window(
        WINDOW,
        t=f"Paint Projectile FX  —  v{_pkg_version}",
        w=520, h=760, mnb=True, mxb=False, s=True,
    )

    fields = {}
    live = lambda *_: _schedule_live_preview(fields)

    # Root vertical stack — every row has a fixed purpose so the user
    # always knows where to look for a given control.
    root = cmds.formLayout()
    setup_frame = _build_setup_bar(fields)
    tabs = _build_parameter_tabs(fields, live)
    preview_bar = _build_preview_bar(fields)
    generate_bar = _build_generate_bar(fields)
    footer = _build_footer_bar()

    cmds.formLayout(
        root, e=True,
        attachForm=[
            (setup_frame, "top", 4), (setup_frame, "left", 4), (setup_frame, "right", 4),
            (preview_bar, "left", 4), (preview_bar, "right", 4),
            (generate_bar, "left", 4), (generate_bar, "right", 4),
            (footer, "left", 4), (footer, "right", 4), (footer, "bottom", 4),
            (tabs, "left", 4), (tabs, "right", 4),
        ],
        attachControl=[
            (tabs, "top", 4, setup_frame),
            (tabs, "bottom", 4, preview_bar),
            (preview_bar, "bottom", 4, generate_bar),
            (generate_bar, "bottom", 4, footer),
        ],
    )

    cmds.showWindow(win)

    # If the animator opened the tool on a scene that already has the
    # start / target locators + mesh set up (e.g. re-opening after a
    # save), pre-populate the pickers from the current selection and
    # kick off the first live preview so they see something
    # immediately.
    cmds.evalDeferred(lambda: _try_auto_populate_and_preview(fields),
                      lowestPriority=True)

    return win


def _try_auto_populate_and_preview(fields) -> None:
    """Best-effort: if a mesh + start + target exist in the scene under
    common names (or the user has 3 things selected), fill the pickers
    and build the preview. Otherwise just log a short hint."""
    try:
        sel = cmds.ls(sl=True, l=False) or []
        if len(sel) >= 3:
            # Assume selection order: mesh, start, target.
            mesh, start, target = sel[0], sel[1], sel[2]
            if cmds.listRelatives(mesh, ad=True, s=True, type="mesh"):
                cmds.textFieldButtonGrp(fields["mesh"], e=True, text=mesh)
                cmds.textFieldButtonGrp(fields["start"], e=True, text=start)
                cmds.textFieldButtonGrp(fields["target"], e=True, text=target)
        # Attempt a rebuild — _rebuild_3d_preview shows a helpful
        # in-view message if setup is incomplete, so the animator
        # always gets feedback about what to do next.
        _rebuild_3d_preview(fields)
    except Exception:
        pass


# --------------------------------------------------------------------------- #
# Layout builders — each returns the outer control it produced so show()
# can wire them up in the form. Keeping them separated makes it obvious
# from show() what each region of the window is for.
# --------------------------------------------------------------------------- #

def _build_setup_bar(fields) -> str:
    """Row 1 — Setup, always visible. Just the four pickers, compact."""
    frame = cmds.frameLayout(l="🎯 セットアップ (投射体)", cll=False,
                             mh=6, mw=6, bgc=(0.22, 0.22, 0.26))
    cmds.columnLayout(adj=True, rs=3)
    _picker = lambda key, label, filt=None: cmds.textFieldButtonGrp(
        l=label, bl="選択", ad3=2,
        bc=lambda *_: _pick_single(fields[key], filt, fields),
        cw3=(74, 260, 60))
    fields["mesh"]   = _picker("mesh",   "メッシュ",     "mesh")
    fields["start"]  = _picker("start",  "発射位置")
    fields["target"] = _picker("target", "ターゲット")
    fields["cam"]    = _picker("cam",    "カメラ")
    cmds.setParent("..")
    cmds.setParent("..")
    return frame


def _build_parameter_tabs(fields, live) -> str:
    """Row 2 — Tabs. Each tab holds one focused set of controls."""
    tab_layout = cmds.tabLayout(innerMarginWidth=6, innerMarginHeight=6)
    ballistics = _build_tab_ballistics(fields, live)
    impact = _build_tab_impact(fields, live)
    splat = _build_tab_splat(fields, live)
    misc = _build_tab_misc(fields, live)
    cmds.tabLayout(tab_layout, e=True,
                   tabLabel=[(ballistics, "🚀 弾道"),
                             (impact, "💥 衝突・着弾"),
                             (splat, "🎨 スプラット"),
                             (misc, "⚙ 詳細")],
                   selectTabIndex=1)
    cmds.setParent("..")
    return tab_layout


def _build_tab_ballistics(fields, live) -> str:
    col = cmds.columnLayout(adj=True, rs=6, cat=("both", 6))
    fields["speed"] = cmds.floatSliderGrp(
        l="初速", f=True, min=0.0, max=200.0, fmn=0.0, fmx=1000.0,
        v=20.0, pre=2, dc=live, cc=live,
        cw=[(1, 90), (2, 60)], cal=[(1, "right")],
        ann="発射時の初速 (シーン単位/秒)")
    fields["gravity"] = cmds.floatSliderGrp(
        l="重力", f=True, min=0.0, max=50.0, fmn=0.0, fmx=200.0,
        v=9.8, pre=2, dc=live, cc=live,
        cw=[(1, 90), (2, 60)], cal=[(1, "right")],
        ann="重力加速度 (-Y 方向)")
    cmds.separator(h=6, style="in")
    cmds.rowLayout(nc=4, cw4=(90, 90, 90, 90), cal=[(1, "right"), (3, "right")])
    cmds.text(l="開始フレーム:")
    fields["startFrame"] = cmds.intField(
        v=int(cmds.playbackOptions(q=True, min=True)), cc=live, w=80)
    cmds.text(l="終了フレーム:")
    fields["endFrame"] = cmds.intField(
        v=int(cmds.playbackOptions(q=True, max=True)), cc=live, w=80)
    cmds.setParent("..")
    cmds.rowLayout(nc=2, cw2=(90, 260), cal=[(1, "right")])
    cmds.text(l="名前:")
    fields["name"] = cmds.textField(tx="paintBall", w=260)
    cmds.setParent("..")
    cmds.setParent("..")
    return col


def _build_tab_impact(fields, live) -> str:
    col = cmds.columnLayout(adj=True, rs=6, cat=("both", 6))
    cmds.text(l="コライダ (軌道と交差判定するメッシュ)", al="left",
              fn="boldLabelFont")
    fields["colliders"] = cmds.textFieldButtonGrp(
        l="", bl="選択を追加",
        ad3=2, cw3=(4, 300, 100),
        bc=lambda *_: _pick_multi(fields["colliders"], "mesh", fields),
        ann="複数可、カンマ区切り")
    cmds.button(l="コライダをクリア", h=22,
                c=lambda *_: _clear_field(fields["colliders"], fields))
    cmds.separator(h=8, style="in")
    cmds.text(l="着弾アニメーション", al="left", fn="boldLabelFont")
    cmds.rowLayout(nc=2, cw2=(160, 100), cal=[(1, "right")])
    cmds.text(l="スカッシュ フレーム数:")
    fields["squashFrames"] = cmds.intField(v=1, cc=live, w=80,
                                            ann="着弾後、弾が潰れて消えるまでのフレーム数")
    cmds.setParent("..")
    cmds.setParent("..")
    return col


def _build_tab_splat(fields, live) -> str:
    col = cmds.columnLayout(adj=True, rs=5, cat=("both", 6))

    cmds.text(l="テンプレート (省略でデフォルト水しぶき形状)",
              al="left", fn="boldLabelFont")
    fields["splatTemplates"] = cmds.textFieldButtonGrp(
        l="", bl="選択を追加", ad3=2, cw3=(4, 300, 100),
        bc=lambda *_: _pick_multi(fields["splatTemplates"], "mesh", fields),
        ann="複数指定でランダム選択")
    cmds.button(l="テンプレートをクリア", h=22,
                c=lambda *_: _clear_field(fields["splatTemplates"], fields))

    cmds.separator(h=8, style="in")
    cmds.text(l="サイズ / 位置", al="left", fn="boldLabelFont")
    _slider = lambda key, lbl, mn, mx, v, pre, ann, fmn=None, fmx=None: (
        cmds.floatSliderGrp(l=lbl, f=True, min=mn, max=mx,
                            fmn=fmn if fmn is not None else mn,
                            fmx=fmx if fmx is not None else mx,
                            v=v, pre=pre, dc=live, cc=live,
                            cw=[(1, 110), (2, 60)], cal=[(1, "right")],
                            ann=ann))
    fields["splatScale"] = _slider("splatScale", "サイズ (弾比)",
                                    0.5, 10.0, 3.0, 2,
                                    "弾の bounding radius を 1 とした倍率",
                                    fmn=0.0, fmx=1000.0)
    fields["splatOffset"] = _slider("splatOffset", "面オフセット",
                                     0.0, 1.0, 0.01, 3,
                                     "Z-fight 防止のため面 Normal 方向にずらす距離",
                                     fmn=0.0, fmx=100.0)
    fields["splatThickness"] = _slider("splatThickness", "厚み",
                                        0.0, 0.5, 0.08, 3,
                                        "押し出し深さ (base radius 比)",
                                        fmn=0.0, fmx=2.0)

    cmds.separator(h=8, style="in")
    cmds.text(l="Grazing (斜め着弾) デフォーム", al="left", fn="boldLabelFont")
    fields["splatStretch"] = _slider("splatStretch", "伸び (進行方向)",
                                      1.0, 3.0, 1.8, 2,
                                      "完全 grazing 時の進行方向スケール",
                                      fmn=1.0, fmx=10.0)
    fields["splatSqueeze"] = _slider("splatSqueeze", "潰れ (垂直方向)",
                                      0.1, 1.0, 0.55, 2,
                                      "完全 grazing 時の直交方向スケール")
    fields["splatForwardBias"] = _slider("splatForwardBias", "前方バイアス",
                                          0.0, 1.0, 1.0, 2,
                                          "1.0 で着弾点がスプラット後端 (彗星型)")

    cmds.separator(h=8, style="in")
    cmds.text(l="形状バリエーション", al="left", fn="boldLabelFont")
    fields["splatJitter"] = _slider("splatJitter", "回転ジッタ (度)",
                                     0.0, 90.0, 12.0, 1,
                                     "面 Normal 周りのランダム回転度", fmx=180.0)
    cmds.rowLayout(nc=3, cw3=(110, 60, 170), cal=[(1, "right")])
    cmds.text(l="シード:")
    fields["shapeSeed"] = cmds.intField(v=0, cc=live, w=60,
                                         ann="乱数シード。同値で常に同形状。")
    cmds.button(l="🎲 別形状を試す", h=22, w=170,
                c=lambda *_: _reroll_shape_seed(fields))
    cmds.setParent("..")

    fields["splatGrow"] = cmds.intFieldGrp(
        l="拡がりフレーム", nf=1, v1=2, cc=live,
        cw=[(1, 110), (2, 60)], cal=[(1, "right")],
        ann="0 → 満スケールに拡がるまでのフレーム数")

    cmds.setParent("..")
    return col


def _build_tab_misc(fields, live) -> str:
    col = cmds.columnLayout(adj=True, rs=6, cat=("both", 6))
    cmds.text(l="使い方 (概要)", al="left", fn="boldLabelFont")
    cmds.text(
        l=("1. セットアップ タブで Mesh / Start / Target を選択\n"
           "2. 各パラメータ タブで数値調整 (プレビューがライブ更新)\n"
           "3. タイムライン スペースキーで実速度再生を確認\n"
           "4. 満足したら GENERATE ボタンでシーンにコミット\n\n"
           "生成後: *_CTRL を選択し worldOffset* / cameraOffset* /\n"
           "trajectoryTime に Key を打って演出。\n"
           "*_GRP 下の Base curves は凍結済み — 上書きされません。"),
        al="left")
    cmds.separator(h=8, style="in")
    cmds.text(l="ライブプレビュー モジュール", al="left", fn="boldLabelFont")
    cmds.text(
        l=(f"プレビュー用オブジェクトは Outliner の\n"
           f"'{_preview.PREVIEW_GROUP_NAME}' 以下にまとめて配置。\n"
           f"GENERATE 時に自動削除されます。\n"
           f"Ctrl+Z で 1 操作としてまとめて undo 可能。"),
        al="left")
    cmds.setParent("..")
    return col


def _build_preview_bar(fields) -> str:
    """Row 3 — Preview action bar. Always visible."""
    frame = cmds.frameLayout(l="🔄 ライブプレビュー", cll=False,
                             mh=4, mw=4, bgc=(0.22, 0.26, 0.28))
    cmds.rowLayout(nc=3, adj=1, cw3=(200, 130, 130))
    cmds.button(l="今すぐ再構築", h=26,
                ann="Mesh/Start/Target を切り替えた後などに手動で再構築。",
                c=lambda *_: _rebuild_3d_preview(fields))
    cmds.button(l="削除", h=26, bgc=(0.5, 0.3, 0.3),
                ann="プレビュー用オブジェクトをシーンから削除。",
                c=lambda *_: _clear_3d_preview())
    cmds.button(l="▶ 再生 / 停止", h=26, c=_play_toggle,
                ann="タイムライン (Space と同じ)。実速度で確認。")
    cmds.setParent("..")
    cmds.setParent("..")
    return frame


def _build_generate_bar(fields) -> str:
    """Row 4 — the big commit button, impossible to miss."""
    col = cmds.columnLayout(adj=True, rs=2)
    cmds.button(l="▶  GENERATE  —  シーンに最終生成",
                h=44, bgc=(0.32, 0.60, 0.38),
                c=lambda *_: _on_generate(fields))
    cmds.setParent("..")
    return col


def _build_footer_bar() -> str:
    """Row 5 — version + updater. Small, unobtrusive."""
    row = cmds.rowLayout(nc=2, adj=1, cw2=(300, 160))
    cmds.text(l=f"paint_projectile  v{_pkg_version}",
              al="left", fn="smallObliqueLabelFont")
    cmds.button(l="GitHub から更新", h=22, c=_update_from_github)
    cmds.setParent("..")
    return row
