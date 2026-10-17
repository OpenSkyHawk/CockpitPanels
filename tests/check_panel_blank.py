# SPDX-License-Identifier: LGPL-2.1-or-later
"""Headless checks for the Panel Blank tool.

Run with FreeCAD's command-line binary (not its bundled python, which crashes on
`import Part`):

    freecadcmd tests/check_panel_blank.py

Prints one PASS/FAIL line per check and exits non-zero if any check fails.
"""
import math
import os
import sys
import tempfile


def _repo_root():
    try:
        here = os.path.abspath(__file__)
    except NameError:  # freecadcmd may run the file without setting __file__
        here = next(os.path.abspath(a) for a in sys.argv if a.endswith("check_panel_blank.py"))
    return os.path.dirname(os.path.dirname(here))


sys.path.insert(0, _repo_root())

import FreeCAD as App  # noqa: E402
import importDXF  # noqa: E402
import Part  # noqa: E402

from cockpitpanels import panel_blank as pb  # noqa: E402

P = pb.PITCH_MM
TOL = 1e-6
results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail and not ok else ""))


def close(a, b, tol=TOL):
    return abs(a - b) <= tol


def points(doc):
    return sorted((round(v.Point.x, 4), round(v.Point.y, 4)) for v in doc.BlankMountPoints.Shape.Vertexes)


def circles(doc):
    return sorted((round(e.Curve.Center.x, 4), round(e.Curve.Center.y, 4), round(e.Curve.Radius * 2, 4))
                  for e in doc.BlankHoles.Shape.Edges)


def rows(doc):
    """Mount rows in units from the top edge, read back from the geometry."""
    top = doc.BlankOutline.Shape.BoundBox.YMax
    return sorted({round((top - y) / P, 4) for _, y in points(doc)})


def fully_constrained(sk):
    return sk.solve() == 0 and getattr(sk, "FullyConstrained", True)


def new_doc(name):
    return App.newDocument(name)


# --- reference panels ------------------------------------------------------
REFERENCE = [  # name, N, extra rows typed, expected rows
    ("APN-153", 6, (), [1.5, 4.5]),
    ("ASN-41", 14, (3.5, 8.5, 10.5), [1.5, 3.5, 8.5, 10.5, 12.5]),
    ("ARC-51A", 13, (2.5, 10.5), [1.5, 2.5, 10.5, 11.5]),
]
for name, n, extra, expected in REFERENCE:
    doc = new_doc("Ref")
    pb.make_blank(doc, n, extra_rows=extra)
    got = rows(doc)
    check(f"{name} {n}U rows {expected}", got == expected, f"got {got}")
    check(f"{name} height {n} x 9.525", close(doc.BlankOutline.Shape.BoundBox.YLength, n * P, 1e-4))
    App.closeDocument(doc.Name)

# --- APN-153 geometry ------------------------------------------------------
doc = new_doc("Apn")
own = doc.addObject("Spreadsheet::Sheet", "Spreadsheet")  # a panel doc's own sheet
own.set("A1", "1.5875 mm")
own.setAlias("A1", "t_faceplate")
pb.make_blank(doc, 6)
pts = points(doc)
check("6U points on the APN-153 pattern 136.525 x 28.575",
      pts == [(-68.2625, -14.2875), (-68.2625, 14.2875), (68.2625, -14.2875), (68.2625, 14.2875)], pts)
bb = doc.BlankOutline.Shape.BoundBox
check("outline 146.05 x 57.15, centred on the origin",
      all(close(a, b, 1e-4) for a, b in ((bb.XMin, -73.025), (bb.XMax, 73.025), (bb.YMin, -28.575), (bb.YMax, 28.575))))
wires = doc.BlankOutline.Shape.Wires
check("outline is one closed wire", len(wires) == 1 and wires[0].isClosed())
for sk in (doc.BlankOutline, doc.BlankMountPoints, doc.BlankHoles):
    check(f"{sk.Name} fully constrained", fully_constrained(sk))
