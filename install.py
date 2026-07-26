"""One-shot installer / updater for the Stylized Paint Projectile Tool.

Two ways to run this file from inside Maya:

1) Drag ``install.py`` from your file browser into any Maya viewport.
   Maya calls ``onMayaDroppedPythonFile`` automatically.

2) From the Script Editor (Python tab)::

       exec(open(r"C:/path/to/install.py").read())

Both do the same thing:

* **Download** the ``paint_projectile/`` package and
  ``paint_projectile_launch.py`` fresh from GitHub every time and drop
  them into your Maya user scripts folder
  (``cmds.internalVar(userScriptDir=True)``). This means you never have
  to ``git pull`` — just drag install.py.
  (Developers can opt in to the local checkout by setting
  ``PAINT_PROJECTILE_USE_LOCAL=1`` before dragging install.py.)
* Verify the installed version by reading ``__version__`` back off disk.
* Force-flush any previously loaded ``paint_projectile*`` modules from
  ``sys.modules`` so the very next import picks up the fresh code —
  no Maya restart needed.
* Close any tool window that was already open.
* Add / refresh a ``PaintFX`` shelf button on the active shelf. The
  button's command also flushes ``sys.modules`` on every click so
  dropping a newer ``install.py`` in future always takes effect on the
  next button press.
"""

from __future__ import annotations

import os
import re
import shutil
import sys


_REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
_PACKAGE = "paint_projectile"
_LAUNCHER = "paint_projectile_launch.py"
_SHELF_BUTTON_LABEL = "PaintFX"

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


# --------------------------------------------------------------------------- #
# Force-overwrite helpers (Windows-safe)
# --------------------------------------------------------------------------- #

def _force_writable(path: str) -> None:
    """Clear read-only bit so we can overwrite / remove."""
    import stat
    try:
        os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
    except Exception:
        pass


def _force_rmtree(path: str) -> None:
    """Remove a directory tree, clearing read-only on Windows and retrying
    on transient locks."""
    import stat
    import time

    if not os.path.exists(path):
        return

    def _on_error(func, p, exc_info):
        try:
            os.chmod(p, stat.S_IWRITE)
            func(p)
        except Exception:
            pass

    for attempt in range(3):
        try:
            shutil.rmtree(path, onerror=_on_error)
            if not os.path.exists(path):
                return
        except Exception as exc:
            last_exc = exc
        time.sleep(0.2)

    if os.path.exists(path):
        # Last-ditch: try to at least wipe individual files so a fresh copy
        # can overlay the folder even if the directory itself can't be
        # removed.
        for root, _dirs, files in os.walk(path):
            for name in files:
                p = os.path.join(root, name)
                try:
                    _force_writable(p)
                    os.remove(p)
                except Exception:
                    pass
        # And try one more time.
        try:
            shutil.rmtree(path, onerror=_on_error)
        except Exception:
            pass

    if os.path.exists(path):
        raise RuntimeError(
            f"Could not remove existing folder {path!r}. Close any editor "
            "or explorer window that has it open, then re-drag install.py."
        )


def _atomic_write_bytes(target: str, data: bytes) -> None:
    """Write ``data`` to ``target``, overwriting any existing file, even
    read-only ones. Uses a temp file + os.replace for an atomic swap so
    a half-written file never gets left behind."""
    os.makedirs(os.path.dirname(target), exist_ok=True)
    if os.path.exists(target):
        _force_writable(target)
        # os.replace overwrites, but only if the target is writable.
    tmp = target + ".tmp_install"
    with open(tmp, "wb") as fh:
        fh.write(data)
        fh.flush()
        try:
            os.fsync(fh.fileno())
        except Exception:
            pass
    os.replace(tmp, target)


def _atomic_copy_file(src: str, dst: str) -> None:
    with open(src, "rb") as fh:
        data = fh.read()
    _atomic_write_bytes(dst, data)


# --------------------------------------------------------------------------- #
# File acquisition
# --------------------------------------------------------------------------- #

def _copy_from_local(dest_root: str) -> None:
    src_pkg = os.path.join(_REPO_ROOT, _PACKAGE)
    dst_pkg = os.path.join(dest_root, _PACKAGE)

    _force_rmtree(dst_pkg)
    os.makedirs(dst_pkg, exist_ok=True)
    for root, _dirs, files in os.walk(src_pkg):
        for name in files:
            rel = os.path.relpath(os.path.join(root, name), src_pkg)
            _atomic_copy_file(os.path.join(root, name),
                              os.path.join(dst_pkg, rel))

    src_launcher = os.path.join(_REPO_ROOT, _LAUNCHER)
    dst_launcher = os.path.join(dest_root, _LAUNCHER)
    _atomic_copy_file(src_launcher, dst_launcher)


