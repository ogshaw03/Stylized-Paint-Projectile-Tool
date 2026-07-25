"""Convenience launcher.

Drop this file (and the ``paint_projectile`` package alongside it) into any
folder on Maya's ``PYTHONPATH`` / ``MAYA_SCRIPT_PATH``, then run from the
Maya Script Editor:

    import paint_projectile_launch
    paint_projectile_launch.show()

Or reload during iteration:

    import paint_projectile_launch
    paint_projectile_launch.reload_all()
    paint_projectile_launch.show()
"""

from __future__ import annotations

import importlib

import paint_projectile
from paint_projectile import ui as _ui


def show():
    return _ui.show()


def reload_all():
    """Reload every submodule (dev convenience — not needed at runtime)."""
    from paint_projectile import trajectory, system, ui
    for mod in (trajectory, system, ui, paint_projectile):
        importlib.reload(mod)