check("hole centres == mount points", [(x, y) for x, y, _ in circles(doc)] == pts)
check("default fastener M5 socket cap, hole 5.6",
      doc.PanelBlank.get("fastener") == "M5 socket cap" and {d for *_, d in circles(doc)} == {5.6})
check("objects grouped under 'Panel Blank'",
      {o.Name for o in doc.getObject(pb.GROUP).Group} == {pb.SHEET, pb.OUTLINE, pb.POINTS, pb.HOLES})

# --- layer body consuming the blank through binders ------------------------
body = doc.addObject("PartDesign::Body", "Faceplate")
ob = body.newObject("PartDesign::SubShapeBinder", "OutlineBinder")
ob.Support = [(doc.BlankOutline, [""])]
pad = body.newObject("PartDesign::Pad", "Pad")
pad.Profile = ob
pad.Length = 1.5875
doc.recompute()  # one object at a time: a single recompute over the chain breaks the Hole
pbind = body.newObject("PartDesign::SubShapeBinder", "PointsBinder")
pbind.Support = [(doc.BlankMountPoints, [""])]
doc.recompute()
hole = body.newObject("PartDesign::Hole", "Hole")
hole.Profile = pbind
hole.Diameter = 5.6
hole.DepthType = "ThroughAll"
doc.recompute()


def holes_cut(n_dia=5.6):
    return (pad.Shape.Volume - hole.Shape.Volume) / (math.pi * (n_dia / 2) ** 2 * pad.Length.Value)


hole.Reversed = False
doc.recompute()
check("Hole on points without Reversed cuts nothing (documented gotcha)", close(holes_cut(), 0, 1e-3))
hole.Reversed = True
doc.recompute()
check("Hole on points with Reversed cuts 4 holes", close(holes_cut(), 4, 1e-3), f"{holes_cut():.3f}")

# --- live spreadsheet edits ------------------------------------------------
doc.PanelBlank.set("units", "7")
doc.recompute()
check("units 6 -> 7 moves the points", sorted({y for _, y in points(doc)}) == [-19.05, 19.05])
check("units edit: holes follow the points", [(x, y) for x, y, _ in circles(doc)] == points(doc))
check("units edit: binder hole still cuts 4", close(holes_cut(), 4, 1e-3))
doc.PanelBlank.set("width", "150 mm")
doc.recompute()
check("width edit moves the columns to +-(width/2 - pitch/2)",
      sorted({x for x, _ in points(doc)}) == [round(-(75 - P / 2), 4), round(75 - P / 2, 4)])
doc.PanelBlank.set("hole_dia", "6 mm")
doc.recompute()
check("hole_dia edit resizes every hole", {d for *_, d in circles(doc)} == {6.0})

# --- in-place re-run -------------------------------------------------------
before = (doc.BlankOutline, doc.BlankMountPoints, doc.BlankHoles)
pb.make_blank(doc, 7, extra_rows=(3.5,))
doc.recompute()
check("re-run reuses the same sketch objects",
      (doc.BlankOutline, doc.BlankMountPoints, doc.BlankHoles) == before)
check("re-run: binders still valid", all("Invalid" not in o.State and "Error" not in o.State
                                          for o in (ob, pad, pbind, hole)), [o.State for o in (ob, pad, pbind, hole)])
check("re-run: binder hole now cuts 6", close(holes_cut(), 6, 1e-3), f"{holes_cut():.3f}")
check("panel's own Spreadsheet untouched", own.get("t_faceplate").Value == 1.5875)

pb.make_blank(doc, 7, extra_rows=(3.5,), fastener="None (points only)")
check("'None' empties BlankHoles, same object", doc.BlankHoles is before[2] and not doc.BlankHoles.Shape.Edges)
check("'None' keeps the 6 points", len(points(doc)) == 6)
App.closeDocument(doc.Name)

