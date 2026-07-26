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

_INSTALL_URL = (
    "https://raw.githubusercontent.com/ogshaw03/Stylized-Paint-Projectile-Tool/"
    "main/install.py"
)

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


def _update_from_github(*_args) -> None:
    """Fetch install.py from GitHub and run it inline. This bypasses the
    drag-and-drop-caching issue where Maya won't re-run install.py in
    the same session."""
    import random
    import sys
    import time
    import traceback
    import urllib.request

    # High-entropy cache-buster + no-cache headers so no proxy or edge
    # cache can hand us back a stale install.py.
    salt = f"{time.time():.6f}_{random.randint(0, 2 ** 32)}"
    url = f"{_INSTALL_URL}?_={salt}"
    print(f"[paint_projectile] update: fetching {url}")
    try:
        req = urllib.request.Request(url, headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0",
            "User-Agent": f"paint_projectile-updater/{salt}",
        })
        source = urllib.request.urlopen(req, timeout=30).read()
    except Exception as exc:
        cmds.confirmDialog(
            title="Update failed",
            message=f"Could not fetch install.py:\n{exc}",
            button=["OK"],
        )
        return

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

    # Force-drop the running package so the very next import reads the
    # freshly overwritten files from disk. install() already does this
    # once, but a defensive second pass is cheap and makes the reopen
    # deterministic if the module was somehow re-imported in between.
    if cmds.window(WINDOW, exists=True):
        cmds.deleteUI(WINDOW)
    for _m in [k for k in list(sys.modules)
               if k == "paint_projectile" or k.startswith("paint_projectile.")
               or k == "paint_projectile_launch"]:
        sys.modules.pop(_m, None)

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
