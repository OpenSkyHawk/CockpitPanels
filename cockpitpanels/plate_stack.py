# SPDX-License-Identifier: LGPL-2.1-or-later
"""Plate Stack: one PartDesign Body per layer, padded from the Panel Blank.

Layers are listed front to back. The front face of the first layer sits on the
blank's sketch plane (z = 0) and faces +z, so the Top view shows the panel as
seen in the cockpit; each further layer sits directly behind the previous one.

Every layer:
  <Layer>_Outline  SubShapeBinder of BlankOutline (the faceplate: StackFaceOutline),
                   lifted to the layer's back face
  <Layer>_Pad      padded by the layer thickness
  <Layer>_Cut      SubShapeBinder of the fastener cut for this layer's style
  <Layer>_Pocket   cut through all, both directions

Fastener styles (per layer):
  Clearance  the blank's clearance holes (BlankHoles)
  Recess     a larger circle at each mount point (StackRecesses), so the
             screw head sits down in the layer
  Slot       the same circle opened through the nearest side edge (StackSlots)

The faceplate (the first layer) can be inset from the blank's edges, left /
right / top / bottom, positive = smaller: StackFaceOutline is the blank outline
with those insets, same corner radius. The layers behind it stay full size.

Thicknesses, the recess diameter, the insets and the layers' depths live in the PlateStack
spreadsheet: edit a cell and recompute. Running Plate Stack again updates the
same objects in place.
"""
import re

import FreeCAD as App
import Part
import Sketcher

from . import panel_blank as pb

V = App.Vector
SHEET = "PlateStack"
RECESSES, SLOTS, FACE_OUTLINE = "StackRecesses", "StackSlots", "StackFaceOutline"
INSETS = ("inset_l", "inset_r", "inset_t", "inset_b")
STYLES = ("Recess", "Slot", "Clearance")
STYLE_SKETCH = {"Recess": RECESSES, "Slot": SLOTS, "Clearance": pb.HOLES}
INCH = 25.4
DEFAULT_RECESS_MM = 9.5
DEFAULT_LAYERS = (            # name, thickness expression, style
    ("FacePlate", "=1/16 * 25.4 mm", "Recess"),
    ("Diffuser", "=1/8 * 25.4 mm", "Clearance"),
    ("BackPlate", "=1/8 * 25.4 mm", "Clearance"),
)
SLOT_PAST_EDGE_MM = 1.0       # slots run this far past the side edge so the cut opens cleanly


def layer_name(text):
    """A layer name usable as an object name and spreadsheet alias."""
    name = re.sub(r"[^A-Za-z0-9_]+", "_", text.strip()).strip("_")
    if not name:
        raise ValueError("a layer needs a name")
    return name if not name[0].isdigit() else "L" + name


def parse_thickness(text):
    """Thickness as a spreadsheet expression. Accepts '3', '3 mm', '0.125 in',
    '1/8"', '1/16 in'. Inch fractions stay exact."""
    t = text.strip().replace("”", '"').replace("″", '"')
    m = re.fullmatch(r"(\d+)\s*/\s*(\d+)\s*(\"|in|inch)?", t)
    if m:
        return f"={m[1]}/{m[2]} * 25.4 mm"
    m = re.fullmatch(r"(\d+(?:\.\d+)?)\s*(\"|in|inch|mm)?", t)
    if m:
        value, unit = m[1], m[2] or "mm"
        if float(value) <= 0:
            raise ValueError(f"thickness must be positive: {text!r}")
        return f"={value} * 25.4 mm" if unit in ('"', "in", "inch") else f"{value} mm"
    raise ValueError(f"can't read thickness {text!r} (try 3, 3 mm, 1/8\" or 0.125 in)")


def _n_extra(doc):
    return len(pb._read_existing(doc)[2])


