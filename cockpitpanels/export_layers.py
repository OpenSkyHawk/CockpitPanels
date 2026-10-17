# SPDX-License-Identifier: LGPL-2.1-or-later
"""Export Layers: one DXF cut file per plate.

Each plate Body (faceplate, diffuser, backing, ...) is written to its own DXF,
named after the Body's label. The file holds the plate's bottom face, flattened
to z = 0: its outline plus every hole and cutout that goes through it, so it is
ready for the laser cutter. The document is not modified.
"""
import os
import re

import FreeCAD as App
import Part


def find_plates(doc):
    """PartDesign Bodies in the document that have a solid to cut."""
    return [o for o in doc.Objects
            if o.TypeId == "PartDesign::Body" and o.Shape.Solids]


def plate_profile(body):
    """The plate's bottom face(s) as edges, flattened to z = 0."""
    shape = body.Shape
    zmin = shape.BoundBox.ZMin
    faces = [f for f in shape.Faces
             if f.Surface.TypeId == "Part::GeomPlane"
             and abs(abs(f.normalAt(0, 0).z) - 1) < 1e-6
             and abs(f.BoundBox.ZMin - zmin) < 1e-6]
    if not faces:
        raise ValueError(f"{body.Label}: no flat face at the bottom (z = {zmin:g})")
    edges = Part.Compound([e for f in faces for e in f.Edges])
    edges.translate(App.Vector(0, 0, -zmin))
    return edges


def _safe_name(label):
    """A file and DXF-layer name from a label: letters, digits, '-' and '_' only."""
    return re.sub(r"[^A-Za-z0-9_-]+", "_", label).strip("_") or "Plate"


def export_layers(bodies, folder):
    """Write one DXF per body into folder; returns the paths written.

    The export runs in a scratch document so each DXF layer is named exactly
    after its plate and nothing is added to the user's document.
    """
    import importDXF

    os.makedirs(folder, exist_ok=True)
    scratch = App.newDocument("CockpitPanelsExport", hidden=True)
    written = []
    try:
        for body in bodies:
            name = _safe_name(body.Label)
            obj = scratch.addObject("Part::Feature", name)
            obj.Shape = plate_profile(body)
            scratch.recompute()
            path = os.path.join(folder, name + ".dxf")
            importDXF.export([obj], path)
            written.append(path)
    finally:
        App.closeDocument(scratch.Name)
    return written


def run_dialog():
    import FreeCADGui as Gui
    from PySide import QtWidgets

    mw = Gui.getMainWindow()
    doc = App.ActiveDocument
    if doc is None:
        QtWidgets.QMessageBox.information(mw, "Export Layers", "Open a document with plate bodies first.")
        return
    selected = [o for o in Gui.Selection.getSelection(doc.Name) if o.TypeId == "PartDesign::Body"]
    bodies = selected or find_plates(doc)
    if not bodies:
        QtWidgets.QMessageBox.information(mw, "Export Layers", f"\"{doc.Label}\" has no plates to export.\n\n"
                                          "Run Plate Stack first, or switch to the document with your plates.")
        return
    start = os.path.dirname(doc.FileName) if doc.FileName else os.path.expanduser("~")
    folder = QtWidgets.QFileDialog.getExistingDirectory(
        mw, f"Export {len(bodies)} layer(s): {', '.join(b.Label for b in bodies)}", start)
    if not folder:
        return
    try:
        written = export_layers(bodies, folder)
    except ValueError as e:
        QtWidgets.QMessageBox.warning(mw, "Export Layers", str(e))
        return
    QtWidgets.QMessageBox.information(
        mw, "Export Layers", "Wrote:\n" + "\n".join(os.path.basename(p) for p in written))
