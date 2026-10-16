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
doc = new_doc("Dxf")
pb.make_blank(doc, 6)
ctl = doc.addObject("Sketcher::SketchObject", "Controls")  # a user's own cutout sketch
ctl.addGeometry(Part.Circle(App.Vector(-40, 0, 0), App.Vector(0, 0, 1), 4.8))
doc.recompute()
path = os.path.join(tempfile.mkdtemp(), "blank.dxf")
importDXF.export([doc.BlankOutline, doc.BlankHoles, ctl], path)
lines = [ln.strip() for ln in open(path).read().split("\n")]
entities = {}
for i, ln in enumerate(lines[:-1]):
    if ln in ("LINE", "CIRCLE") and lines[i - 1] == "0":
        j = i + 1
        while j < len(lines) - 1 and lines[j] != "0":
            if lines[j] == "8":
                entities.setdefault((ln, lines[j + 1]), 0)
                entities[(ln, lines[j + 1])] += 1
                break
            j += 2
check("DXF: outline = 4 LINE on layer BlankOutline", entities.get(("LINE", "BlankOutline")) == 4, entities)
check("DXF: holes = 4 CIRCLE on layer BlankHoles", entities.get(("CIRCLE", "BlankHoles")) == 4, entities)
check("DXF: user sketch on its own layer", entities.get(("CIRCLE", "Controls")) == 1, entities)
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
