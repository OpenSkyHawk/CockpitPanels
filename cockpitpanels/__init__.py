# SPDX-License-Identifier: LGPL-2.1-or-later
"""Cockpit Panels: FreeCAD tools for home-cockpit panels."""
import os

ICONS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "Resources", "icons")


def icon(name):
    return os.path.join(ICONS, name)
