# SPDX-License-Identifier: LGPL-2.1-or-later
"""Panel Blank: the base blank for a Dzus-rail console panel.

Adds a panel blank to the active document, inside a "Panel Blank" group:
  PanelBlank        spreadsheet: units, pitch, width, fastener, hole_dia, corner_r, extra rows
  BlankOutline      sketch: panel rectangle (corners rounded by corner_r), centred
                    on the origin, XY (top) plane
  BlankMountPoints  sketch: one point per mount position on the Dzus grid
  BlankHoles        sketch: one clearance circle per mount (empty for "None")
All dimensions are spreadsheet expressions, so editing a cell + recompute moves
everything. Running again on a doc that already has a blank updates the same
sketches in place, so SubShapeBinders pointing at them keep working.

Every object is a plain FreeCAD object: files open without this workbench.
"""
import math

import FreeCAD as App
import Part
import Sketcher

V = App.Vector
PITCH_MM = 3 / 8 * 25.4          # 9.525
DEFAULT_WIDTH_MM = 23 / 4 * 25.4  # 146.05
SHEET, OUTLINE, POINTS, HOLES, GROUP = ("PanelBlank", "BlankOutline", "BlankMountPoints",
                                        "BlankHoles", "PanelBlankGroup")
# name: (clearance hole Ø, head Ø) in mm. Hole 0 = points only, no circles.
FASTENERS = {
    "M5 socket cap": (5.6, 8.5),
    "M5 self-tap (printed)": (4.7, 8.5),  # coupon on the H2C: 4.6 tight but threads, <=4.4 too small
    "M4 socket cap": (4.5, 7.0),
    "M6 socket cap": (6.6, 10.0),
    "Dzus stud": (6.6, 9.53),
    "None (points only)": (0.0, 0.0),
}
DEFAULT_FASTENER = "M5 socket cap"


def nearest_units(height_mm):
    return max(4, round(height_mm / PITCH_MM))


def rows_for(units, extra_rows):
    """Row positions in pitch units from the top edge."""
    if units < 4:
        raise ValueError("units must be >= 4 (N=3 leaves one stud per side)")
    for r in extra_rows:
        if abs((r % 1) - 0.5) > 1e-9:
            raise ValueError(f"extra row {r} is not a half-unit (k + 0.5)")
        if not 1.5 <= r <= units - 1.5:
            raise ValueError(f"row {r:g} is outside the outer rows (1.5 and {units - 1.5:g}) "
                             f"of a {units}U panel")
    return sorted({1.5, units - 1.5, *extra_rows})


def full_rail_rows(units):
    """Every half-unit between the outer rows: any stack of panels totalling N fits."""
    return [k + 0.5 for k in range(2, units - 2)]


def _extras_only(units, rows):
    """Drop the always-present outer rows (and duplicates) from what the user typed."""
    return sorted({r for r in rows if r not in (1.5, units - 1.5)})


def _sheet(doc, units, width_mm, extra_rows, fastener, hole_dia, corner_r):
    ss = doc.getObject(SHEET) or doc.addObject("Spreadsheet::Sheet", SHEET)
    ss.clearAll()
    cells = [("units", str(units)),
             ("pitch", "=3 / 8 * 25.4 mm"),
             ("width", "=23 / 4 * 25.4 mm" if abs(width_mm - DEFAULT_WIDTH_MM) < 1e-9 else f"{width_mm} mm"),
             ("fastener", "'" + fastener),
             ("hole_dia", f"{hole_dia} mm"),
             ("corner_r", f"{corner_r} mm")]
    cells += [(f"row_e{i + 1}", str(r)) for i, r in enumerate(extra_rows)]
    for n, (alias, value) in enumerate(cells, start=1):
        ss.set(f"A{n}", alias)
        ss.set(f"B{n}", value)
        ss.setAlias(f"B{n}", alias)
    return ss


def _sketch(doc, name):
    sk = doc.getObject(name)
    if sk is None:
        sk = doc.addObject("Sketcher::SketchObject", name)
        sk.Placement = App.Placement()   # XY = top plane, origin at panel centre
    else:
        sk.deleteAllGeometry()           # same object, so binders stay linked
    return sk