# --- stacked panels --------------------------------------------------------
top, low = new_doc("Top"), new_doc("Low")
pb.make_blank(top, 4)
pb.make_blank(low, 7)
# put the 7U panel directly under the 4U one
shift = top.BlankOutline.Shape.BoundBox.YMin - low.BlankOutline.Shape.BoundBox.YMax
lowest_top_row = min(y for _, y in points(top))
highest_low_row = max(y for _, y in points(low)) + shift
check("N=4 over N=7: 28.575 between rows across the joint",
      close(lowest_top_row - highest_low_row, 3 * P, 1e-4), f"{lowest_top_row - highest_low_row:.4f}")
App.closeDocument(top.Name)
App.closeDocument(low.Name)

# --- full rail -------------------------------------------------------------
doc = new_doc("Rail")
pb.make_blank(doc, 20, extra_rows=pb.full_rail_rows(20), fastener="M5 self-tap (printed)")
rail = rows(doc)
check("20U full rail: a row every half-unit 1.5..18.5", rail == [k + 0.5 for k in range(1, 19)], rail)
check("20U full rail: 36 holes at 4.7", len(circles(doc)) == 36 and {d for *_, d in circles(doc)} == {4.7})
for combo in [(6, 14), (7, 13), (4, 6, 10), (4, 4, 4, 4, 4)]:
    off, need = 0, []
    for n in combo:
        need += [off + 1.5, off + n - 1.5]
        off += n
    check(f"stack {combo} lands on the 20U rail", all(r in rail for r in need))
App.closeDocument(doc.Name)

# --- fastener presets ------------------------------------------------------
for name, (hole_dia, head) in pb.FASTENERS.items():
    doc = new_doc("F")
    pb.make_blank(doc, 6, fastener=name)
    want = {hole_dia} if hole_dia else set()
    check(f"preset '{name}' -> holes {want or 'none'}", {d for *_, d in circles(doc)} == want)
    App.closeDocument(doc.Name)
check("M6 head is wider than the pitch (dialog warns)", pb.FASTENERS["M6 socket cap"][1] > P)
check("M5 head fits inside the pitch", pb.FASTENERS["M5 socket cap"][1] < P)

# --- DXF export ------------------------------------------------------------
def dxf_entities(path):
    """{(entity type, layer): count} for the LINE / CIRCLE / ARC entities in a DXF."""
    lines = [ln.strip() for ln in open(path).read().split("\n")]
    found = {}
    for i, ln in enumerate(lines[:-1]):
        if ln in ("LINE", "CIRCLE", "ARC") and lines[i - 1] == "0":
            j = i + 1
            while j < len(lines) - 1 and lines[j] != "0":
                if lines[j] == "8":
                    found[(ln, lines[j + 1])] = found.get((ln, lines[j + 1]), 0) + 1
                    break
                j += 2
    return found


doc = new_doc("Dxf")
pb.make_blank(doc, 6)
ctl = doc.addObject("Sketcher::SketchObject", "Controls")  # a user's own cutout sketch
ctl.addGeometry(Part.Circle(App.Vector(-40, 0, 0), App.Vector(0, 0, 1), 4.8))
doc.recompute()
path = os.path.join(tempfile.mkdtemp(), "blank.dxf")
importDXF.export([doc.BlankOutline, doc.BlankHoles, ctl], path)
entities = dxf_entities(path)
check("DXF: outline = 4 LINE on layer BlankOutline", entities.get(("LINE", "BlankOutline")) == 4, entities)
check("DXF: holes = 4 CIRCLE on layer BlankHoles", entities.get(("CIRCLE", "BlankHoles")) == 4, entities)
check("DXF: user sketch on its own layer", entities.get(("CIRCLE", "Controls")) == 1, entities)
App.closeDocument(doc.Name)

# --- three-layer plate stack + Export Layers --------------------------------
from cockpitpanels import export_layers as el  # noqa: E402

