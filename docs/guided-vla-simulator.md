# Guided VLA → simulator: offline contract and B_PR fixture gate

2026-09-30 verdict: **B_PR_FIXTURE_SUPPORT_REQUIRED**. The successful Guided VLA result can be read by the original prediction loader, but the native simulator has no B_PR fixture/contact-seam handler. No Segment, Rough, trajectory2, Guided VLA, OpenAI, SSH retrieval, Isaac, training or benchmark was executed in this work. All external repositories/data/assets remain read-only.

## Source artifact and package

- Source attempt: `866654a5-8cc7-4edc-82a8-0c276818aad8`, artifact UUID `f2bba528-fb2b-46a6-8c57-d0e1ba10211c`.
- Query/episode/fixture identity: `B_PR_03_0001`, split `train`. Retrieved reference identity is never used to select the simulator sample.
- Authoritative prior result: `GUIDED_VLA_LIVE_PASS`; this work reads its existing completion/response/metadata/NPZ and approval snapshots without calling the server again.
- New immutable package: `.cache/simulator/prediction-packages/f72c8af8-d291-4070-a6b5-d3ccf05170a9/package.json`.
- Audit: the same directory's `offline_audit.json`.
- Export: `predictions/B_PR_03_0001/trajectory.npz`, an exact byte copy, SHA256 `73e8e933a50a40a9f47a08494be77736fa94075c7820625e8249f9ccb36a2261`.
- Original NPZ/response/metadata, prior outputs and parity sessions were preserved. Earlier offline package UUIDs are retained; they are never overwritten.

`SimulatorPredictionPackage` is separate from image-pixel `FinalTrajectory`. It records artifact/attempt/sample UUIDs, source hashes, approved mask/job provenance, simulator source and asset hashes, original metrics, intended orientation policy, and fixture readiness. Browser summaries omit local paths and point arrays. `simulation_only=true`, `physical_robot_executable=false`, `is_robot_executable=false` are mandatory literals.

The exact simulator `metadata.json` contains only the four fields read by native `welding_prediction.py`:

```json
{
  "episode_id": "B_PR_03_0001",
  "coordinate_frame": "source_robot_frame_unaligned_with_isaac",
  "source_units": "mm",
  "scale_to_meters": 0.001
}
```

The frame is verified against the response before this metadata is generated; it is never relabeled. NPZ arrays already use meters. The loader checks metadata's original source scale; it does not multiply these arrays by 0.001 again. Extra provenance/metrics/flags belong in `package.json`, not fabricated native metadata fields.

## Exact bounded assets

H5:

```text
D:\용접로봇데이터\42.용접로봇 행동 생성 데이터\3.개방데이터\1.데이터\Other\Other\로봇티칭데이터\Butt\PR(Plate-Round)\03(3mm)\B_PR_03_0001\B_PR_03_0001.h5
```

OBJ:

```text
D:\용접로봇데이터\42.용접로봇 행동 생성 데이터\3.개방데이터\1.데이터\Other\Other\모델링 데이터\Butt\PR(Plate-Round)\03(3mm)\B_PR_03_0001\B_PR_03_0001.obj
```

H5 SHA256 `178297f6e8802a01f3dbd25d11ba88447f16322168e5bd2db967a5f286572855`; OBJ SHA256 `a4d724cbfe2c076da6443707ef9088acdb184278438abde32b20a3757b2053ab`. H5 has `trajectory (150,6)`, `joint_values (2,6)`, `original_points (2,6)`, and `interpolation_type`. There are no root frame/calibration attributes.

Existing robot/tool assets under `D:\Research_and_Paper\2026경남AISW경진대회\code\simulator` were checked: `rbpodo_description/robots/rb10_1300e_u.urdf`, all 14 visual/collision meshes referenced by that URDF, `ATU01035_welding_tool.usd`, and `welding_tool_geometry.py`. The package records hashes of 22 simulator code/asset files. The native preparation uses the RB10 URDF and mounted CAD/tool transforms. No robot or CAD asset was generated or renamed.

## Frame and N=9 verification

