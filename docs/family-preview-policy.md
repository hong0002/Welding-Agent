# Current VLA family diagnostic preview

Verdicts: **FAMILY_PREVIEW_REGISTRY_READY**, **B_PP_CURRENT_VLA_PATH_PREVIEW_READY**.
B_PP robot/workpiece placement is pending. This is offline readiness, not a live
Isaac pass or physical safety validation. All current previews keep
`simulation_only=true`, `fixture_ready=false`, `validated_simulation=false` and
`physical_robot_executable=false`. Existing sample replay remains independent.

## Existing code audit

| Component | Dependency | Result |
|---|---|---|
| Current VLA proof/approval/image/guidance binding, immutable NPZ | A: sample independent | Reused current artifact verification |
| H5/OBJ resolver | B: family directory + C: exact sample | Explicit naming resolver, no dataset search |
| Old `CurrentVLAPreviewService.prepare` exact geometry/clearance hashes | C: exact sample | Moved into `BprPreviewPolicy` |
| Old `current_preview_config.configuration` B_PR ID/evidence check | C: exact sample | Removed from global runtime; retained per requested B_PR policy |
| Old `current_preview_gate` mandatory B_PR warning/geometry paths | C: exact sample | v1 remains strict; v2 binds policy, asset hashes and owned renderer code |
| Renderer workpiece/table, source-to-scene, flange rotation, RB10 root | B/C: family and sample placement | Reads policy descriptor; neutral Path mode has no workpiece/robot/table |
| Renderer B_PR labels | B: policy provenance | Displays admitted warning/orientation source |
| `simulator_prediction_package` B_PR fixture-blocked verdict | Validated replay gate | Kept unchanged, never promoted |
| Runtime ownership, fixed launcher, queue, no physics | A: sample independent | Reused; no Isaac launched during this work |

B_PR audit defaults remain in `current_preview_config.py`. Previously audited
robot placement still requires the exact B_PR sample ID/H5/OBJ hashes and the
unchanged `B_PR_TOOL_CLEARANCE_FAIL`, `registry_connected=false` evidence.
Another sample cannot borrow that placement. Explicit Path mode may display a
different registered B_PR sample in its source frame; robot requests never
automatically fall back to Path.

The child gate previously omitted `native_output` from its conditioning hash,
although `guided_workflow.conditioning_hash` includes that field. It now uses
the same payload and rejects subsequent native-output changes.

## Resolver and policy contract

`dataset_sample.resolve_sample` requires the full canonical ID:
`[B|L|T]_[PP|PR|PS|RR|RS|SS]_<two digit thickness>_<four digit index>`.
Thickness/index must be nonzero. Joint directories are `Butt`, `Lap`, `Tee`.
Actual pairing directory names were confirmed by bounded directory listings of
`Other/Other/로봇티칭데이터`; no recursive dataset scan was performed.
H5/OBJ each use their exact sample basename and
`<thickness>(<integer thickness>mm)/<sample_id>` hierarchy. No symlink, family
substitute, reference sample or search fallback is admitted.

`PreviewPolicy` supplies family/path/robot capability, `resolve_h5`, `resolve_obj`,
`validate_sample_assets`, and `derive_or_resolve_source_to_scene`. Resolved policy
contains workpiece/base placement, tool orientation, warnings and provenance.
`PreviewPolicyRegistry` rejects duplicate registrations and resolves by family.

| Family | Path | Robot | Placement |
|---|---|---|---|
| B_PR | Exact own assets | Previously audited exact sample only | Existing audited candidate, clearance FAIL retained |
| B_PP | Exact own assets | Pending | Neutral source frame, no workpiece |
| L_PR | Exact own assets | Pending for current preview | Neutral source frame |
| T_PR | Exact own assets | Pending for current preview | Neutral source frame |
| T_PP | Exact own assets | Pending for current preview | Neutral source frame |

Unknown/malformed IDs and canonical families without a registered policy are
explicitly blocked with `PREVIEW_FAMILY_UNSUPPORTED`. Family capability never
implies equal geometry or equal transforms across samples.

## Actual B_PP preflight

| Item | Verified result |
|---|---|
| Job | `9256ee42-ea9c-41fa-8a63-a8ac98be195a` |
| Artifact | `5450d82a-e927-434e-b365-4ddb11b74850` |
| Attempt | `e968a420-7316-4325-9ce9-84d972e87290` |
| Sample / split | `B_PP_03_0001` / `train`, from bound current job and response |
| H5 | `D:\용접로봇데이터\42.용접로봇 행동 생성 데이터\3.개방데이터\1.데이터\Other\Other\로봇티칭데이터\Butt\PP(Plate-Plate)\03(3mm)\B_PP_03_0001\B_PP_03_0001.h5` |
| OBJ | `D:\용접로봇데이터\42.용접로봇 행동 생성 데이터\3.개방데이터\1.데이터\Other\Other\모델링 데이터\Butt\PP(Plate-Plate)\03(3mm)\B_PP_03_0001\B_PP_03_0001.obj` |
| H5 SHA256 | `555ea5f9713ec7c92faab990be449ad3837bec04db08a3702bb683df549da603` |
| OBJ SHA256 | `315da0bca15c0aaa0fe1323e1dd73429ed00c4adf9c979be7fb85eb0a1fa7740` |
| H5 trajectory | `(150,6)`, XYZ mm per original export contract |
| OBJ bounds | `(-50,-50,-1.5)` to `(150,50,1.5)` mm; 16 vertices |
| Prediction | Nine float32 XYZ points, meter NPZ; exact sample identity |
| GT-H5 maximum error | `0.00007040456633534796 mm`, PASS against existing `0.05 mm` limit |
| Coordinate frame | `source_robot_frame_unaligned_with_isaac` |
| Workpiece/robot transform | **C: unresolved** |
| ADE / FDE | `38.28097915649414 / 51.84674835205078 mm`, unchanged |
| Path / robot / workpiece | Ready / Pending / Pending |