doc = new_doc("Stack")
pb.make_blank(doc, 6)
plates = []
for name in ("FacePlate", "Diffuser", "BackPlate"):
    body = doc.addObject("PartDesign::Body", name)
    ob = body.newObject("PartDesign::SubShapeBinder", name + "_Outline")
    ob.Support = [(doc.BlankOutline, [""])]
    pad = body.newObject("PartDesign::Pad", name + "_Pad")
    pad.Profile = ob
    pad.Length = 3
    doc.recompute()
    pbind = body.newObject("PartDesign::SubShapeBinder", name + "_Points")
    pbind.Support = [(doc.BlankMountPoints, [""])]
    doc.recompute()
    hole = body.newObject("PartDesign::Hole", name + "_Holes")
    hole.Profile = pbind
    hole.DepthType = "ThroughAll"
    hole.Reversed = True
    hole.setExpression("Diameter", "PanelBlank.hole_dia")
    doc.recompute()
    plates.append(body)
doc.getObject("BackPlate").Label = "Back plate (3 mm)"  # labels with spaces must still give a clean name


def plate_holes(body):
    return len([e for e in el.plate_profile(body).Edges if e.Curve.TypeId == "Part::GeomCircle"])


check("stack: each plate has 4 holes at 6U", all(plate_holes(b) == 4 for b in plates))
pb.make_blank(doc, 7, extra_rows=(3.5,))
doc.recompute()
check("stack: re-run 7U + row 3.5 resizes every plate",
      all(close(b.Shape.BoundBox.YLength, 7 * P, 1e-4) and plate_holes(b) == 6 for b in plates))
check("stack: every feature still valid after the re-run",
      all("Invalid" not in o.State and "Error" not in o.State for b in plates for o in b.Group))
check("find_plates finds the three bodies", [b.Name for b in el.find_plates(doc)] == [b.Name for b in plates])

folder = tempfile.mkdtemp()
n_objects = len(doc.Objects)
written = el.export_layers(plates, folder)
names = sorted(os.path.basename(p) for p in written)
check("Export Layers: one file per plate, named after the label",
      names == ["Back_plate_3_mm.dxf", "Diffuser.dxf", "FacePlate.dxf"], names)
check("Export Layers: the document is not modified", len(doc.Objects) == n_objects)
check("Export Layers: scratch document closed", "CockpitPanelsExport" not in App.listDocuments())
for path in written:
    layer = os.path.basename(path)[:-4]
    ents = dxf_entities(path)
    check(f"Export Layers: {layer} = 4 LINE + 6 CIRCLE on layer {layer}",
          ents == {("LINE", layer): 4, ("CIRCLE", layer): 6}, ents)
App.closeDocument(doc.Name)

# --- Plate Stack -----------------------------------------------------------
from cockpitpanels import plate_stack as ps  # noqa: E402


def profile_circles(body):
    """Diameters of the full circles on the plate's back face."""
    return sorted(round(e.Curve.Radius * 2, 3) for e in el.plate_profile(body).Edges
                  if e.Curve.TypeId == "Part::GeomCircle" and e.isClosed())


doc = new_doc("PlateStack")
pb.make_blank(doc, 6)
stack = ps.make_stack(doc)
IN = 25.4
want = {"FacePlate": (-IN / 16, 0), "Diffuser": (-3 * IN / 16, -IN / 16), "BackPlate": (-5 * IN / 16, -3 * IN / 16)}
check("stack: default layers FacePlate / Diffuser / BackPlate", [b.Name for b in stack] == list(want))
for b in stack:
    bb = b.Shape.BoundBox
    check(f"stack: {b.Name} spans z {want[b.Name][0]:.4f}..{want[b.Name][1]:.4f} (front at z = 0)",
          close(bb.ZMin, want[b.Name][0], 1e-6) and close(bb.ZMax, want[b.Name][1], 1e-6), (bb.ZMin, bb.ZMax))
    check(f"stack: {b.Name} is one solid, 146.05 x 57.15", len(b.Shape.Solids) == 1
          and close(bb.XLength, 146.05, 1e-4) and close(bb.YLength, 57.15, 1e-4))