Both arrays are finite float32 `(9,3)`. They exactly match the response's XYZ mm arrays converted using the existing Guided VLA float32 export rule. Prediction and GT remain distinct. Native loader `prediction_index` and `prediction_targets` were executed **only as pure numpy/json offline utilities**, with an identity transform solely to test the loader contract. That identity is not a B_PR scene placement or a calibration.

Native GT validation linearly resamples query H5 XYZ by row index to the exported GT length, converts mm→m, and rejects maximum Euclidean error above 0.05 mm. Measured maximum error is **0.0000536488234215 mm**, comfortably inside that bound. The source start norm is about 721.909 mm, and response GT matches that nonzero query source start. This is absolute H5 source XYZ, rather than a start-relative/recentered path. Direct matching needs no XYZ permutation, sign flip, start subtraction, fitted translation or corrective alignment.

This proves numeric agreement at the checked GT waypoints with this H5/source convention. Prediction shares the declared response/export convention; GT agreement does not prove prediction accuracy, camera calibration, CAD registration, real robot origin/handedness, or physical safety. The server used `ground_truth_h5_first_point` as its start input; this oracle condition is preserved in provenance.

The loader comment mentions 33 waypoints, but its actual validation accepts finite `(N>=2,3)` arrays and resamples H5 to `len(gt)`. Its returned target pose count was **9**. Native sample preparation and interpolation loop use `len(q)`; there is no hard 33-point requirement. The adapter never resamples the prediction to 33. Mounted-tool IK/Kit playback at N=9 has not been exercised.

## B_PR fixture blocker and reuse

The actual `welding_scene_layout.py` allowlist is `L_PR_`, `T_PP_`, `T_PR_`. `object_seam` explicitly rejects B_PR, and no B_PR placement/approach policy exists. Assets are present; fixture logic is missing.

The OBJ has 628 vertices/1252 faces and two disconnected bodies: a round body with PCA extents about 100×50×50 mm, and a plate about 100×100×3 mm. Its plate spans Y=-125…-25 mm and its round body Y=-25…25 mm. These bounds support an edge-contact interpretation of this Butt geometry; this is a geometry inference, not a certified weld seam or source-to-CAD calibration.

| Native family | Native policy | Reuse for B_PR |
|---|---|---|
| L_PR | Plate-face/round contact heuristic; axial seam; CAD axes preserved | Closest body types. Mesh loading, component analysis and rigid-transform framework are reusable. Its plate-face seam/contact normal are unsuitable for this plate-edge Butt geometry. |
| T_PP | Two plates; vertical plate/base intersection | Rigid placement infrastructure only; no corresponding round/contact geometry. |
| T_PR | Plate below pipe; pipe-end circular joint and specific outward vector | Rigid placement infrastructure only; circular joint is different from B_PR's observed axial edge contact. |

No L_PR policy was relabeled as B_PR. No B_PR anchor, outward vector, tool roll or fixture matrix was invented. `source_to_scene=null`, `fixture_ready=false`, `orientation_available=false` in this package.

For supported native fixtures, `build_scene` creates one GT-derived rigid transform with a fixture center at (0.85,0.15,0.50) meters. `prediction_targets` applies the **same** rotation and translation to prediction and GT. This is an explicit visualization fixture relocation, not recovered world calibration. Its algebra can be reused after a verified B_PR seam/approach policy establishes the missing target basis/anchor. A transform from a different sample must never be copied.

## Accuracy and orientation

Original server ADE **97.1541061401 mm**, FDE **155.0347595215 mm** are retained in the package and current-run status. Poor accuracy does not itself block simulation visualization. Physical execution stays disabled.

The original loader computes ADE excluding the first waypoint, giving **100.7848909166 mm** in the offline probe; its FDE is **155.0347629947 mm** after float32 export. These are labeled separately in the audit; they do not replace the server metrics. No error-minimizing transform was fitted.