def _sheet(doc, layers, recess_dia, insets):
    ss = doc.getObject(SHEET) or doc.addObject("Spreadsheet::Sheet", SHEET)
    ss.clearAll()
    ss.set("A1", "recess_dia")
    ss.set("B1", f"{recess_dia} mm")
    ss.setAlias("B1", "recess_dia")
    for r, (alias, value) in enumerate(zip(INSETS, insets), start=1):  # faceplate insets, col F
        ss.set(f"E{r}", "faceplate " + alias)
        ss.set(f"F{r}", f"{value} mm")
        ss.setAlias(f"F{r}", alias)
    for col, head in zip("ABCD", ("layer", "thickness", "back face z", "style")):
        ss.set(f"{col}2", head)
    for i, (name, thickness, style) in enumerate(layers):
        r = i + 3
        ss.set(f"A{r}", "'" + name)
        ss.set(f"B{r}", thickness)
        ss.set(f"C{r}", f"=-B{r}" if i == 0 else f"=C{r - 1} - B{r}")
        ss.set(f"D{r}", "'" + style)
        ss.setAlias(f"B{r}", f"t_{name}")
        ss.setAlias(f"C{r}", f"z_{name}")
        ss.setAlias(f"D{r}", f"style_{name}")
    doc.recompute()
    return ss


def _recesses(doc, n_extra):
    sk = pb._sketch(doc, RECESSES)
    for side, x, y in pb._mount_exprs(n_extra):
        g = sk.addGeometry(Part.Circle(V(side * 60, 0, 0), V(0, 0, 1), DEFAULT_RECESS_MM / 2))
        pb._place(sk, g, 3, side, x, y)
        d = sk.addConstraint(Sketcher.Constraint("Diameter", g, DEFAULT_RECESS_MM))
        sk.setExpression(f"Constraints[{d}]", f"{SHEET}.recess_dia")
    return sk


def _slots(doc, n_extra):
    """A U per mount point: a half circle on the panel side, open through the side edge."""
    sk = pb._sketch(doc, SLOTS)
    r = DEFAULT_RECESS_MM / 2
    reach = f"{pb.SHEET}.pitch / 2 + {SLOT_PAST_EDGE_MM} mm"
    for side, x, y in pb._mount_exprs(n_extra):
        cx = side * 60.0
        if side > 0:   # right column: arc on the left, CCW from top (start) to bottom (end)
            arc = Part.ArcOfCircle(Part.Circle(V(cx, 0, 0), V(0, 0, 1), r), 0.5 * 3.14159265, 1.5 * 3.14159265)
            top, bottom = 1, 2
        else:          # left column: arc on the right, CCW from bottom (start) to top (end)
            arc = Part.ArcOfCircle(Part.Circle(V(cx, 0, 0), V(0, 0, 1), r), -0.5 * 3.14159265, 0.5 * 3.14159265)
            top, bottom = 2, 1
        out = cx + side * (r + 2)
        a = sk.addGeometry(arc)
        l1 = sk.addGeometry(Part.LineSegment(V(cx, r, 0), V(out, r, 0)))      # top edge, outwards
        l2 = sk.addGeometry(Part.LineSegment(V(out, r, 0), V(out, -r, 0)))    # past the side edge
        l3 = sk.addGeometry(Part.LineSegment(V(out, -r, 0), V(cx, -r, 0)))    # bottom edge, back in
        con = Sketcher.Constraint
        sk.addConstraint(con("Tangent", a, top, l1, 1))
        sk.addConstraint(con("Coincident", l1, 2, l2, 1))
        sk.addConstraint(con("Coincident", l2, 2, l3, 1))
        sk.addConstraint(con("Tangent", l3, 2, a, bottom))
        sk.addConstraint(con("Horizontal", l1))
        sk.addConstraint(con("Horizontal", l3))
        sk.addConstraint(con("Vertical", l2))
        pb._place(sk, a, 3, side, x, y)
        rad = sk.addConstraint(con("Radius", a, r))
        sk.setExpression(f"Constraints[{rad}]", f"{SHEET}.recess_dia / 2")
        dx = sk.addConstraint(con("DistanceX", a, 3, l2, 1, side * (r + 2)))
        sk.setExpression(f"Constraints[{dx}]", f"{side} * ({reach})")
    return sk


