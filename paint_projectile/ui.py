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
from . import splat as _splat
from . import system as _system

_PREVIEW_GROUP = "paint_projectile_splat_PREVIEW_GRP"

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


def _clear_splat_preview() -> None:
    if cmds.objExists(_PREVIEW_GROUP):
        cmds.delete(_PREVIEW_GROUP)


def _preview_splat(fields) -> None:
    """Spawn a static splat at the world origin using the current SPLAT
    slider values so the animator can dial in the look without running
    a full GENERATE. Re-clicking replaces the previous preview.

    Visualises the *fully-grazing* case (velocity purely tangential to
    the surface) so every slider that biases toward the direction of
    travel — Grazing Stretch, Grazing Squeeze, Forward Bias — has
    maximum visible effect. Perpendicular hits will always be milder
    than this preview."""
    _clear_splat_preview()

    splat_scale = cmds.floatSliderGrp(fields["splatScale"], q=True, v=True)
    splat_offset = cmds.floatSliderGrp(fields["splatOffset"], q=True, v=True)
    splat_stretch = cmds.floatSliderGrp(fields["splatStretch"], q=True, v=True)
    splat_squeeze = cmds.floatSliderGrp(fields["splatSqueeze"], q=True, v=True)
    splat_forward_bias = cmds.floatSliderGrp(fields["splatForwardBias"],
                                              q=True, v=True)
    splat_jitter = cmds.floatSliderGrp(fields["splatJitter"], q=True, v=True)

    templates = _parse_csv(cmds.textFieldButtonGrp(
        fields["splatTemplates"], q=True, text=True))

    # Use the picked projectile mesh (if any) to size the splat, so the
    # preview reflects the actual final size. Fall back to unit radius.
    mesh = cmds.textFieldButtonGrp(fields["mesh"], q=True, text=True).strip()
    if mesh and cmds.objExists(mesh):
        try:
            projectile_radius = _splat.projectile_bounding_radius(mesh)
        except Exception:
            projectile_radius = 1.0
    else:
        projectile_radius = 1.0
    base_scale = projectile_radius * splat_scale

    # Fully grazing synthetic hit: normal +Y, tangent +X, grazing = 1.
    forward_offset = (1.0 * splat_stretch * base_scale
                      * float(splat_forward_bias))
    shape_asymmetry = 1.0 * float(splat_forward_bias)

    grp = cmds.group(em=True, n=_PREVIEW_GROUP)

    splat_name = _splat.create_splats_from_candidates(
        base_name="paint_projectile_splat_preview",
        position=(0.0, 0.0, 0.0),
        normal=(0.0, 1.0, 0.0),
        template_candidates=templates,
        parent=grp,
        surface_offset=splat_offset,
        spawn_frame=int(cmds.currentTime(q=True)),
        grow_frames=1,
        base_scale=base_scale,
        stretch_along_tangent=splat_stretch,
        stretch_perp_tangent=splat_squeeze,
        tangent_direction=(1.0, 0.0, 0.0),
        forward_offset=forward_offset,
        shape_asymmetry=shape_asymmetry,
        rotation_jitter_degrees=splat_jitter,
        seed=None,   # random each preview so shape variation is visible
    )

    # Strip the grow-in animation so the preview stays fully visible on
    # any frame — the animator wants to inspect shape, not scrub time.
    for attr in ("scaleX", "scaleY", "scaleZ", "visibility"):
        try:
            cmds.cutKey(splat_name, at=attr, clear=True)
        except Exception:
            pass
    cmds.setAttr(f"{splat_name}.scaleX", splat_stretch * base_scale)
    cmds.setAttr(f"{splat_name}.scaleY", base_scale)
    cmds.setAttr(f"{splat_name}.scaleZ", splat_squeeze * base_scale)
    cmds.setAttr(f"{splat_name}.visibility", 1)

    cmds.select(splat_name, r=True)
    cmds.inViewMessage(
        amg=(f"Splat preview at origin ・ size ≈ "
             f"<hl>{base_scale:.2f}</hl> ・ +X = ball travel direction"),
        pos="topCenter", fade=True,
    )


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

    cmds.separator(h=4, style="none")
    cmds.rowLayout(nc=2, adj=1, cw2=(200, 130))
    cmds.button(l="Preview Splat", h=26,
                annotation=("Spawn a static splat at the world origin "
                            "using the current SPLAT settings + a "
                            "synthetic fully-grazing hit (normal +Y, "
                            "tangent +X). Re-click to reroll shape."),
                c=lambda *_: _preview_splat(fields))
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
