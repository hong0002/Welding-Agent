# B_PR fixture geometry audit — runtime remains blocked

Subsequent explicitly authorized actual-USDC audit verdict is
**B_PR_TOOL_CLEARANCE_FAIL**. Both previous candidates intersect the workpiece
and fixture table; registry remains disconnected. See
[actual-tool clearance audit](bpr-tool-clearance-audit.md). The following
sections preserve the earlier candidate investigation and its historical verdict.

2026-09-30 verdict: **B_PR_ROBOT_APPROACH_UNRESOLVED**. Ideal CAD contact geometry and rigid-transform candidates were computed offline. The robot-facing candidate has good seam residual and solves the nine predicted XYZ targets with the native numerical IK solver, but full tool clearance is not established. Neither candidate is an approved fixture policy.

An automatic approval review rejected the proposed B_PR registry/transform/approach/orientation integration because unverified policy could permit simulator playback. That patch was not applied. The safer completed change is an **offline diagnostic module only**: `backend/services/bpr_geometry_diagnostics.py`, with synthetic tests in `tests/test_bpr_geometry_diagnostics.py`. It is not imported by the simulator launcher, fixture probe or API. `runtime_approved` remains false, and no fixture registration, readiness override, package rewrite or queue action was added.

## Immutable inputs and diagnostic artifacts

- Sample: `B_PR_03_0001`.
- Guided VLA artifact: `f2bba528-fb2b-46a6-8c57-d0e1ba10211c`.
- Original package: `.cache/simulator/prediction-packages/f72c8af8-d291-4070-a6b5-d3ccf05170a9/package.json`.
- Package SHA256 before and after: `74ce06ee98ea5f26382a2965ac1811584c1d680fa7ba2e67126084cf46bffbf7`.
- NPZ SHA256 unchanged: `73e8e933a50a40a9f47a08494be77736fa94075c7820625e8249f9ccb36a2261`.
- Detailed audit: `.cache/bpr-geometry-audit/0efd49b0-a360-466e-b7f1-2fe5cdee0d2e/diagnostics.json`.
- Code/real-data comparison and GT point penetration addendum: the same directory's `validation_addendum.json`.
- Cross-section visual: the same directory's `contact_approach_diagnostic.png`.
- All 22 previously hashed external simulator code/asset files remain unchanged. `backend/services/bpr_fixture.py` was not created.

H5 and OBJ are the exact Butt/PR(Plate-Round)/03(3mm)/B_PR_03_0001 paths recorded in [guided-vla-simulator.md](guided-vla-simulator.md); no dataset enumeration was used. Comparison reads were limited to the exact L_PR_03_0001, T_PP_03_0001 and T_PR_03_0001 H5/OBJ files.

## B_PR geometry

All coordinates in this section are millimeters in their respective original file frames.

| Item | Observed value |
|---|---|
| Whole OBJ bounds | X [-25,25], Y [-125,25], Z [-50,50] |
| Tube body | 620 vertices, axis parallel to CAD Z, extent 100×50×50, radius about 22…25 |
| Plate body | 8 vertices, thin normal CAD X, extent 100×100×3; X [-1.5,1.5], Y [-125,-25], Z [-50,50] |
| H5 trajectory bounds | X [654.840026855,679.419982910], Y [-8.199999809,-5.519999981], Z [235.240005493,303.820007324] |
| H5 start | (654.840026855,-5.519999981,303.820007324) |
| H5 end | (679.419982910,-8.199999809,235.240005493) |
| H5 endpoint distance | 72.901119949 mm |
| Source direction | (+24.579956055,-2.679999828,-68.580001831), predominantly negative source Z |
| Raw source frame vs OBJ | Different numerical origins/axes; no stored robot-to-CAD calibration was found. Direct overlap is not assumed. |

The tube's CAD minimum Y=-25 tangent vertices lie at X≈0 and Z=-50,-16.666667,16.666667,50. The plate's end face is also Y=-25. Their finite common ideal contact line is:

```text
X=0, Y=-25, Z∈[-50,50]
anchor=(0,-25,0), canonical axis=(0,0,1)
contact gap=0 mm
```