Guided VLA predicts XYZ only. Native `prediction_targets` copies the initial fixture pose orientation to all prediction waypoints. Native preparation derives its fixed flange/tool reference from the fixture and mounted CAD policy, rather than VLA. The package explicitly records `orientation_policy=fixed_initial_fixture_pose` and `orientation_source=simulator_fixture_tool_policy; not VLA`. These describe the existing intended simulator policy; they do not declare a B_PR orientation available. That remains blocked with the fixture.

## Backend interfaces and admission

Implemented in `backend/services/simulator_prediction_package.py`, injected through `create_app(current_vla_simulator=...)`. Native geometry inspection uses the already audited `C:\Users\hong_\anaconda3\envs\py3_12\python.exe` (numpy/scipy/h5py) and a fixed **Welding-Agent-owned** helper. It never invokes the Isaac launcher, sample script, IK or SimulationApp. Bytecode writes are disabled and credential variables are removed from that child's environment.

The two new endpoints accept only `{"artifact_id":"<UUID>"}`, reject extra fields/query parameters and reuse the explicit origin guard:

- `POST /api/simulator/current-vla/preflight`: resolve exactly one completed backend-owned attempt; verify completion hashes, response/NPZ/metadata, query identity, current source job/mask hashes and approval, exact dataset H5/OBJ paths, robot/tool assets, fixture readiness; create a fresh package and return a bounded summary. No simulation starts.
- `POST /api/simulator/run-current-vla`: repeat admission, reject a failed fixture gate with HTTP 409, then call the separate `run_current_vla_prediction(package)` boundary only if preflight passes and the owned simulator is already READY. It never starts Isaac automatically.

Existing empty-body `/api/simulator/run-sample` still replays `WELD_SIM_SAMPLE_ID`. Current playback instead uses the exact package sample and prediction directory; no fallback to the configured/retrieved sample or GT is permitted. The current path uses `--samples-dir` at the exact query H5 directory to keep enumeration bounded and retains native sibling-OBJ discovery. Backend-owned paths/arguments travel via the existing shell=False launch manifest and ownership gate.

Before an owned sample child executes external code, a stdlib-only gate rechecks the admitted package hash, source/output NPZ and metadata, original VLA completion/input manifest, approved job/mask, H5/OBJ, and audited simulator source/assets. Current completion must identify the admitted sample/H5/prediction directory, N=9 and `mounted_fixture_v2`, in addition to existing exit=0/result=done/output checks. Existing Job Object cleanup/lease/queue isolation are retained. This is a local single-backend-process design.

No Agent tool invokes this new action. Image-pixel Workflow validation never selects a spatial artifact or starts simulation; no frontend current-plan button or layout redesign was added. The client must explicitly select the spatial Guided VLA artifact UUID through this API.

## Verification and next gate

Offline fake tests cover immutable byte-copy, four-field metadata, original accuracy/physical flags, reference-vs-query identity, 9 points in supported fixture families, hash/units/frame/GT/shape/approval rejection, UUID/path/origin rejection, B_PR no-launch behavior, and stubbed current-sample admission/completion independent of configured replay. Full backend suite: **281 passed** (two existing UUID serializer warnings); focused simulator suite after admission updates: **64 passed**. `compileall` passed.

TypeScript checking passed. Standard frontend build and Playwright server startup hit an existing `node_modules/.vite-temp` EPERM. Vite `--configLoader runner` production build succeeded to `.cache/frontend-build/current-vla-f72c8af8`. E2E did not complete; no frontend code changed.

Reproducible **offline-only** audit command:

```powershell
.\.venv\Scripts\python.exe -B -X utf8 -m backend.simulator_prediction_preflight --artifact-id f2bba528-fb2b-46a6-8c57-d0e1ba10211c
```

Minimum next work is to establish a verified B_PR edge-contact seam/anchor, target basis/outward and mounted-tool orientation policy from the real CAD/query data, implemented only in Welding-Agent or supplied as an explicit verified native contract. Preserve native supported-family behavior, one identical rigid transform, untouched prediction and reported CAD/GT seam residuals. Repeat the offline fixture/transform gate, then decide a separate explicitly authorized one-artifact Isaac smoke with fresh mounted-tool IK/queue/output. No Isaac command is recommended while `fixture_ready=false`.