H5 has no unit/calibration attributes. Direct GT consistency verifies the export
frame/unit contract, not CAD-to-robot registration. Neutral display uses identity
only to preserve source XYZ; it is not a B_PP fixture transform. B_PR's matrix was
not copied. Prediction is neither fitted, translated, resampled nor substituted.
Only H5 GT is index-linearly resampled for the original consistency check.

Actual immutable package, claim and preserved source hashes are recorded in
`.cache/family-preview-audit/5213a1f7-00f3-4f8e-aaad-64040a0da10e/report.json`.
NPZ is byte-identical and all nine prediction coordinates are unchanged. Current
job, mask, VLA attempt and original B_PR audit files were preserved. Path packages
use `current-vla-path-package-v1`, `orientation_policy=none_xyz_only`,
`current_preview_only=true`, `fixture_ready=false` and cannot pass the existing
validated replay gate. Orientation is `simulator_preview_policy`, never VLA output;
neutral mode has no robot orientation. `vla_orientation=false` always remains.

## Existing L_PR/T_PP/T_PR logic

Read-only `simulator/welding_scene_layout.py` supports `L_PR_`, `T_PP_`, `T_PR_`.
`build_scene` computes each query's own CAD seam and H5 source basis, with common
diagnostic anchor `(0.85,0.15,0.50)` m. L_PR uses plate/round seam geometry; T_PP
uses two plate components; T_PR uses upright pipe/plate circular geometry.
H5 direction/TCP rotations and the exact CAD anchor determine a per-query rigid
transform. Existing URDF chain root is identity; mounted CAD/tip helpers supply
tool geometry. These are diagnostic fixture conventions, not physical calibration.

Shared utilities are exact asset mapping, OBJ/DAE/STL readers, rigid-transform and
GT checks, and runtime ownership. External fixture/playback code was not modified.
Its existing replay contract remains strict. New current robot policies require
separate audited sample geometry and orientation evidence before registration.

## API, UI and future family registration

Read-only `GET /api/simulator/current-vla/capabilities?job_id=<UUID>` verifies the
current artifact and own assets, returning family/sample and distinct Path/Robot
readiness. It creates no package and launches no subprocess. Browser capability
responses contain no asset paths, matrices, full hashes or point arrays.

POST endpoints remain `/api/simulator/preview-current-vla/path` and
`/api/simulator/preview-current-vla` (robot). Bodies accept exactly one job/artifact
UUID, no family/path/matrix/command overrides. The backend resolves job, current
artifact, family, policy, exact assets and requested mode before launcher admission.
There is no automatic retry or mode fallback.

`current_preview.configured` now describes the neutral Path runtime;
`robot_configuration` separately checks robot assets. Sample policy evidence is
checked per request. Existing replay configuration remains independent and strict.
Simulator UI shows sample/family, Path Preview Ready and Robot Preview Pending for
B_PP. Its path button is enabled, robot button disabled, validated execution blocked.

Safe codes: `PREVIEW_FAMILY_UNSUPPORTED`, `PREVIEW_SAMPLE_ASSET_MISSING`,
`PREVIEW_H5_MISMATCH`, `PREVIEW_OBJ_MISSING`, `PREVIEW_PATH_SUPPORTED_ROBOT_PENDING`,
`PREVIEW_POLICY_NOT_READY`, plus existing typed runtime/artifact errors.

To add a family, implement the policy and register it in `default_registry`.
Main admission/renderer has no sample-specific if/elif selection. Asset validation
must remain exact; scene/orientation evidence belongs to the policy. Robot support
does not promote physical fixture readiness.

Actual Isaac rendering/captures require a separate explicit user launch after
backend restart and restoration of the same VLA_READY job. This work performed
zero Segment2, Trajectory3, Guided VLA, OpenAI, SSH, Simulator or Isaac calls.

Offline verification: full pytest **455 PASS**; final focused policy/current preview/
immutable package regression **72 PASS**; full Playwright **32 PASS** using installed
Chrome and the fake app; frontend build, backend compileall and whitespace checks PASS.
The existing approval browser test uses a fixed offline status snapshot to avoid a
polling `route.fetch` response racing page teardown. No production behavior changed
for that test fixture repair.