check("stack: faceplate has 4 recesses at 9.5", profile_circles(doc.FacePlate) == [9.5] * 4, profile_circles(doc.FacePlate))
check("stack: diffuser and backplate have 4 clearance holes at 5.6",
      profile_circles(doc.Diffuser) == [5.6] * 4 and profile_circles(doc.BackPlate) == [5.6] * 4)
check("stack: faceplate volume = plate - 4 recesses",
      close(doc.FacePlate.Shape.Volume, 146.05 * 57.15 * IN / 16 - 4 * math.pi * 4.75 ** 2 * IN / 16, 1e-3))
for name in (ps.RECESSES, ps.SLOTS):
    sk = doc.getObject(name)
    check(f"stack: {name} fully constrained, 4 closed profiles",
          fully_constrained(sk) and len(sk.Shape.Wires) == 4 and all(w.isClosed() for w in sk.Shape.Wires))

doc.PlateStack.set("recess_dia", "9 mm")
doc.recompute()
check("stack: recess_dia cell edit resizes the recesses live", profile_circles(doc.FacePlate) == [9.0] * 4)
ps.make_stack(doc, [("FacePlate", "=1/16 * 25.4 mm", "Slot"), ("Diffuser", "=1/8 * 25.4 mm", "Clearance"),
                    ("BackPlate", "=1/8 * 25.4 mm", "Clearance")], 9.5)
recess_vol = 146.05 * 57.15 * IN / 16 - 4 * math.pi * 4.75 ** 2 * IN / 16
check("stack: Slot style removes more than a recess and keeps one solid",
      doc.FacePlate.Shape.Volume < recess_vol - 1 and len(doc.FacePlate.Shape.Solids) == 1)
check("stack: Slot style opens the faceplate's side edges (no full recess circles left)",
      profile_circles(doc.FacePlate) == [])
before = [b.Shape.BoundBox.ZMin for b in stack]
pb.make_blank(doc, 7, extra_rows=(3.5,))
doc.recompute()
check("stack: Panel Blank re-run (7U + row 3.5) resizes every layer",
      all(close(b.Shape.BoundBox.YLength, 7 * P, 1e-4) for b in stack))
after = [b.Shape.BoundBox.ZMin for b in stack]
check("stack: ... and keeps the depths", all(close(a, b, 1e-6) for a, b in zip(after, before)), (before, after))
check("stack: ... and the slot sketch follows the new row (6 slots)", len(doc.StackSlots.Shape.Wires) == 6)
check("stack: ... diffuser now has 6 holes", profile_circles(doc.Diffuser) == [5.6] * 6)
check("stack: every feature valid after the re-run",
      all("Invalid" not in o.State and "Error" not in o.State for b in stack for o in b.Group))
layers, rd, _ = ps.read_existing(doc)
check("stack: settings read back from the sheet",
      [(n, s) for n, _, s in layers] == [("FacePlate", "Slot"), ("Diffuser", "Clearance"), ("BackPlate", "Clearance")]
      and rd == 9.5 and [ps.thickness_text(t) for _, t, _ in layers] == ['1/16"', '1/8"', '1/8"'], layers)
ps.make_stack(doc, [("FacePlate", "=1/16 * 25.4 mm", "Recess"), ("Diffuser", "=1/8 * 25.4 mm", "Clearance"),
                    ("BackPlate", "=1/8 * 25.4 mm", "Clearance")], 9.5)
check("stack: switching back to Recess reuses the same bodies",
      [doc.getObject(n) for n in want] == stack and profile_circles(doc.FacePlate) == [9.5] * 6)
written = el.export_layers(stack, tempfile.mkdtemp())
ents = {os.path.basename(p)[:-4]: dxf_entities(p) for p in written}
check("stack + Export Layers: faceplate 4 LINE + 6 CIRCLE",
      ents["FacePlate"] == {("LINE", "FacePlate"): 4, ("CIRCLE", "FacePlate"): 6}, ents["FacePlate"])