This identifies the **ideal CAD tangent line**, not a certified prepared weld groove or an accessible nozzle contact. There are two plate broadside approach candidates (+X/-X). Both can register a straight GT trajectory to the same contact line with equal residual. Source XYZ and GT agreement alone cannot select a safe tool roll/approach.

## Existing native fixture policies

Native `build_scene` sets the common seam anchor to (0.85,0.15,0.50) m. Straight-joint source basis uses H5 endpoint direction and mean H5 TCP+Y; the T_PR circular policy uses the arc plane instead. Each matrix is calculated from its own query H5 and own CAD anchor, never borrowed between samples.

| Family/sample | CAD origin/geometry | Scene anchor and native CAD seam anchor | CAD rotation / object translation m | Initial scene TCP XYZ mm | Native tool outward |
|---|---|---|---|---|---|
| L_PR_03_0001 | Original file axes; bounds (-25,-50,-50)…(28,50,50); plate-face/round seam | World (.85,.15,.50); CAD (25,0,0) | I / (.825,.15,.50) | (850,150,462.003043) | (0,-1,0) |
| T_PP_03_0001 | Original file axes; bounds (150,-50,-1.5)…(250,50,101.5); two-plate intersection | World (.85,.15,.50); CAD (198.5,0,1.5) | I / (.6515,.15,.4985) | (850,124.969630,500) | (-1,0,1)/√2 |
| T_PR_03_0001 | Original bounds (-50,-50,-50)…(50,50,53); pipe-end circular joint | World (.85,.15,.50); rotated-CAD anchor (0,-50,-50) | diag(-1,1,-1) / (.85,.200000000627,.55) | (842.499998,154.742640,500) | (0,-1,1)/√2 |

Full native rotations, 4×4 `source_to_scene` matrices, initial XYZ/RPY and exact workpiece offsets are stored per family in `diagnostics.json.native_fixture_comparison`. The robot importer preserves the URDF root/base transform and adds no new base placement. Source-chain root is identity; actual imported USD/world pose was not measured because Isaac was not run.

Reusable logic is mesh/component analysis, orthonormal bases, one rigid transform, the existing workspace anchor, and fixed mounted CAD/tool reference construction. B_PR-specific geometry is the plate **end edge** tangent to an axial tube; L_PR's plate-face seam and T_PR's circular joint do not apply. No existing transform was copied.

## Candidate B_PR source_to_scene

The robot-facing **-X candidate**, not an approved/runtime matrix, is:

```text
[ 0.633551309 -0.730257573  0.255610280  0.353434705 ]
[-0.696369291 -0.682182104 -0.222929108  0.669975163 ]
[ 0.337168429 -0.036762121 -0.940726314  0.528366606 ]
[ 0           0           0           1           ]
```

Translation uses meters. Derivation:

1. Build source basis from H5 end-start direction and mean source TCP+Y, using the existing native `frame` algorithm.
2. Build a target basis from the CAD canonical tube axis and candidate plate broadside normal (-X or +X).
3. `R = target_basis @ source_basis.T`.
4. `t = native_fixture_center - R @ mean(H5_XYZ_m)`.
5. Preserve CAD axes. Candidate object offset is `native_fixture_center - CAD_contact_anchor_m = (.85,.175,.50)` m.

Both candidate matrices are finite proper rigid transforms (determinant≈1, orthogonality errors at machine precision). No scale distortion, point projection, per-point correction or prediction fitting was performed. GT ordered start/end become CAD axial positions approximately -36.450560/+36.450560 mm, preserving order while rotating the predominantly negative source-Z direction to positive canonical CAD Z. This is a declared visualization convention, not recovered robot/CAD calibration.

## Seam, prediction and penetration diagnostics

| Diagnostic | -X candidate |
|---|---|
| Transformed 150-point H5 GT distance to finite contact line, mean | 0.000014391520 mm |
| Maximum | 0.000031953908 mm |
| Start/end distance | about 0.000000388 mm each |
| Finite contact interval correspondence | GT covers [-36.450560,+36.450560] within CAD seam [-50,+50] |
| GT definite plate/tube interior points | 0/0 after excluding a source-float32 numerical boundary uncertainty band |
| Boundary uncertainty | about 0.000204738 mm, derived from source ULPs; **not a weld PASS threshold** |
| Physical weld acceptance threshold | None; distances are diagnostic |