def _face_outline(doc, insets, blank=None):
    """The blank outline with the faceplate's insets, same corner radius.
    blank: (units, width_mm, corner_r) when the blank's sheet hasn't been recomputed yet."""
    sk = pb._sketch(doc, FACE_OUTLINE)
    if blank is None:
        units, width_mm, _, _, _, corner_r = pb._read_existing(doc)
    else:
        units, width_mm, corner_r = blank
    il, ir, it, ib = insets
    w, h = width_mm / 2, units * pb.PITCH_MM / 2
    B, S = pb.SHEET, SHEET
    exprs = (f"-{B}.width / 2 + {S}.inset_l", f"{B}.width / 2 - {S}.inset_r",
             f"{B}.units * {B}.pitch / 2 - {S}.inset_t", f"-{B}.units * {B}.pitch / 2 + {S}.inset_b")
    return pb.rect_outline(sk, (-w + il, w - ir, h - it, -h + ib), exprs, corner_r, f"{B}.corner_r")


def _feature(body, type_id, name):
    obj = body.Document.getObject(name)
    if obj is None:
        obj = body.newObject(type_id, name)
    return obj


def _layer(doc, name, style, outline_sketch):
    body = doc.getObject(name)
    if body is None:
        body = doc.addObject("PartDesign::Body", name)
    outline = _feature(body, "PartDesign::SubShapeBinder", f"{name}_Outline")
    outline.Support = [(doc.getObject(outline_sketch), [""])]
    outline.setExpression("Placement.Base.z", f"{SHEET}.z_{name}")
    doc.recompute()
    pad = _feature(body, "PartDesign::Pad", f"{name}_Pad")
    pad.Profile = outline
    pad.setExpression("Length", f"{SHEET}.t_{name}")
    doc.recompute()  # one feature at a time: a single recompute over the chain breaks the cut
    cut_sketch = doc.getObject(STYLE_SKETCH[style])
    cut = doc.getObject(f"{name}_Cut")
    pocket = doc.getObject(f"{name}_Pocket")
    if not cut_sketch.Shape.Edges:   # e.g. Clearance with fastener "None": nothing to cut
        if pocket:
            body.removeObject(pocket)
            doc.removeObject(pocket.Name)
        if cut:
            body.removeObject(cut)
            doc.removeObject(cut.Name)
        doc.recompute()
        return body
    cut = cut or body.newObject("PartDesign::SubShapeBinder", f"{name}_Cut")
    cut.Support = [(cut_sketch, [""])]
    doc.recompute()
    pocket = pocket or body.newObject("PartDesign::Pocket", f"{name}_Pocket")
    pocket.Profile = cut
    pocket.Type = "ThroughAll"
    pocket.SideType = "Symmetric"
    doc.recompute()
    return body


def make_stack(doc, layers=None, recess_dia=DEFAULT_RECESS_MM, insets=(0, 0, 0, 0)):
    """Create or update the plate stack. layers: (name, thickness expression, style),
    front to back. insets: (left, right, top, bottom) mm for the faceplate (the first
    layer) only, positive = smaller. Bodies of layers no longer listed are left untouched."""
    if doc.getObject(pb.SHEET) is None:
        raise ValueError("run Panel Blank first: the stack is built from the blank")
    layers = list(layers or DEFAULT_LAYERS)
    if not layers:
        raise ValueError("a stack needs at least one layer")
    names = [layer_name(n) for n, _, _ in layers]
    if len(set(names)) != len(names):
        raise ValueError("layer names must be different")
    for _, _, style in layers:
        if style not in STYLES:
            raise ValueError(f"unknown fastener style {style!r}")
    if recess_dia <= 0:
        raise ValueError("recess diameter must be positive")
    insets = tuple(float(v) for v in insets)
    units, width_mm, _, _, hole_dia, corner_r = pb._read_existing(doc)
    try:
        pb.check_outline(units, width_mm, corner_r, hole_dia, insets)
    except ValueError as e:
        raise ValueError(f"faceplate: {e}") from None
    layers = [(n, t, s) for n, (_, t, s) in zip(names, layers)]
    _sheet(doc, layers, recess_dia, insets)
    refresh_cut_sketches(doc)
    bodies = [_layer(doc, name, style, FACE_OUTLINE if i == 0 else pb.OUTLINE)
              for i, (name, _, style) in enumerate(layers)]
    grp = doc.getObject("PlateStackGroup") or doc.addObject("App::DocumentObjectGroup", "PlateStackGroup")
    grp.Label = "Plate Stack"
    for o in (doc.getObject(SHEET), doc.getObject(FACE_OUTLINE), doc.getObject(RECESSES), doc.getObject(SLOTS)):
        if o not in grp.Group:
            grp.addObject(o)
    doc.recompute()
    if App.GuiUp:
        _style_view(doc, bodies)
    return bodies