App.closeDocument(doc.Name)

# --- corner radius + faceplate insets -------------------------------------
def arcs(shape):
    return sorted(round(e.Curve.Radius, 4) for e in shape.Edges
                  if e.Curve.TypeId == "Part::GeomCircle" and not e.isClosed())


doc = new_doc("Corners")
pb.make_blank(doc, 6, corner_r=2)
sk = doc.BlankOutline
check("corner_r 2: outline is 4 lines + 4 arcs R2, fully constrained",
      fully_constrained(sk) and len(sk.Shape.Edges) == 8 and arcs(sk.Shape) == [2.0] * 4
      and len(sk.Shape.Wires) == 1 and sk.Shape.Wires[0].isClosed(), arcs(sk.Shape))
bb = sk.Shape.BoundBox
check("corner_r 2: still 146.05 x 57.15, centred", close(bb.XLength, 146.05, 1e-4) and close(bb.YLength, 6 * P, 1e-4)
      and close(bb.Center.x, 0, 1e-6) and close(bb.Center.y, 0, 1e-6))
check("corner_r 2: mount points unchanged", points(doc) == sorted(
    (round(sx * (146.05 / 2 - P / 2), 4), round(sy * (3 * P - 1.5 * P), 4)) for sx in (-1, 1) for sy in (-1, 1)))
doc.PanelBlank.set("corner_r", "3 mm")
doc.recompute()
check("corner_r cell edit resizes the arcs live", arcs(doc.BlankOutline.Shape) == [3.0] * 4)
check("corner_r read back", pb._read_existing(doc)[5] == 3.0)

stack = ps.make_stack(doc, insets=(0.5, 0.5, 1, 1))
fp, df = doc.FacePlate.Shape.BoundBox, doc.Diffuser.Shape.BoundBox
check("insets: faceplate 145.05 x 55.15, centred",
      close(fp.XLength, 145.05, 1e-4) and close(fp.YLength, 6 * P - 2, 1e-4) and close(fp.Center.x, 0, 1e-6), (fp.XLength, fp.YLength))
check("insets: diffuser and backplate stay 146.05 x 57.15",
      all(close(b.XLength, 146.05, 1e-4) and close(b.YLength, 6 * P, 1e-4)
          for b in (df, doc.BackPlate.Shape.BoundBox)))
check("insets: StackFaceOutline fully constrained, same corner radius",
      fully_constrained(doc.StackFaceOutline) and arcs(doc.StackFaceOutline.Shape) == [3.0] * 4)
check("insets: every layer one valid solid",
      all(len(b.Shape.Solids) == 1 for b in stack)
      and all("Invalid" not in o.State and "Error" not in o.State for b in stack for o in b.Group))
check("insets: read back", ps.read_existing(doc)[2] == (0.5, 0.5, 1.0, 1.0), ps.read_existing(doc)[2])
ps.make_stack(doc, insets=(0, 1, 0, 0))
fp = doc.FacePlate.Shape.BoundBox
check("insets: right only moves the right edge", close(fp.XMin, -146.05 / 2, 1e-4) and close(fp.XMax, 146.05 / 2 - 1, 1e-4))
doc.PlateStack.set("inset_l", "1 mm")
doc.recompute()
check("insets: inset_l cell edit moves the left edge live", close(doc.FacePlate.Shape.BoundBox.XMin, -146.05 / 2 + 1, 1e-4))
pb.make_blank(doc, 6, corner_r=0)
check("Panel Blank re-run back to sharp corners: blank + faceplate outlines rebuilt",
      arcs(doc.BlankOutline.Shape) == [] and len(doc.BlankOutline.Shape.Edges) == 4
      and arcs(doc.StackFaceOutline.Shape) == [] and fully_constrained(doc.StackFaceOutline)
      and close(doc.FacePlate.Shape.BoundBox.XMax, 146.05 / 2 - 1, 1e-4))