The +X candidate gives effectively identical seam distances. Thus a tiny residual cannot establish the approach policy. GT point classification excludes the uncertain numerical boundary band and does not certify interpolated edges, nozzle collision or physical clearance.

Both 9-point `ground_truth_path_m` and `predicted_path_m` were transformed by each **same** candidate matrix for diagnostic comparison. N=9 stayed unchanged, and pointwise prediction-GT distances were invariant within floating-point roundoff. Source NPZ/package were not changed or replaced. Original server ADE=97.15410614013672 mm and FDE=155.03475952148438 mm remain unchanged.

## Robot/tool starting pose and unresolved approach

Native fixed-tool reference construction was evaluated as a diagnostic: mounted CAD/tip transform, candidate `fixture_outward`, world Z reference, mean transformed GT rotation, and fixed first GT tip orientation for XYZ-only prediction. This orientation is from the **simulator fixture policy candidate**, never from VLA.

| Candidate | Initial GT flange XYZ m | Native single-seed nine-point prediction IK | Tip-to-mount chord proxy |
|---|---|---|---|
| -X | (.416246257,.172138306,.457100086) | Position max 4.65e-13 mm; orientation max 2.94e-14°; joint step max 2.299781°, satisfies native numerical bounds | 58 sampled points inside tube shell; full nozzle mesh not tested |
| +X | (1.283753743,.127861694,.457100086) | Position max 19.197218 mm; orientation max 30.260081°, fails native numerical bounds for this seed | 34 sampled points inside plate; full nozzle mesh not tested |

The IK calculation imported only pure NumPy/SciPy kinematics routines and the URDF chain. It did not run any script main, output solution NPZ, queue, SimulationApp or hardware. It used the native prediction seed `[0,-30,100,-60,-90,0]` once per candidate; this was a bounded diagnostic, not a benchmark or a multi-seed search. The single-seed +X failure does not prove every possible IK seed fails.

The chord is only an approximation between the known CAD tip and mount, not the actual curved nozzle geometry. Its intersections are a warning that approach needs investigation, not a certified full-tool collision result. `ATU01035_welding_tool.usd` is a 247808-byte binary USDC asset. The audited native Python environment lacks `pxr` and `trimesh`; the existing ASCII scene references this binary asset rather than embedding its tool mesh. No Isaac Python/SDK launcher was used to decode it in this turn.

This evidence is insufficient for `B_PR_FIXTURE_OFFLINE_READY`. It must not be used to relabel `fixture_ready` or bypass the current gate.

## Verification and current API compatibility

The diagnostic module's candidate matrices match the independent read-only real-data audit to maximum element difference about 1.11e-16. Synthetic tests cover contact-line evidence, explicit gap reporting without readiness, both approach candidates, N=9/distance invariance, input immutability, and rejection of scaling/reflection/NaN/degenerate transforms. **290 backend tests passed**, with two existing UUID serializer warnings. `compileall` and `git diff --check` passed. Frontend/API runtime code was not changed in this turn.

Original package hash and all prediction bytes/metrics remain unchanged. Its stored fixture gate is still false. The existing current-VLA API continues accepting the artifact UUID and rejecting this B_PR run before queue admission. Package-UUID admission and B_PR registry integration remain unapplied; they must not be described as implemented.

An actual Isaac smoke command is **not currently admissible**. Running the external sample script directly would bypass the missing B_PR gate and still hit unsupported native fixture preparation. Do not provide a fallback to a different sample or invent a ready status.

Minimum next work is read-only extraction of the actual binary USD tool mesh with a verified USD reader, evaluation of the initial and interpolated tool mesh against the actual workpiece, and selection/validation of a fixture-specific approach/orientation only after that evidence. The configured Isaac Python may be used solely as an offline USD reader if explicitly approved separately; no SimulationApp, GUI, queue or model call is needed. Only after a valid policy exists should the blocked process-local registry extension and immutable package-bound fixture sidecar/API admission be reconsidered. Existing L_PR/T_PP/T_PR behavior must remain delegated unchanged.

Execution counts: Segment=0, Rough=0, trajectory2=0, Guided VLA=0, OpenAI=0, SSH retrieval=0, Isaac=0. Runtime/production fixture implementation is **incomplete**, and the final verdict is **B_PR_ROBOT_APPROACH_UNRESOLVED**.
