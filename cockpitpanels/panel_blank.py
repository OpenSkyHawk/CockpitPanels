# SPDX-License-Identifier: LGPL-2.1-or-later
"""Panel Blank: the base blank for a Dzus-rail console panel.

Adds a panel blank to the active document, inside a "Panel Blank" group:
  PanelBlank        spreadsheet: units, pitch, width, fastener, hole_dia, extra rows
  BlankOutline      sketch: panel rectangle, centred on the origin, XY (top) plane
  BlankMountPoints  sketch: one point per mount position on the Dzus grid
  BlankHoles        sketch: one clearance circle per mount (empty for "None")
All dimensions are spreadsheet expressions, so editing a cell + recompute moves
everything. Running again on a doc that already has a blank updates the same
sketches in place, so SubShapeBinders pointing at them keep working.

Every object is a plain FreeCAD object: files open without this workbench.
"""
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


def _sheet(doc, units, width_mm, extra_rows, fastener, hole_dia):
    ss = doc.getObject(SHEET) or doc.addObject("Spreadsheet::Sheet", SHEET)
    ss.clearAll()
    cells = [("units", str(units)),
             ("pitch", "=3 / 8 * 25.4 mm"),
             ("width", "=23 / 4 * 25.4 mm" if abs(width_mm - DEFAULT_WIDTH_MM) < 1e-9 else f"{width_mm} mm"),
             ("fastener", "'" + fastener),
             ("hole_dia", f"{hole_dia} mm")]
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


def _outline(doc):
    sk = _sketch(doc, OUTLINE)
    c = [V(-70, 25, 0), V(70, 25, 0), V(70, -25, 0), V(-70, -25, 0)]  # rough, constraints fix it
    for i in range(4):
        sk.addGeometry(Part.LineSegment(c[i], c[(i + 1) % 4]))
    for i in range(4):
        sk.addConstraint(Sketcher.Constraint("Coincident", i, 2, (i + 1) % 4, 1))
    for i in (0, 2):
        sk.addConstraint(Sketcher.Constraint("Horizontal", i))
    for i in (1, 3):
        sk.addConstraint(Sketcher.Constraint("Vertical", i))
    sk.addConstraint(Sketcher.Constraint("Symmetric", 0, 1, 1, 2, -1, 1))  # centred on origin
    w = sk.addConstraint(Sketcher.Constraint("DistanceX", 0, 1, 0, 2, 140))
    h = sk.addConstraint(Sketcher.Constraint("DistanceY", 1, 2, 1, 1, 50))
    sk.setExpression(f"Constraints[{w}]", f"{SHEET}.width")
    sk.setExpression(f"Constraints[{h}]", f"{SHEET}.units * {SHEET}.pitch")
    return sk


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
               fastener=DEFAULT_FASTENER, hole_dia=None):
    rows_for(units, extra_rows)  # validate what was typed
    extra_rows = _extras_only(units, extra_rows)
    if hole_dia is None:
        hole_dia = FASTENERS[fastener][0]
    _sheet(doc, units, width_mm, extra_rows, fastener, hole_dia)
    outline = _outline(doc)
    points = _points(doc, len(extra_rows))
    holes = _holes(doc, len(extra_rows), hole_dia)
    grp = doc.getObject(GROUP) or doc.addObject("App::DocumentObjectGroup", GROUP)
    grp.Label = "Panel Blank"
    for o in (doc.getObject(SHEET), outline, points, holes):
        if o not in grp.Group:
            grp.addObject(o)
    doc.recompute()
    return outline, points


def _read_existing(doc):
    ss = doc.getObject(SHEET)
    if ss is None:
        return 6, DEFAULT_WIDTH_MM, (), DEFAULT_FASTENER, FASTENERS[DEFAULT_FASTENER][0]
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
    fastener = cell("fastener", DEFAULT_FASTENER)
    fastener = fastener if fastener in FASTENERS else DEFAULT_FASTENER
    return (int(ss.get("units")), float(getattr(w, "Value", w)), tuple(extras),
            fastener, float(getattr(h, "Value", h)))


def run_dialog():
    import FreeCADGui as Gui
    from PySide import QtWidgets

    doc = App.ActiveDocument or App.newDocument("PanelBlank")
    units0, width0, extras0, fastener0, hole0 = _read_existing(doc)

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
                   fastener.currentText(), hole.value() if hole.isEnabled() else 0.0)
    except ValueError as e:
        QtWidgets.QMessageBox.warning(Gui.getMainWindow(), "Panel Blank", str(e))
        return
    Gui.activeDocument().activeView().viewTop()
    Gui.SendMsgToActiveView("ViewFit")
