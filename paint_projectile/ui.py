"""Minimal Maya UI for the prototype.

Deliberately small — enough surface to run the Section 24 workflow without
touching Python:

    * pick projectile mesh, start locator, target locator (and optional camera)
    * dial speed / gravity / frame range
    * hit GENERATE
"""

from __future__ import annotations

from typing import Optional

from . import __version__ as _pkg_version
from . import system as _system

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
    )
    cmds.select(result.controller, r=True)
    cmds.inViewMessage(
        amg=f"Generated <hl>{result.controller}</hl>",
        pos="topCenter",
        fade=True,
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

    cmds.separator(h=8, style="none")
    cmds.button(l="GENERATE", h=36, c=lambda *_: _on_generate(fields))
    cmds.separator(h=6, style="none")

    cmds.text(
        l="After generate: select the *_CTRL and key worldOffset* /\n"
          "cameraOffset* / trajectoryTime to art-direct the shot.\n"
          "Base curves under the *_GRP are frozen — never overwritten.",
        al="left")

    cmds.separator(h=8, style="in")
    cmds.rowLayout(nc=2, adj=1)
    cmds.text(l="", al="left")   # left spacer stretches
    cmds.text(l=f"paint_projectile  v{_pkg_version}",
              al="right", fn="smallObliqueLabelFont",
              annotation="Installed package version. Re-drag install.py to update.")
    cmds.setParent("..")

    cmds.showWindow(win)
    return win