def _style_view(doc, bodies):
    """Show only the plates: hide the helper sketches and binders (all drawn at z = 0,
    on top of the faceplate) and give each layer its own colour."""
    helpers = [pb.OUTLINE, pb.POINTS, pb.HOLES, FACE_OUTLINE, RECESSES, SLOTS]
    for b in bodies:
        helpers += [f"{b.Name}_Outline", f"{b.Name}_Cut"]
    for name in helpers:
        obj = doc.getObject(name)
        if obj is not None and obj.ViewObject is not None:
            obj.ViewObject.Visibility = False
    for i, b in enumerate(bodies):
        vo = b.ViewObject
        if vo is None:
            continue
        vo.Visibility = True
        if i == 0:                      # faceplate: dark, like the real panels
            vo.ShapeColor, vo.Transparency = (0.20, 0.25, 0.32), 0
        elif i == len(bodies) - 1:      # back layer
            vo.ShapeColor, vo.Transparency = (0.55, 0.60, 0.66), 0
        else:                           # middle layers (diffuser): see-through
            vo.ShapeColor, vo.Transparency = (0.95, 0.95, 0.90), 50


def update(doc):
    """Re-run the stack with its current settings (after the blank changed)."""
    layers, recess_dia, insets = read_existing(doc)
    return make_stack(doc, layers, recess_dia, insets)


def refresh_cut_sketches(doc):
    """Rebuild the faceplate outline, recess and slot sketches for the blank's
    current shape and mount points (after Panel Blank changed rows or corners)."""
    _face_outline(doc, read_insets(doc))
    n = _n_extra(doc)
    _recesses(doc, n)
    _slots(doc, n)
    doc.recompute()


def read_insets(doc):
    """The faceplate's (left, right, top, bottom) insets in mm; 0 when not set."""
    ss = doc.getObject(SHEET)
    out = []
    for alias in INSETS:
        try:
            v = ss.get(alias)
        except Exception:  # no stack yet, or one made before insets existed
            v = 0.0
        out.append(float(getattr(v, "Value", v)))
    return tuple(out)


def read_existing(doc):
    """(layers, recess_dia, insets) from the document's PlateStack sheet, or the defaults."""
    ss = doc.getObject(SHEET)
    if ss is None:
        return [(n, t, s) for n, t, s in DEFAULT_LAYERS], DEFAULT_RECESS_MM, (0.0, 0.0, 0.0, 0.0)
    layers, r = [], 3
    while True:
        try:
            name = ss.get(f"A{r}")
        except Exception:
            break
        thickness = ss.getContents(f"B{r}")
        layers.append((name, thickness, ss.get(f"D{r}")))
        r += 1
    rd = ss.get("recess_dia")
    return layers, float(getattr(rd, "Value", rd)), read_insets(doc)


def thickness_text(expr):
    """Spreadsheet thickness back to what a person would type."""
    m = re.fullmatch(r"=\s*(\d+)\s*/\s*(\d+)\s*\*\s*25\.4\s*mm", expr)
    if m:
        return f'{m[1]}/{m[2]}"'
    m = re.fullmatch(r"=\s*(\d+(?:\.\d+)?)\s*\*\s*25\.4\s*mm", expr)
    if m:
        return f"{m[1]} in"
    return expr.lstrip("=")