def rect_outline(sk, edges, exprs, radius, radius_expr):
    """A closed rectangle in sketch sk, fully constrained.

    edges:  (left, right, top, bottom) as numbers, the starting geometry
    exprs:  the same four as expressions, so sheet edits move the edges
    radius: corner radius; 0 gives sharp corners, > 0 adds a tangent arc per
            corner sized by radius_expr. Switching between the two needs a re-run.
    """
    xl, xr, yt, yb = edges
    con = Sketcher.Constraint
    if radius <= 0:
        c = [V(xl, yt, 0), V(xr, yt, 0), V(xr, yb, 0), V(xl, yb, 0)]
        for i in range(4):
            sk.addGeometry(Part.LineSegment(c[i], c[(i + 1) % 4]))
        for i in range(4):
            sk.addConstraint(con("Coincident", i, 2, (i + 1) % 4, 1))
        sk.addConstraint(con("Horizontal", 0))
        sk.addConstraint(con("Horizontal", 2))
        sk.addConstraint(con("Vertical", 1))
        sk.addConstraint(con("Vertical", 3))
        # line 3 starts bottom-left, line 1 starts top-right, line 0 starts top-left, line 2 bottom-right
        placed = [("DistanceX", 3, 1, xl, exprs[0]), ("DistanceX", 1, 1, xr, exprs[1]),
                  ("DistanceY", 0, 1, yt, exprs[2]), ("DistanceY", 2, 1, yb, exprs[3])]
    else:
        r = radius
        top = sk.addGeometry(Part.LineSegment(V(xl + r, yt, 0), V(xr - r, yt, 0)))
        right = sk.addGeometry(Part.LineSegment(V(xr, yb + r, 0), V(xr, yt - r, 0)))
        bottom = sk.addGeometry(Part.LineSegment(V(xl + r, yb, 0), V(xr - r, yb, 0)))
        left = sk.addGeometry(Part.LineSegment(V(xl, yb + r, 0), V(xl, yt - r, 0)))
        q = math.pi / 2

        def arc(cx, cy, a0):
            return sk.addGeometry(Part.ArcOfCircle(Part.Circle(V(cx, cy, 0), V(0, 0, 1), r), a0, a0 + q))

        tr = arc(xr - r, yt - r, 0)        # starts on the right edge, ends on the top
        tl = arc(xl + r, yt - r, q)        # starts on the top, ends on the left edge
        bl = arc(xl + r, yb + r, 2 * q)    # starts on the left edge, ends on the bottom
        br = arc(xr - r, yb + r, 3 * q)    # starts on the bottom, ends on the right edge
        for a, b in [((top, 2), (tr, 2)), ((top, 1), (tl, 1)), ((right, 2), (tr, 1)), ((right, 1), (br, 2)),
                     ((bottom, 1), (bl, 2)), ((bottom, 2), (br, 1)), ((left, 1), (bl, 1)), ((left, 2), (tl, 2))]:
            sk.addConstraint(con("Tangent", a[0], a[1], b[0], b[1]))
        sk.addConstraint(con("Horizontal", top))
        sk.addConstraint(con("Horizontal", bottom))
        sk.addConstraint(con("Vertical", left))
        sk.addConstraint(con("Vertical", right))
        for g in (tr, tl, bl, br):
            c = sk.addConstraint(con("Radius", g, r))
            sk.setExpression(f"Constraints[{c}]", radius_expr)
        placed = [("DistanceX", left, 1, xl, exprs[0]), ("DistanceX", right, 1, xr, exprs[1]),
                  ("DistanceY", top, 1, yt, exprs[2]), ("DistanceY", bottom, 1, yb, exprs[3])]
    for kind, g, pos, value, expr in placed:
        c = sk.addConstraint(con(kind, -1, 1, g, pos, value))
        sk.setExpression(f"Constraints[{c}]", expr)
    return sk


