# B_PR actual-tool offline clearance audit

2026-09-30 verdict: **B_PR_TOOL_CLEARANCE_FAIL**. Both exact previous diagnostic
placement/orientation candidates intersect the actual workpiece and table.
`runtime_approved=false`, `registry_connected=false`, package
`preflight.fixture_ready=false`. No registry/API/launcher changes were made.
This verdict concerns these candidates, not every possible future B_PR design.

Audit UUID: `a74cb77c-7d4e-4617-b20d-57a43fcb89cf`.
Outputs under `.cache/bpr-tool-clearance/<UUID>/` are `summary.json` (verdict,
hashes, limits), `usd_geometry.json` (actual composed triangle data/hierarchy),
`clearance.json`, `candidate_-1.json`, `candidate_1.json` (closest points and
triangle IDs), `table_containment.json`, `robot_collision.json`, and
`tool_clearance.png`. Previous output directories were preserved.

## Reader and mesh

Tool: `D:\Research_and_Paper\2026경남AISW경진대회\code\simulator\ATU01035_welding_tool.usd`.
Binary USDC SHA256:
`385f7b1a8477f1f1d0a3165733156a33dd1039197e62e602a569e75908324e90`.

Reader: `D:\isaacsim\kit\python\python.exe`, Python 3.12, USD 0.25.11.
Operator-only `backend/offline_usd_tool_reader.py` ran with `-I -S -B -X utf8`
and directly loaded the installed USD libraries. It bypassed `python.bat`,
`sitecustomize`, and app/extension initialization. No `isaacsim`/`omni` modules,
SimulationApp, GUI, physics, queue or stage playback were used; no layer was
saved/exported. Subsequent CPU geometry used
`C:\Users\hong_\anaconda3\envs\py3_12\python.exe` with bytecode writes disabled.

Default prim: `/tn__STEPATU01035_ab0X0`. Nested instance/proxy Xforms lead to
`/tn__STEPATU01035_ab0X0/tn__STEPATU01035_ab0X0/tn__1_zxOJQg4/Mesh`.
All four composed transforms are identity. Default traversal omits this
instanced mesh, so the reader includes instance proxies. The only file layer
is the original tool asset. Geometry: **6,979 vertices, 8,435 triangles**, no
holes/time samples, subdivision `none`. Origin=(0,0,0), up=Z,
meters-per-unit=0.001. Native `add_torch_at_tcp` applies one explicit 0.001
Geometry scale; the audit applies it exactly once, followed by native mounted
CAD and previous flange transforms.

| Actual CAD-local geometry | mm |
|---|---|
| Minimum XYZ | (-37.998977661, -45, -8.399999619) |
| Maximum XYZ | (38, 161.996200562, 425.934204102) |
| Native mount center | (0, 0, -8.4) |
| Actual rear mount-ring X/Y range | ±22.802570343 |
| Native tip reference | (0.140769460, 20.398856299, 425.486938477) |
| Tip to nearest actual surface | 0.361210963 |

Tip definition is existing `welding_tool_geometry.CAD_TIP_LOCAL_MM`, not a USD
semantic marker or newly inferred calibration. Maximum mesh Z is 0.447265625 mm
higher. Nearest surface point is (0.115462239,20.361552900,425.845325643) mm,
triangle 753. These differences did not change the tip/path.
Full-mesh vertex PCA axis is (0.003150672,0.116157342,0.993225828).
Distal-region PCA (`CAD Z > 400 mm`, diagnostic only) is
(-0.000000023,-0.655523275,0.755174971). The curved torch has no single
whole-body approach axis; PCA does not select a new policy.

## Exact previous convention and orientation

Both `source_to_scene` and initial flange candidates come from immutable prior
audit `0efd49b0-a360-466e-b7f1-2fe5cdee0d2e/diagnostics.json`. OBJ axes are
preserved with translation (.85,.175,.50) m; workpiece bounds are
(.825,.05,.45) to (.875,.20,.55) m. Both indexed workpiece components are
closed consistently oriented 2-manifolds. Their hashes match the prior audit.

World tool points use
`flange_R @ (native_cad_R @ (asset_points_mm*.001) + native_cad_t) + flange_t`.
Native mounting maps CAD+Z to flange-Y with translation (0,-.0084,0) m;
tip translation in flange is (.000140769,-.433886938,.020398856) m.

`orientation_source = simulator_fixture_policy`, never VLA. The existing
formula uses candidate outward, world-Z flange reference, mean transformed H5
orientation, and fixed first transformed H5 tip orientation for XYZ-only
prediction. Recalculation reproduces previous rotations to <1e-12. GT and
prediction use this same fixed flange rotation for comparison.
-X initial flange XYZ is (.416246257,.172138306,.457100086) m; world CAD+Z
is (.998187723,-.050883513,-.032126893), and distal nozzle axis is
(.733049410,-.031960526,-.679424085). +X initial flange XYZ is
(1.283753743,.127861694,.457100086) m; those axis X/Y signs reverse.

## Intersections and clearances

The offline AABB-tree solver checks planar triangle vertex/face, edge/edge and
edge/face distances, including coplanar/transverse crossings. Distances are
unsigned; an intersection has minimum zero. Counts are triangle pairs, not
separate collision events. Closed-solid winding and nearest surfaces separately
verify tool vertices inside workpiece bodies. The maximum reported depth is
among tested vertices, not a global solid-overlap depth.

No physical tool-clearance tolerance exists in the inspected source. Native
1.5/3 mm `contact_tolerance_mm` selects L_PR contact vertices; it is not reused
as clearance. Neither 1 mm/1° tracking nor 0.05 mm GT/H5 checks are clearance
thresholds. Only machine-scale numerical equality (~1.1e-13 m) is used;
`physical_clearance_threshold_m=null`.

