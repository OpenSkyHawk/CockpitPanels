# SPDX-License-Identifier: LGPL-2.1-or-later
"""Registers the Cockpit Panels workbench, and puts its tools on the Sketcher and
Part Design toolbars so they can be used without switching workbench."""
import FreeCADGui as Gui


class CockpitPanelsWorkbench(Gui.Workbench):
    MenuText = "Cockpit Panels"
    ToolTip = "Tools for home-cockpit panels: Dzus-grid panel blanks"

    def __init__(self):
        from cockpitpanels import icon
        self.__class__.Icon = icon("CockpitPanels.svg")

    def Initialize(self):
        from cockpitpanels.commands import COMMANDS
        self.appendToolbar("Cockpit Panels", list(COMMANDS))
        self.appendMenu("Cockpit Panels", list(COMMANDS))

    def GetClassName(self):
        return "Gui::PythonWorkbench"


class CockpitPanelsManipulator:
    """Appends the tools to toolbars other workbenches already have. A toolbar a
    workbench doesn't have is left alone, so the button appears only there."""
    TOOLBARS = ("Sketcher", "Part Design Helper Features")

    def modifyToolBars(self):
        from cockpitpanels.commands import COMMANDS
        return [{"append": cmd, "toolBar": bar} for bar in self.TOOLBARS for cmd in COMMANDS]


Gui.addWorkbench(CockpitPanelsWorkbench())

import cockpitpanels.commands  # noqa: E402  the manipulator's commands must exist first
Gui.addWorkbenchManipulator(CockpitPanelsManipulator())