def _outline(doc, units, width_mm, corner_r):
    sk = _sketch(doc, OUTLINE)
    S, w, h = SHEET, width_mm / 2, units * PITCH_MM / 2
    exprs = (f"-{S}.width / 2", f"{S}.width / 2", f"{S}.units * {S}.pitch / 2", f"-{S}.units * {S}.pitch / 2")
    return rect_outline(sk, (-w, w, h, -h), exprs, corner_r, f"{S}.corner_r")


def check_outline(units, width_mm, corner_r, hole_dia, insets=(0, 0, 0, 0)):
    """Raise ValueError when the corner radius or the edge insets would cut into a
    mount point (or its hole) or leave no outline. insets = (left, right, top, bottom),
    positive = the edge moves inward."""
    il, ir, it, ib = insets
    w, h = width_mm - il - ir, units * PITCH_MM - it - ib
    if min(insets) < 0:
        raise ValueError("insets can't be negative (positive = smaller)")
    if w <= 0 or h <= 0:
        raise ValueError("the insets leave no panel")
    if corner_r < 0:
        raise ValueError("the corner radius can't be negative")
    if corner_r >= min(w, h) / 2:
        raise ValueError(f"corner radius {corner_r:g} mm is too big for a {w:g} x {h:g} mm outline")
    side_room = PITCH_MM / 2 - hole_dia / 2          # mount column to side edge, minus the hole
    end_room = 1.5 * PITCH_MM - hole_dia / 2         # outer row to top/bottom edge, minus the hole
    for name, inset, room in (("left", il, side_room), ("right", ir, side_room),
                              ("top", it, end_room), ("bottom", ib, end_room)):
        if inset >= room:
            raise ValueError(f"{name} inset {inset:g} mm reaches the mount holes "
                             f"(keep it under {room:.2f} mm)")
    # the corner mount holes must stay inside the rounded corner
    xl, xr = -width_mm / 2 + il, width_mm / 2 - ir
    yt, yb = units * PITCH_MM / 2 - it, -units * PITCH_MM / 2 + ib
    hx, hy = width_mm / 2 - PITCH_MM / 2, units * PITCH_MM / 2 - 1.5 * PITCH_MM
    for px, py in ((hx, hy), (-hx, hy), (hx, -hy), (-hx, -hy)):
        if _depth_inside(px, py, xl, xr, yt, yb, corner_r) <= hole_dia / 2:
            raise ValueError(f"corner radius {corner_r:g} mm cuts into the corner mount holes")


def _depth_inside(px, py, xl, xr, yt, yb, r):
    """How far point (px, py) is inside a rectangle with corner radius r
    (negative = outside)."""
    qx = abs(px - (xl + xr) / 2) - ((xr - xl) / 2 - r)
    qy = abs(py - (yt + yb) / 2) - ((yt - yb) / 2 - r)
    return r - math.hypot(max(qx, 0), max(qy, 0)) - min(max(qx, qy), 0)


def _mount_exprs(n_extra):
    """(x, y) expressions for every mount position; points and holes share them."""
    S = SHEET
    # rows: the two outer rows by formula, the extras read from their own cells
    row_exprs = ["1.5", f"{S}.units - 1.5"] + [f"{S}.row_e{i + 1}" for i in range(n_extra)]
    for row in row_exprs:
        for side in (-1, 1):
            yield (side, f"{side} * ({S}.width / 2 - {S}.pitch / 2)",
                   f"{S}.units * {S}.pitch / 2 - ({row}) * {S}.pitch")


def _place(sk, g, pos, side, x_expr, y_expr):
    cx = sk.addConstraint(Sketcher.Constraint("DistanceX", -1, 1, g, pos, side * 60))
    cy = sk.addConstraint(Sketcher.Constraint("DistanceY", -1, 1, g, pos, 0))
    sk.setExpression(f"Constraints[{cx}]", x_expr)
    sk.setExpression(f"Constraints[{cy}]", y_expr)


def _points(doc, n_extra):
    sk = _sketch(doc, POINTS)
    for side, x, y in _mount_exprs(n_extra):
        g = sk.addGeometry(Part.Point(V(side * 60, 0, 0)))
        _place(sk, g, 1, side, x, y)
    return sk