def run_dialog():
    import FreeCADGui as Gui
    from PySide import QtWidgets

    mw = Gui.getMainWindow()
    doc = App.ActiveDocument
    if doc is None or doc.getObject(pb.SHEET) is None:
        QtWidgets.QMessageBox.information(mw, "Plate Stack", f"\"{doc.Label if doc else 'This document'}\" has no Panel Blank.\n\n"
                                          "Run Panel Blank first, or switch to the document that has one: "
                                          "the stack is built from the blank.")
        return
    layers0, recess0, insets0 = read_existing(doc)

    dlg = QtWidgets.QDialog(mw)
    dlg.setWindowTitle("Plate Stack" + (" — update" if doc.getObject(SHEET) else ""))
    box = QtWidgets.QVBoxLayout(dlg)
    box.addWidget(QtWidgets.QLabel("Layers, front to back. Thickness: 3, 3 mm, 1/8\" or 0.125 in."))
    table = QtWidgets.QTableWidget(0, 3)
    table.setHorizontalHeaderLabels(["Layer", "Thickness", "Fastener cut"])
    table.horizontalHeader().setStretchLastSection(True)
    box.addWidget(table)

    def add_row(name="Layer", thickness="1/8\"", style="Clearance"):
        r = table.rowCount()
        table.insertRow(r)
        table.setItem(r, 0, QtWidgets.QTableWidgetItem(name))
        table.setItem(r, 1, QtWidgets.QTableWidgetItem(thickness))
        combo = QtWidgets.QComboBox()
        combo.addItems(list(STYLES))
        combo.setCurrentText(style)
        table.setCellWidget(r, 2, combo)

    for name, thickness, style in layers0:
        add_row(name, thickness_text(thickness), style)
    buttons_row = QtWidgets.QHBoxLayout()
    add_btn = QtWidgets.QPushButton("Add layer")
    del_btn = QtWidgets.QPushButton("Remove selected")
    add_btn.clicked.connect(lambda: add_row())
    del_btn.clicked.connect(lambda: [table.removeRow(i.row()) for i in sorted(table.selectionModel().selectedRows(), key=lambda i: -i.row())]
                            or (table.currentRow() >= 0 and not table.selectionModel().selectedRows() and table.removeRow(table.currentRow())))
    buttons_row.addWidget(add_btn)
    buttons_row.addWidget(del_btn)
    buttons_row.addStretch()
    box.addLayout(buttons_row)
    form = QtWidgets.QFormLayout()
    recess = QtWidgets.QDoubleSpinBox()
    recess.setRange(0.1, 50)
    recess.setDecimals(2)
    recess.setSuffix(" mm")
    recess.setValue(recess0)
    form.addRow("Recess / slot Ø", recess)
    note = QtWidgets.QLabel()
    form.addRow("", note)
    box.addLayout(form)

    def warn(*_):
        value = recess.value()
        side = max(inset_boxes[0].value(), inset_boxes[1].value())
        left = (pb.PITCH_MM - value) / 2 - side
        if value >= pb.PITCH_MM - 1e-9:
            note.setText(f"Ø{value:g} ≥ 9.525 pitch: a recess breaks through the side edge\n"
                         f"and merges with recesses one row apart")
        elif left <= 0:
            note.setText("on the inset faceplate a recess opens through the side edge")
        else:
            note.setText(f"{left:.2f} mm left between a recess and the faceplate's side edge")

    inset_row = QtWidgets.QHBoxLayout()
    inset_boxes = []
    for label, value in zip(("L", "R", "T", "B"), insets0):
        spin = QtWidgets.QDoubleSpinBox()
        spin.setRange(0, 20)
        spin.setDecimals(2)
        spin.setSuffix(" mm")
        spin.setValue(value)
        inset_row.addWidget(QtWidgets.QLabel(label))
        inset_row.addWidget(spin)
        inset_boxes.append(spin)
    form.addRow("Faceplate inset", inset_row)
    form.addRow("", QtWidgets.QLabel("Shrinks the first layer only, from each edge; the layers behind stay full size"))
    for w in [recess] + inset_boxes:
        w.valueChanged.connect(warn)
    warn()
    ok = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
    ok.accepted.connect(dlg.accept)
    ok.rejected.connect(dlg.reject)
    box.addWidget(ok)
    dlg.resize(460, 360)
    if not dlg.exec():
        return
    try:
        layers = [(table.item(r, 0).text(), parse_thickness(table.item(r, 1).text()),
                   table.cellWidget(r, 2).currentText()) for r in range(table.rowCount())]
        make_stack(doc, layers, recess.value(), tuple(b.value() for b in inset_boxes))
    except ValueError as e:
        QtWidgets.QMessageBox.warning(mw, "Plate Stack", str(e))
        return
    Gui.activeDocument().activeView().viewIsometric()
    Gui.SendMsgToActiveView("ViewFit")
