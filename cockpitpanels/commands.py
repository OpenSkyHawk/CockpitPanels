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


class PlateStackCommand:
    def GetResources(self):
        return {
            "Pixmap": icon("PlateStack.svg"),
            "MenuText": "Plate Stack",
            "ToolTip": "Build one padded plate Body per layer (faceplate, diffuser, backplate, ...) "
                       "from the Panel Blank, stacked front to back, with each layer's fastener cut",
        }

    def Activated(self):
        from . import plate_stack
        plate_stack.run_dialog()

    def IsActive(self):
        # Clickable with any document open: the dialog says what is missing
        # (a disabled button gives no reason).
        import FreeCAD as App
        return App.ActiveDocument is not None


class ExportLayersCommand:
    def GetResources(self):
        return {
            "Pixmap": icon("ExportLayers.svg"),
            "MenuText": "Export Layers",
            "ToolTip": "Write one DXF cut file per plate body (outline, holes and cutouts), "
                       "named after the body. Uses the selected bodies, or all of them",
        }

    def Activated(self):
        from . import export_layers
        export_layers.run_dialog()

    def IsActive(self):
        # Clickable with any document open: the dialog says what is missing
        # (a disabled button gives no reason).
        import FreeCAD as App
        return App.ActiveDocument is not None


COMMANDS = {
    "CockpitPanels_PanelBlank": PanelBlankCommand(),
    "CockpitPanels_PlateStack": PlateStackCommand(),
    "CockpitPanels_ExportLayers": ExportLayersCommand(),
}

for _name, _cmd in COMMANDS.items():
    Gui.addCommand(_name, _cmd)
