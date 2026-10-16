# Cockpit Panels

A FreeCAD workbench for building home-cockpit (simpit) panels. It starts with one tool, **Panel Blank**, and is built so more tools can be added.

**Panel Blank** draws the base for a Dzus-rail console panel: the outline, a mount point at every fastener position on the rail grid, and a clearance hole at each one. You model your control cutouts on top of it, then export the lot to DXF for the laser cutter or pad it into a 3D-printed plate.

Everything it creates is a plain FreeCAD object (a spreadsheet and three sketches). Your panel files open and recompute on any FreeCAD 1.1+, with or without this workbench installed.

## The panel grid

Classic US military side-console panels follow one standard:

| | Value |
|---|---|
| Width | 146.05 mm (5¾″) |
| Height | N × 9.525 mm (N × ⅜″), N ≥ 4 |
| Fastener columns | half a pitch in from each side edge, 136.525 mm (5⅜″) apart |
| Outer fastener rows | 1.5 pitch in from the top and bottom edges |
| Extra rows | any half-unit row between the outer ones (2.5, 3.5, …) |

Because every panel sits on the same grid, stacked panels keep 28.575 mm (3 pitches) between fastener rows across the joint, the same as within a panel.

## Install

**Addon Manager (recommended)**

1. Tools → Addon Manager → ⚙ (Preferences) → **Custom repositories** → add
   `https://github.com/OpenSkyHawk/CockpitPanels` with branch `main`.
2. Find **Cockpit Panels** in the list and install it. Restart FreeCAD.

Updates arrive through the Addon Manager like any other addon.

**From a clone (for development)**

Link the clone into FreeCAD's `Mod` folder, then restart FreeCAD. Edits take effect on the next restart.

```bash
ln -s "$PWD" "$HOME/Library/Application Support/FreeCAD/v1-1/Mod/CockpitPanels"   # macOS
ln -s "$PWD" "$HOME/.local/share/FreeCAD/v1-1/Mod/CockpitPanels"                 # Linux
```

On Windows the folder is `%APPDATA%\FreeCAD\v1-1\Mod`. To see yours, run `App.getUserAppDataDir()` in FreeCAD's Python console and add `Mod`.

## Use

The **Panel Blank** button is on the **Cockpit Panels** toolbar, and also on the Sketcher and Part Design toolbars so you don't have to switch workbench.

1. Open your panel document (or start a new one) and click **Panel Blank**.
2. Enter the height in units (N), or type a measured height and let it round to the nearest N. Set the width if your panel isn't 5¾″, any extra fastener rows, and the fastener.
3. Click OK. A **Panel Blank** group appears, centred on the origin on the XY plane:

| Object | What it is |
|---|---|
| `PanelBlank` | Spreadsheet: `units`, `pitch`, `width`, `fastener`, `hole_dia`, one `row_eN` per extra row |
| `BlankOutline` | The panel rectangle |
| `BlankMountPoints` | One point per fastener: the datum for your layer bodies |
| `BlankHoles` | One clearance circle per fastener (empty for "None") |

**Changing it later:** edit a cell in `PanelBlank` and recompute, and everything moves. To add or remove extra rows, click **Panel Blank** again: it opens pre-filled and updates the same objects in place, so anything linked to them keeps working.

### Fasteners

| Preset | Hole Ø | Head Ø |
|---|---|---|
| M5 socket cap (default) | 5.6 | 8.5 |
| M5 self-tap (printed) | 4.7 | 8.5 |
| M4 socket cap | 4.5 | 7.0 |
| M6 socket cap | 6.6 | 10.0 |
| Dzus stud | 6.6 | 9.53 |
| None (points only) | — | — |

The hole Ø is editable. Heads wider than the 9.525 mm pitch (every M6) hang over the side edge and collide on rows one pitch apart; the dialog warns about this. The head size only drives the warning, no head geometry is drawn.

## Workflows

**Laser-cut plate:** draw your control cutouts in your own sketch on the XY plane, positioned from the origin (the panel centre). Use numbers or `PanelBlank` cell references rather than External Geometry, which breaks when objects move between files. Select `BlankOutline`, `BlankHoles` and your sketch, then File → Export → DXF: each sketch lands on its own layer, named after the sketch. Use `BlankHoles`, not the points, for the cut file: sketch points don't export to DXF.

**Plate bodies (printed or layered):** keep the blank outside your Part Design bodies and bring it in with a **SubShapeBinder** in each body, then Pad the outline binder. To drill the fastener holes, put a **Hole** on a binder of `BlankMountPoints`.

> **Gotcha:** with the plate's front face at z = 0 and the material going +z, the Hole must have **Reversed** ticked. Without it the Hole recomputes "up to date" and cuts nothing, with no error.

## Tests

Headless checks, run with FreeCAD's command-line binary (not its bundled `python`, which crashes on `import Part`):

```bash
/Applications/FreeCAD.app/Contents/Resources/bin/freecadcmd tests/check_panel_blank.py
```

It prints one PASS/FAIL line per check and exits non-zero on any failure.

## License

LGPL-2.1-or-later, the same as FreeCAD. See [LICENSE](LICENSE).

Part of the [OpenSkyhawk](https://github.com/OpenSkyHawk/OpenSkyhawk) A-4E home-cockpit project, but not tied to it: the panel grid is common to many aircraft.
