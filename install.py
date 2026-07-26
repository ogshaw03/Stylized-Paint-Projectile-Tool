"""One-shot installer for the Stylized Paint Projectile Tool.

Two ways to run this file from inside Maya:

1) Drag ``install.py`` from your file browser into any Maya viewport.
   Maya calls ``onMayaDroppedPythonFile`` automatically and the install
   runs.

2) From the Script Editor (Python tab)::

       exec(open(r"C:/path/to/install.py").read())

Both do the same thing:

* Copy (or download) the ``paint_projectile/`` package and
  ``paint_projectile_launch.py`` into your Maya user scripts folder
  (``cmds.internalVar(userScriptDir=True)``).
* Ensure that folder is on ``sys.path`` for the current session.
* Add a ``PaintFX`` shelf button to the active shelf.

If ``install.py`` is run standalone (downloaded by itself without the rest
of the repo), the source files are fetched from GitHub over HTTPS. If run
from inside a checkout of the repository, the local files are used
instead.

After install you can launch the tool with either the shelf button or::

    import paint_projectile_launch
    paint_projectile_launch.show()
"""

from __future__ import annotations

import os
import shutil
import sys


_REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
_PACKAGE = "paint_projectile"
_LAUNCHER = "paint_projectile_launch.py"
_SHELF_BUTTON_LABEL = "PaintFX"

# GitHub source for the standalone / drag-and-drop-only case, where
# install.py was downloaded by itself.
_GITHUB_OWNER = "ogshaw03"
_GITHUB_REPO = "Stylized-Paint-Projectile-Tool"
_GITHUB_BRANCH = "main"
_GITHUB_RAW = (
    f"https://raw.githubusercontent.com/{_GITHUB_OWNER}/{_GITHUB_REPO}/"
    f"{_GITHUB_BRANCH}"
)
_REMOTE_FILES = (
    f"{_PACKAGE}/__init__.py",
    f"{_PACKAGE}/trajectory.py",
    f"{_PACKAGE}/system.py",
    f"{_PACKAGE}/ui.py",
    _LAUNCHER,
)


def _copy_from_local(dest_root: str) -> None:
    src_pkg = os.path.join(_REPO_ROOT, _PACKAGE)
    dst_pkg = os.path.join(dest_root, _PACKAGE)
    if os.path.isdir(dst_pkg):
        shutil.rmtree(dst_pkg)
    shutil.copytree(src_pkg, dst_pkg)

    src_launcher = os.path.join(_REPO_ROOT, _LAUNCHER)
    dst_launcher = os.path.join(dest_root, _LAUNCHER)
    shutil.copy2(src_launcher, dst_launcher)


def _download_from_github(dest_root: str) -> None:
    """Fetch the package files from GitHub when the local package folder
    isn't sitting next to install.py (common case: user downloaded only
    install.py)."""
    try:
        from urllib.request import urlopen  # Py3
    except ImportError:  # pragma: no cover - Maya 2023 is Py3 only
        from urllib2 import urlopen  # type: ignore

    dst_pkg = os.path.join(dest_root, _PACKAGE)
    if os.path.isdir(dst_pkg):
        shutil.rmtree(dst_pkg)
    os.makedirs(dst_pkg)

    for rel_path in _REMOTE_FILES:
        url = f"{_GITHUB_RAW}/{rel_path}"
        target = os.path.join(dest_root, rel_path.replace("/", os.sep))
        os.makedirs(os.path.dirname(target), exist_ok=True)
        print(f"[paint_projectile] downloading {url}")
        try:
            response = urlopen(url, timeout=30)
            data = response.read()
        except Exception as exc:  # network/SSL failure — surface clearly
            raise RuntimeError(
                f"Failed to download {url}: {exc}. "
                "Check your internet connection, or download the full "
                "repository ZIP from GitHub and run install.py from its root."
            )
        with open(target, "wb") as fh:
            fh.write(data)


def _copy_package(dest_root: str) -> None:
    src_pkg = os.path.join(_REPO_ROOT, _PACKAGE)
    src_launcher = os.path.join(_REPO_ROOT, _LAUNCHER)
    if os.path.isdir(src_pkg) and os.path.isfile(src_launcher):
        _copy_from_local(dest_root)
    else:
        _download_from_github(dest_root)


def _flush_imports() -> None:
    """Drop any previously imported copies so the freshly installed files
    are picked up on the very next ``import`` — no Maya restart needed."""
    for mod_name in list(sys.modules):
        if mod_name == _PACKAGE or mod_name.startswith(_PACKAGE + "."):
            sys.modules.pop(mod_name, None)
    sys.modules.pop("paint_projectile_launch", None)


def _add_shelf_button() -> None:
    from maya import cmds, mel

    top_shelf = mel.eval("$tmp = $gShelfTopLevel")
    if not top_shelf or not cmds.tabLayout(top_shelf, exists=True):
        return
    current = cmds.tabLayout(top_shelf, q=True, selectTab=True)
    if not current:
        return

    # Remove any previous button with our label so re-installs don't stack.
    for child in cmds.shelfLayout(current, q=True, ca=True) or []:
        try:
            if cmds.shelfButton(child, q=True, label=True) == _SHELF_BUTTON_LABEL:
                cmds.deleteUI(child)
        except Exception:
            pass

    cmd = (
        "import paint_projectile_launch\n"
        "paint_projectile_launch.show()\n"
    )
    cmds.shelfButton(
        parent=current,
        label=_SHELF_BUTTON_LABEL,
        annotation="Stylized Paint Projectile Tool",
        image="pythonFamily.png",
        imageOverlayLabel="Paint",
        command=cmd,
        sourceType="python",
    )


def install() -> str:
    """Perform the install. Returns the destination path."""
    from maya import cmds

    user_scripts = cmds.internalVar(userScriptDir=True).rstrip("/\\")
    if not os.path.isdir(user_scripts):
        os.makedirs(user_scripts)

    _copy_package(user_scripts)
    _flush_imports()

    if user_scripts not in sys.path:
        sys.path.insert(0, user_scripts)

    _add_shelf_button()

    print(f"[paint_projectile] installed to {user_scripts}")
    try:
        cmds.confirmDialog(
            title="Stylized Paint Projectile Tool",
            message=(
                "Installed to:\n"
                f"{user_scripts}\n\n"
                f"A '{_SHELF_BUTTON_LABEL}' shelf button was added to the "
                "active shelf. Click it to launch, or run:\n\n"
                "  import paint_projectile_launch\n"
                "  paint_projectile_launch.show()"
            ),
            button=["OK"],
        )
    except Exception:
        # confirmDialog fails in batch mode; the print above is enough.
        pass
    return user_scripts


def onMayaDroppedPythonFile(*_args) -> None:
    """Entry point Maya calls when this file is dragged into the viewport."""
    install()


# When invoked via ``exec(open(...).read())`` from the Script Editor,
# neither ``__name__ == "__main__"`` nor ``onMayaDroppedPythonFile`` gets
# a chance to fire on its own — so just run the install.
# When dragged, Maya loads this module and *then* calls
# ``onMayaDroppedPythonFile``; ``install()`` is idempotent (it wipes any
# previous copy before copying), so a double-run is harmless.
try:
    from maya import cmds as _cmds  # noqa: F401
    install()
except ImportError:
    # Being imported outside of Maya (e.g. during unit tests) — no-op.
    pass