def _holes(doc, n_extra, hole_dia):
    """Circles at the mount positions, sized by PanelBlank.hole_dia. Empty when points-only."""
    sk = _sketch(doc, HOLES)
    if hole_dia > 0:
        for side, x, y in _mount_exprs(n_extra):
            g = sk.addGeometry(Part.Circle(V(side * 60, 0, 0), V(0, 0, 1), hole_dia / 2))
            _place(sk, g, 3, side, x, y)  # 3 = circle centre
            d = sk.addConstraint(Sketcher.Constraint("Diameter", g, hole_dia))
            sk.setExpression(f"Constraints[{d}]", f"{SHEET}.hole_dia")
    return sk


def make_blank(doc, units, width_mm=DEFAULT_WIDTH_MM, extra_rows=(),
               fastener=DEFAULT_FASTENER, hole_dia=None, corner_r=0.0):
    """corner_r rounds the panel's corners (every plate follows the outline);
    0 keeps them sharp."""
    rows_for(units, extra_rows)  # validate what was typed
    extra_rows = _extras_only(units, extra_rows)
    if hole_dia is None:
        hole_dia = FASTENERS[fastener][0]
    check_outline(units, width_mm, corner_r, hole_dia)
    if doc.getObject("PlateStack"):  # the faceplate's insets must still fit the new blank
        from . import plate_stack
        check_outline(units, width_mm, corner_r, hole_dia, plate_stack.read_insets(doc))
    _sheet(doc, units, width_mm, extra_rows, fastener, hole_dia, corner_r)
    outline = _outline(doc, units, width_mm, corner_r)
    if doc.getObject("PlateStack"):  # rebuild the faceplate outline before the recompute sees the new corners
        plate_stack._face_outline(doc, plate_stack.read_insets(doc), (units, width_mm, corner_r))
    points = _points(doc, len(extra_rows))
    holes = _holes(doc, len(extra_rows), hole_dia)
    grp = doc.getObject(GROUP) or doc.addObject("App::DocumentObjectGroup", GROUP)
    grp.Label = "Panel Blank"
    for o in (doc.getObject(SHEET), outline, points, holes):
        if o not in grp.Group:
            grp.addObject(o)
    doc.recompute()
    if doc.getObject("PlateStack"):  # a plate stack built on this blank follows the new rows
        from . import plate_stack
        plate_stack.update(doc)
    return outline, points


def _read_existing(doc):
    ss = doc.getObject(SHEET)
    if ss is None:
        return 6, DEFAULT_WIDTH_MM, (), DEFAULT_FASTENER, FASTENERS[DEFAULT_FASTENER][0], 0.0
    extras, i = [], 1
    while True:
        try:
            extras.append(float(ss.get(f"row_e{i}")))
        except Exception:
            break
        i += 1
    def cell(alias, default):
        try:
            return ss.get(alias)
        except Exception:  # blank made by an older version of this macro
            return default
    w = ss.get("width")
    h = cell("hole_dia", FASTENERS[DEFAULT_FASTENER][0])
    r = cell("corner_r", 0.0)
    fastener = cell("fastener", DEFAULT_FASTENER)
    fastener = fastener if fastener in FASTENERS else DEFAULT_FASTENER
    return (int(ss.get("units")), float(getattr(w, "Value", w)), tuple(extras),
            fastener, float(getattr(h, "Value", h)), float(getattr(r, "Value", r)))


