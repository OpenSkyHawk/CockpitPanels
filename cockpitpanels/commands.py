# SPDX-License-Identifier: LGPL-2.1-or-later
"""GUI commands. Each tool registers one command here."""
import FreeCADGui as Gui

from . import icon


class PanelBlankCommand:
    def GetResources(self):
        return {
            "Pixmap": icon("PanelBlank.svg"),
            "MenuText": "Panel Blank",
            "ToolTip": "Add or update a Dzus-grid panel blank (outline, mount points, holes) "
                       "in the active document",
        }

    def Activated(self):
        from . import panel_blank
        panel_blank.run_dialog()

    def IsActive(self):
        return True


COMMANDS = {
    "CockpitPanels_PanelBlank": PanelBlankCommand(),
}

for _name, _cmd in COMMANDS.items():
    Gui.addCommand(_name, _cmd)