def _download_from_github(dest_root: str) -> None:
    import random
    import time
    from urllib.request import Request, urlopen

    dst_pkg = os.path.join(dest_root, _PACKAGE)
    _force_rmtree(dst_pkg)
    os.makedirs(dst_pkg, exist_ok=True)

    for rel_path in _REMOTE_FILES:
        # High-entropy cache-buster per FILE (not per session): time to
        # microseconds + random int. Using os.getpid() alone gave the
        # same URL every call within one Maya session, so any GitHub
        # edge / corporate proxy that cached the first response kept
        # serving it forever until Maya was restarted.
        cache_bust = f"?_={time.time():.6f}_{random.randint(0, 2**32)}"
        url = f"{_GITHUB_RAW}/{rel_path}{cache_bust}"
        target = os.path.join(dest_root, rel_path.replace("/", os.sep))
        print(f"[paint_projectile] downloading {url}")
        try:
            req = Request(url, headers={
                "Cache-Control": "no-cache, no-store, must-revalidate",
                "Pragma": "no-cache",
                "Expires": "0",
                # A distinct User-Agent avoids any UA-keyed cache too.
                "User-Agent": f"paint_projectile-installer/{cache_bust[3:]}",
            })
            data = urlopen(req, timeout=30).read()
        except Exception as exc:
            raise RuntimeError(
                f"Failed to download {url}: {exc}. "
                "Check your internet connection, or download the full "
                "repository ZIP from GitHub and run install.py from its root."
            )
        _atomic_write_bytes(target, data)
        print(f"[paint_projectile]   -> {target} ({len(data)} bytes)")


def _copy_package(dest_root: str) -> None:
    """Fetch the package files.

    Default behavior: always download the latest from GitHub so the user
    never has to remember to ``git pull`` before dragging install.py in.
    That makes install.py itself the only file the user has to keep
    around — every install grabs fresh source code straight from the
    canonical branch on GitHub.

    Developers who want to iterate on the local checkout can opt in by
    setting the environment variable ``PAINT_PROJECTILE_USE_LOCAL=1``
    before dragging install.py — in that mode the ``paint_projectile/``
    folder next to install.py is copied verbatim and no network round
    trip happens.
    """
    use_local = os.environ.get("PAINT_PROJECTILE_USE_LOCAL") == "1"
    src_pkg = os.path.join(_REPO_ROOT, _PACKAGE)
    src_launcher = os.path.join(_REPO_ROOT, _LAUNCHER)
    have_local = os.path.isdir(src_pkg) and os.path.isfile(src_launcher)

    if use_local and have_local:
        print(f"[paint_projectile] PAINT_PROJECTILE_USE_LOCAL=1 → copying "
              f"local files from {_REPO_ROOT}")
        _copy_from_local(dest_root)
    else:
        if have_local:
            print("[paint_projectile] local files exist next to install.py "
                  "but downloading from GitHub anyway (set "
                  "PAINT_PROJECTILE_USE_LOCAL=1 to prefer local)")
        else:
            print("[paint_projectile] downloading latest from GitHub")
        _download_from_github(dest_root)


def _verify_install(dest_root: str) -> None:
    """Sanity-check that every expected file exists and is non-empty."""
    missing = []
    for rel in _REMOTE_FILES:
        p = os.path.join(dest_root, rel.replace("/", os.sep))
        if not os.path.isfile(p) or os.path.getsize(p) == 0:
            missing.append(rel)
    if missing:
        raise RuntimeError(
            "Install verification failed — missing/empty files: "
            + ", ".join(missing)
        )


def _read_installed_version(dest_root: str) -> str:
    init_path = os.path.join(dest_root, _PACKAGE, "__init__.py")
    try:
        with open(init_path, "r", encoding="utf-8") as fh:
            for line in fh:
                m = re.match(r'\s*__version__\s*=\s*[\'"]([^\'"]+)[\'"]', line)
                if m:
                    return m.group(1)
    except Exception:
        pass
    return "(unknown)"


# --------------------------------------------------------------------------- #
# Live-session refresh
# --------------------------------------------------------------------------- #

def _flush_imports() -> None:
    """Drop any previously imported copies so the freshly installed files
    are picked up on the very next ``import`` — no Maya restart needed."""
    for mod_name in list(sys.modules):
        if mod_name == _PACKAGE or mod_name.startswith(_PACKAGE + "."):
            sys.modules.pop(mod_name, None)
    sys.modules.pop("paint_projectile_launch", None)


def _close_existing_window() -> None:
    """If a previous version left the tool window open, close it so the
    next launch instantiates fresh UI from the new code."""
    try:
        from maya import cmds
        for win in ("stylizedProjectileToolWin",):
            if cmds.window(win, exists=True):
                cmds.deleteUI(win)
    except Exception:
        pass


# --------------------------------------------------------------------------- #
# Shelf button
# --------------------------------------------------------------------------- #

_SHELF_BUTTON_CMD = (
    "# Auto-generated by paint_projectile install.py — do not edit.\n"
    "import sys\n"
    "for _m in [_k for _k in sys.modules\n"
    "           if _k == 'paint_projectile'\n"
    "           or _k.startswith('paint_projectile.')\n"
    "           or _k == 'paint_projectile_launch']:\n"
    "    sys.modules.pop(_m, None)\n"
    "import paint_projectile_launch\n"
    "paint_projectile_launch.show()\n"
)