| Initial GT / seam-start | -X | +X |
|---|---:|---:|
| Tool/workpiece surface minimum | 0 mm | 0 mm |
| Intersecting triangle pairs | 412 | 366 |
| Tool vertices inside tube | 55 | 50 |
| Deepest tested tube vertex | 1.488448 mm | 1.495994 mm |
| Tool vertices inside plate | 21 | 28 |
| Deepest tested plate vertex | 1.460696 mm | 1.487203 mm |
| Tool/table intersecting pairs | 31 | 31 |
| Vertices inside table | 16 | 16 |
| Deepest tested table vertex | 1.129319 mm | 1.129319 mm |
| Tool/ground minimum | 411.161416 mm | 411.161416 mm |
| Tool/table-leg minimum | 122.510560 mm | 120.324924 mm |

One -X crossing is world (.836275674,.154126238,.450000000) m, tool triangle
554/workpiece triangle 54. Tube vertex 1113 is inside at
(.847325459,.151660301,.452389126) m; nearest surface is
(.847150512,.150182170,.452389126) m. Plate vertex 513 is inside at
(.849960696,.146658262,.463543998) m; nearest surface has X=.8485 m, same Y/Z.
Full-precision closest points are saved in the JSON reports.

Table/legs/ground follow exact source cube definitions
(`run_rb10_trajectory_with_ATU01035.py:494-511`), without creating a stage.
Table bounds are (.700000000,.024044586,.410000000) to
(1.000000000,.324044586,.450000000) m.

No native B_PR pre-approach length exists. The following offsets along the
previous outward direction are **diagnostic samples**, not a new launch policy.

| Offset | -X distance / intersecting pairs | +X distance / intersecting pairs |
|---|---:|---:|
| 50 mm | 29.0868 mm / 0 | 29.5304 mm / 0 |
| 20 mm | 2.6375 mm / 0 | 3.2509 mm / 0 |
| 10 mm | 0 mm / 130 | 0 mm / 115 |
| 5 mm | 0 mm / 255 | 0 mm / 238 |
| 2 mm | 0 mm / 297 | 0 mm / 269 |
| 1 mm | 0 mm / 341 | 0 mm / 322 |
| 0 mm | 0 mm / 412 | 0 mm / 366 |

GT: **9/9 poses intersect for both candidates**, surface minimum 0 mm;
-X 410–424 pairs/pose, +X 358–368. Failure witnesses do not require a full
continuous-path certificate; this audit does not claim continuous coverage.

## Prediction and robot diagnostics

Original prediction N=9 uses each **same rigid transform**, without fitting,
correction, projection or GT substitution. -X intersects at 6/9 poses, +X at
8/9; each path's sampled minimum is 0 mm. -X final three distances are
7.466822,19.339601,35.223449 mm; +X final distance is 10.437793 mm.
Prediction endpoint table distances are 12.642399 and 21.367551 mm, with no
endpoint table/leg/ground crossings. Intermediate fixture clearance is not
certified. Original **ADE=97.15410614013672 mm,
FDE=155.03475952148438 mm** and pointwise error distances remain unchanged.

Robot check uses one initial reachable -X GT pose, pure native URDF kinematics,
one native prediction seed, and all seven actual collision STL meshes, with
the previously audited identity base assumption. Position error is 1.27e-13 mm,
orientation error 1.59e-15°. No physics/controller/imported USD robot stage ran.

| Link | Tool distance mm | Intersecting pairs |
|---|---:|---:|
| link0 | 490.972102 | 0 |
| link1 | 391.248843 | 0 |
| link2 | 305.527119 | 0 |
| link3 | 154.638561 | 0 |
| link4 | 75.988622 | 0 |
| link5 | 42.999998 | 0 |
| attached mount link6 | 0 | 224 |

Link6 examples lie at the mount interface (flange-Y approximately 0 to
-.2464 mm). Contact/overlap acceptance is **unresolved**; there is no specified
tolerance establishing an intentional safe contact. One-pose non-mount
separation does not certify full robot self-collision or motion clearance.

## Preservation and verification

Package `f72c8af8-d291-4070-a6b5-d3ccf05170a9` SHA256 remains
`74ce06ee98ea5f26382a2965ac1811584c1d680fa7ba2e67126084cf46bffbf7`.
NPZ SHA256 remains
`73e8e933a50a40a9f47a08494be77736fa94075c7820625e8249f9ccb36a2261`.
Tool, H5, OBJ, prior diagnostics, package assets and robot collision STL hashes
were rechecked after calculation and are unchanged. New files are inside
Welding-Agent; the operator-only audit modules have no runtime imports/gates.

11 new synthetic CPU geometry tests cover analytic distances/crossings,
degeneracy, symmetry, AABB pruning, rigid translation, winding and bad input.
**301 backend tests passed**, with two pre-existing UUID serializer warnings;
`compileall` and `git diff --check` passed. Tests never invoke the real USD
reader, Isaac or API models. Frontend/runtime behavior did not change.

Counts: Segment=0, Rough=0, trajectory2=0, VLA=0, OpenAI=0, SSH retrieval=0,
SimulationApp=0, Isaac GUI=0, physics=0, queue=0, existing simulator sample=0.
Only the explicitly authorized isolated offline USD reader and local CPU
geometry ran.

The remaining issue is a B_PR mount/tip/approach/orientation and fixture design
that avoids these measured intersections. This audit does not select a
replacement policy or alter prediction accuracy. Registry connection is
prohibited by the failed clearance result.