def run_dialog():
    import FreeCADGui as Gui
    from PySide import QtWidgets

    doc = App.ActiveDocument or App.newDocument("PanelBlank")
    units0, width0, extras0, fastener0, hole0, corner0 = _read_existing(doc)

    dlg = QtWidgets.QDialog(Gui.getMainWindow())
    dlg.setWindowTitle("Panel Blank" + (" — update" if doc.getObject(SHEET) else ""))
    form = QtWidgets.QFormLayout(dlg)
    units = QtWidgets.QSpinBox(); units.setRange(4, 60); units.setValue(units0)
    measured = QtWidgets.QDoubleSpinBox(); measured.setRange(0, 600); measured.setDecimals(3)
    measured.setSpecialValueText("—"); measured.setSuffix(" mm")
    hint = QtWidgets.QLabel()
    width = QtWidgets.QDoubleSpinBox(); width.setRange(20, 600); width.setDecimals(4)
    width.setSuffix(" mm"); width.setValue(width0)
    extras = QtWidgets.QLineEdit(", ".join(f"{r:g}" for r in extras0))
    extras.setPlaceholderText("e.g. 2.5, 4.5  (blank = none)")
    extras_label = QtWidgets.QLabel()
    full = QtWidgets.QCheckBox("Full rail: a row at every half-unit (frames / rails)")
    full.setChecked(bool(extras0) and list(extras0) == full_rail_rows(units0))
    full.toggled.connect(lambda on: extras.setEnabled(not on))
    extras.setEnabled(not full.isChecked())
    fastener = QtWidgets.QComboBox(); fastener.addItems(list(FASTENERS))
    fastener.setCurrentText(fastener0)
    hole = QtWidgets.QDoubleSpinBox(); hole.setRange(0, 20); hole.setDecimals(2)
    hole.setSuffix(" mm"); hole.setValue(hole0)
    head_note = QtWidgets.QLabel()
    corner = QtWidgets.QDoubleSpinBox(); corner.setRange(0, 20); corner.setDecimals(2)
    corner.setSuffix(" mm"); corner.setValue(corner0); corner.setSpecialValueText("sharp")
    corner.setToolTip("Rounds the panel's four corners; every plate in the stack follows. "
                      "A small radius cuts cleaner on a laser than a sharp corner")

    def on_fastener(name):
        hole.setValue(FASTENERS[name][0])
        hole.setEnabled(FASTENERS[name][0] > 0)
        head = FASTENERS[name][1]
        if head > PITCH_MM + 0.01:
            head_note.setText(f"⚠ head Ø{head:g} > 9.525 pitch: overhangs the side edge\n"
                              f"and collides on rows 1 unit apart")
        else:
            head_note.setText(f"head Ø{head:g}" if head else "no holes, mount points only")

    def refresh():
        n = units.value()
        extras_label.setText(f"Extra rows, units from top\n(1.5 and {n - 1.5:g} always included)")
        txt = f"Height = {n} × 9.525 = {n * PITCH_MM:.3f} mm"
        if measured.value() > 0:
            m = measured.value()
            txt += f"\nMeasured {m:.3f} → nearest {nearest_units(m)}U ({nearest_units(m) * PITCH_MM:.3f} mm, {nearest_units(m) * PITCH_MM - m:+.3f})"
        hint.setText(txt)

    measured.valueChanged.connect(lambda m: (m > 0 and units.setValue(nearest_units(m)), refresh()))
    units.valueChanged.connect(lambda _: refresh())
    refresh()
    on_fastener(fastener0)
    hole.setValue(hole0)  # keep a hand-typed Ø from the last run
    fastener.currentTextChanged.connect(on_fastener)

    form.addRow("Units (N)", units)
    form.addRow("…or measured height", measured)
    form.addRow("", hint)
    form.addRow("Width", width)
    form.addRow(extras_label, extras)
    form.addRow("", full)
    form.addRow("Fastener", fastener)
    form.addRow("Hole Ø", hole)
    form.addRow("", head_note)
    form.addRow("Corner radius", corner)
    buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
    buttons.accepted.connect(dlg.accept); buttons.rejected.connect(dlg.reject)
    form.addRow(buttons)
    if not dlg.exec():
        return
    try:
        if full.isChecked():
            rows = tuple(full_rail_rows(units.value()))
        else:
            rows = tuple(float(t) for t in extras.text().replace(" ", "").split(",") if t)
        make_blank(doc, units.value(), width.value(), rows,
                   fastener.currentText(), hole.value() if hole.isEnabled() else 0.0, corner.value())
    except ValueError as e:
        QtWidgets.QMessageBox.warning(Gui.getMainWindow(), "Panel Blank", str(e))
        return
    Gui.activeDocument().activeView().viewTop()
    Gui.SendMsgToActiveView("ViewFit")