# Popup-menu (right-click) command: fetches install.py from GitHub and
# runs it inline. Works around Maya's drag-and-drop cache which stops
# repeat drops of the same install.py from firing in the same session.
_SHELF_UPDATE_CMD = (
    "# Auto-generated by paint_projectile install.py — do not edit.\n"
    "import urllib.request, time\n"
    "_u = ('https://raw.githubusercontent.com/"
    "ogshaw03/Stylized-Paint-Projectile-Tool/"
    "main/install.py?_=' + str(time.time()))\n"
    "exec(compile(urllib.request.urlopen(_u, timeout=30).read(),\n"
    "             'install.py (from GitHub)', 'exec'),\n"
    "     {'__name__': 'install', '__file__': '<github>'})\n"
)


def _add_shelf_button() -> None:
    from maya import cmds, mel

    top_shelf = mel.eval("$tmp = $gShelfTopLevel")
    if not top_shelf or not cmds.tabLayout(top_shelf, exists=True):
        return
    current = cmds.tabLayout(top_shelf, q=True, selectTab=True)
    if not current:
        return

    for child in cmds.shelfLayout(current, q=True, ca=True) or []:
        try:
            if cmds.shelfButton(child, q=True, label=True) == _SHELF_BUTTON_LABEL:
                cmds.deleteUI(child)
        except Exception:
            pass

    button = cmds.shelfButton(
        parent=current,
        label=_SHELF_BUTTON_LABEL,
        annotation=(
            "Left-click: launch the tool.  "
            "Right-click: update from GitHub."
        ),
        image="pythonFamily.png",
        imageOverlayLabel="Paint",
        command=_SHELF_BUTTON_CMD,
        sourceType="python",
    )
    # Right-click popup with an Update entry so the user doesn't have
    # to re-drag install.py (Maya only fires drag-drop once per file
    # per session).
    popup = cmds.popupMenu(parent=button, button=3)
    cmds.menuItem(parent=popup, label="Launch Tool",
                  command=_SHELF_BUTTON_CMD, sourceType="python")
    cmds.menuItem(parent=popup, divider=True)
    cmds.menuItem(parent=popup, label="Update from GitHub",
                  command=_SHELF_UPDATE_CMD, sourceType="python")


# --------------------------------------------------------------------------- #
# Public entry points
# --------------------------------------------------------------------------- #

def _clean_pycache(dest_root: str) -> None:
    """Wipe __pycache__ so Python re-compiles from the fresh .py files.
    Stale .pyc files can otherwise linger and re-serve old bytecode."""
    pycache = os.path.join(dest_root, _PACKAGE, "__pycache__")
    _force_rmtree(pycache)


def install() -> str:
    """Perform install / update. Returns the destination path."""
    from maya import cmds

    user_scripts = cmds.internalVar(userScriptDir=True).rstrip("/\\")
    if not os.path.isdir(user_scripts):
        os.makedirs(user_scripts)

    prev_version = _read_installed_version(user_scripts)

    _close_existing_window()
    _copy_package(user_scripts)
    _clean_pycache(user_scripts)
    _verify_install(user_scripts)
    _flush_imports()

    if user_scripts not in sys.path:
        sys.path.insert(0, user_scripts)

    _add_shelf_button()

    new_version = _read_installed_version(user_scripts)

    print("[paint_projectile] " + "=" * 55)
    print(f"[paint_projectile] installed to: {user_scripts}")
    print(f"[paint_projectile] previous version: {prev_version}")
    print(f"[paint_projectile] current  version: {new_version}")
    print(f"[paint_projectile] shelf button '{_SHELF_BUTTON_LABEL}' refreshed")
    print("[paint_projectile] " + "=" * 55)

    try:
        cmds.confirmDialog(
            title="Stylized Paint Projectile Tool",
            message=(
                "Installed to:\n"
                f"{user_scripts}\n\n"
                f"Version: {prev_version}  →  {new_version}\n\n"
                f"The '{_SHELF_BUTTON_LABEL}' shelf button has been "
                "refreshed and now auto-reloads the tool on every click, "
                "so future re-installs take effect immediately.\n\n"
                "Click the shelf button to launch."
            ),
            button=["OK"],
        )
    except Exception:
        pass
    return user_scripts


def onMayaDroppedPythonFile(*_args) -> None:
    """Entry point Maya calls when this file is dragged into the viewport."""
    install()


# When invoked via ``exec(open(...).read())`` from the Script Editor,
# neither ``__name__ == "__main__"`` nor ``onMayaDroppedPythonFile`` fires
# on its own — so run the install here. On drag-and-drop, Maya loads this
# module (module-level runs) *and* calls ``onMayaDroppedPythonFile``, so
# install() runs twice; it is idempotent (previous install is wiped
# before copy), so a double-run is harmless.
try:
    from maya import cmds as _cmds  # noqa: F401
    install()
except ImportError:
    pass