pb.make_blank(doc, 6, corner_r=2)
written = el.export_layers([doc.FacePlate, doc.Diffuser], tempfile.mkdtemp())
ents = {os.path.basename(p)[:-4]: dxf_entities(p) for p in written}
check("rounded corners export: diffuser 4 LINE + 4 ARC + 4 CIRCLE",
      ents["Diffuser"] == {("LINE", "Diffuser"): 4, ("ARC", "Diffuser"): 4, ("CIRCLE", "Diffuser"): 4}, ents)
check("inset faceplate: the 9.5 recesses open through the 1 mm-inset sides (no full circles)",
      ("CIRCLE", "FacePlate") not in ents["FacePlate"] and ents["FacePlate"].get(("ARC", "FacePlate"), 0) > 4, ents)
for kwargs, why in [(dict(insets=(2, 0, 0, 0)), "a side inset into the 5.6 hole"),
                    (dict(insets=(0, 0, 12, 0)), "a top inset into the hole"),
                    (dict(insets=(0, 0, -1, 0)), "a negative inset")]:
    try:
        ps.make_stack(doc, **kwargs)
        check(f"insets reject {why}", False, "accepted")
    except ValueError:
        check(f"insets reject {why}", True)
check("rejected insets leave the sheet as it was", ps.read_insets(doc) == (1.0, 1.0, 0.0, 0.0), ps.read_insets(doc))
for r, why in [(25, "the corner holes"), (40, "half the height"), (-1, "a negative radius")]:
    try:
        pb.check_outline(6, 146.05, r, 5.6)
        check(f"corner radius {r} rejected ({why})", False, "accepted")
    except ValueError:
        check(f"corner radius {r} rejected ({why})", True)
check("corner radius 20 fits around the corner holes", pb.check_outline(6, 146.05, 20, 5.6) is None)
App.closeDocument(doc.Name)

for text, expr in [("3", "3 mm"), ("3 mm", "3 mm"), ('1/8"', "=1/8 * 25.4 mm"), ("1/16 in", "=1/16 * 25.4 mm"),
                   ("0.125 in", "=0.125 * 25.4 mm")]:
    check(f"thickness {text!r} -> {expr!r}", ps.parse_thickness(text) == expr, ps.parse_thickness(text))
doc = new_doc("Bad")
for args, why in [((), "no Panel Blank yet"), (([("A", "3 mm", "Recess"), ("A", "3 mm", "Clearance")],), "duplicate names"),
                  (([("A", "3 mm", "Countersink")],), "unknown style")]:
    if why != "no Panel Blank yet" and doc.getObject(pb.SHEET) is None:
        pb.make_blank(doc, 6)
    try:
        ps.make_stack(doc, *args)
        check(f"stack rejects {why}", False, "accepted")
    except ValueError:
        check(f"stack rejects {why}", True)
try:
    ps.parse_thickness("thick")
    check("thickness rejects 'thick'", False, "accepted")
except ValueError:
    check("thickness rejects 'thick'", True)
App.closeDocument(doc.Name)

# --- input validation ------------------------------------------------------
for bad, why in [((3, ()), "N < 4"), ((6, (3.0,)), "whole-unit row"),
                 ((6, (5.5,)), "row below the outer rows"), ((6, (0.5,)), "row above the outer rows")]:
    try:
        pb.rows_for(*bad)
        check(f"rejects {why} {bad}", False, "accepted")
    except ValueError:
        check(f"rejects {why} {bad}", True)
doc = new_doc("Outer")
pb.make_blank(doc, 6, extra_rows=(1.5, 4.5))
check("typed outer rows are accepted and ignored", rows(doc) == [1.5, 4.5] and len(points(doc)) == 4)
App.closeDocument(doc.Name)
check("measured 55.615 mm rounds to 6U", pb.nearest_units(55.615) == 6)

# ---------------------------------------------------------------------------
failed = results.count(False)
print(f"\n{len(results) - failed} passed, {failed} failed")
sys.stdout.flush()
os._exit(1 if failed else 0)  # freecadcmd swallows sys.exit()
