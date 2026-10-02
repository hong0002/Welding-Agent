# Dataset Simulator v2 integration audit — 2026-10-01

판정: **SIMULATOR2_ADAPTER_READY + SIMULATOR2_FAMILY_LIMITED**.
기본 backend/root `.env`는 legacy를 유지했다. 실제 GUI/physics 검증은 하지 않았다.

## 1. 실제 목적

simulator2는 exact sample H5 teaching XYZ와 OBJ로 simulation fixture를 구성하고 VLA XYZ를 동일 scene에 배치하여
RB10/ATU01035 native IK/playback solution을 만든다. Camera/robot calibration이나 collision/physical safety 인증은 아니다.
이번 Segment2/Trajectory3/Guided VLA/OpenAI/SSH retrieval/SimulationApp/Isaac GUI/physics 호출은 **각각 0회**다.
외부 simulator/simulator2/Isaac, dataset, 기존 output은 수정하지 않았다.

## 2. Entry point와 call chain

외부 source: `D:/Research_and_Paper/2026경남AISW경진대회/code/simulator2`.
`run_welding_sample.py → open_samples/ExtractedSamples → sample_index → prepare`.
prepare는 H5 trajectory/joint_values/original_points, exact OBJ, build_scene, prediction_targets,
native orientation, densify_poses, solve_mounted_path 및 FK/interpolation residual을 검사하고 solution/report를 저장한다.

GUI는 `run_welding_simulator.py → run_rb10_trajectory_with_ATU01035.py --serve → SimulationApp → serve → process_next → main`이다.
주요 CLI: `--sample`, `--samples-dir|--zip|--data-root`, `--prediction --prediction-root`, `--output-dir`,
`--queue-dir`, `--duration-sec`, `--dataset-split`, `--prepare-only`, `--isaac-python`, `--headless`, `--auto-close`.
`--prepare-only`는 GUI를 실행하지 않는다. `--send`는 native queue에 제출한다. 둘 다 없으면 Isaac child를 실행한다.
이번에는 main/queue를 호출하지 않고 import-safe native math 함수만 직접 사용했다.

Backend bridge의 fixed Python: `C:/Users/hong_/anaconda3/envs/py3_12/python.exe`.
기존 GUI launcher: `D:/isaacsim/python.bat`. 두 실행 환경을 혼용하지 않는다.
shell=False, secret environment stripped, bytecode writes disabled, offline math timeout=180초, retry=0.

## 3. simulator vs simulator2 contract

| Contract | simulator | simulator2 | Welding-Agent impact |
|---|---|---|---|
| sample identity | H5 stem, duplicate 거부 | 동일 | job=response=request=H5 stem=OBJ stem 강제 |
| supported families | native L_PR/T_PP/T_PR | B/C/E/L/T × PP/PR/PS/RR/RS/SS, 30개 | versioned resolver 추가, legacy registry 보존 |
| H5/OBJ resolution | extracted/ZIP, teaching→modeling relative path | 동일 | exact singular sample directory만 전달, fallback 없음 |
| scene generation | 3개 explicit fixture | 3개 보존 +27개 CAD-contact builder, B_RR/T_RR policy | native world mesh/transform 배열을 소비 |
| trajectory schema | source trajectory.npz+4-field metadata, solution NPZ | raw TCP/source raw/waypoint parameter 추가 | source/derived artifacts 분리 |
| coordinate frame | absolute source robot XYZ, H5 index check | index/arc-length/polyline geometry check | native tolerance 유지, 불일치를 align하지 않음 |
| units | source mm, prediction/scene m | 동일 | 원본 float32 N9 NPZ byte-copy |
| waypoint count | finite N≥2; 기존 exports 주로33, 웹9 계약 검사 | finite N≥2, native subdivision | source9/playbackN 별도 |
| interpolation | joint interval residual 검사, densification 없음 | XYZ linear/SLERP ≤5mm/3°, corner 보존 | Robot만 native derived solution 사용 |
| robot orientation | fixed initial fixture orientation | 동일 +T_RR exterior/virtual wire policy | simulator2_policy, vla_orientation=false |
| tool policy | fixed ATU01035 flange mount/tip | mount 동일, T_RR virtual wire tip | native cad/tool/tip arrays 소비 |
| queue | pending/active/results; sample/solution paths | 동일 | Current Preview는 기존 UUID-only owned queue 유지 |
| result contract | native done/failed +solution/report/scene | raw/playback/torch report 추가 | current result에 source9/derivedN 일치 검사 |

## 4. Supported family / naming

`welding_scene_layout.SUPPORTED_FIXTURES/fixture_supported`에서 30개 prefix를 확인했다.
B=Butt, C=Corner, E=Edge, L=Lap, T=Tee. Pairing은 PP/PR/PS/RR/RS/SS다.
Windows 실제 directory의 thickness는 `03(3mm)` 등과 **`M(Mixed)`**다.
dataset_v2 resolver는 `B_RR_M_0018` 같은 mixed ID도 처리한다.
기존 PreviewPolicyRegistry와 legacy dataset_sample.py는 변경하지 않았다.

## 5. Sample / H5 / OBJ resolver

`<dataset>/1.데이터/Other/Other/로봇티칭데이터/<joint>/<pairing>/<thickness>/<sample>/<sample>.h5`
및 동일 relative layout의 `모델링 데이터/.../<sample>.obj`다.
Backend가 canonical exact path를 계산하고 native singular-directory index 및 native OBJ rule과 다시 비교한다.
Unknown/malformed ID, missing asset, wrong stem, symlink/reparse path는 거부한다. 다른 sample 탐색/fallback은 없다.
Existing NIA 9-view train/val scene resolver는 변경하지 않았다.

B_PP H5는 `D:/용접로봇데이터/42.용접로봇 행동 생성 데이터/3.개방데이터/1.데이터/Other/Other/로봇티칭데이터/Butt/PP(Plate-Plate)/03(3mm)/B_PP_03_0001/B_PP_03_0001.h5`.
OBJ는 `모델링 데이터/Butt/PP(Plate-Plate)/03(3mm)/B_PP_03_0001/B_PP_03_0001.obj`.
H5 sha256=`555ea5f9713ec7c92faab990be449ad3837bec04db08a3702bb683df549da603`;
OBJ sha256=`315da0bca15c0aaa0fe1323e1dd73429ed00c4adf9c979be7fb85eb0a1fa7740`.

## 6. Native scene/module builder

Path bridge는 native build_scene/prediction_targets/densify_poses를 호출한다.
Robot bridge는 native run_welding_sample.prepare를 직접 호출하여 orientation/interpolation/IK/FK policy까지 보존한다.
Native sample resolver에는 정확히 한 H5 directory만 전달하며 dataset rglob/index 전체 탐색을 실행하지 않는다.

27개 general family는 build_contact_scene의 두 CAD body contact candidates, rigid GT registration,
approach selection, CAD-up/yaw policy를 사용한다. L_PR/T_PP/T_PR은 기존 explicit builder를 유지한다.
B_RR은 인식된 coaxial joint의 standing fixture, T_RR은 exterior contact/orientation policy가 있다.
Welding-Agent는 geometry/registration/fixture 알고리즘을 복제하지 않는다.
Native workpiece world vertices/faces, source_to_scene, robot/tool arrays를 immutable solution에 보존한다.
기존 owned renderer는 그 배열을 USD visual로 표시한다. Native physics/articulation server는 이번 Current GUI 경로에서 실행하지 않는다.
Current Robot Preview는 kinematic visual/FK이며 physics/timeline stepping이 없다.

## 7. Source frame / source_to_scene

H5 절대 robot XYZ(mm)의 origin/axis order/sign을 그대로 사용한다. Start subtraction, sign/axis 추측,
scale, prediction fitting/projecting/correction은 하지 않는다.
Frame 문자열 외에 VLA GT와 exact H5 mm→m consistency를 native **0.05mm** tolerance로 검사한다.
B_PP GT↔H5 최대 오차=**0.00007040456633534796mm**, resampling=index.

Native scene transform은 **GT/CAD-derived simulation placement**다. Native builder는 GT로 scene 배치를 추정하지만
prediction을 GT에 맞춰 수정하지 않는다. 동일한 SE(3)를 GT/prediction 양쪽에 적용한다.
이것은 recovered camera/robot extrinsics가 아니다. CAD/source path를 scale/deform하지 않는다.
Robot base는 native URDF/FK origin, tool은 native mounted CAD/tip policy다.

## 8. Field-by-field VLA input

| Welding-Agent | Native input / binding |
|---|---|
| artifact UUID | private package/provenance source_artifact_id, HTTP는 UUID만 허용 |
| sample_id | metadata.episode_id=job/request/H5/OBJ stem |
| split train/val | original artifact/proof/current scene 일치 검사, native scene에서 추측하지 않음 |
| predicted_path_xyz_mm | original response, float32×.001와 NPZ 일치 검사 |
| predicted_path_m | trajectory.npz exact byte-copy → prediction_targets |
| ground_truth_path_xyz_mm/NPZ GT | exact H5 frame check/reference 표시용, robot XYZ 대체 금지 |
| coordinate_frame | source_robot_frame_unaligned_with_isaac |
| point_count | source9 / separate playbackN |
| model/provenance | source response/completion/approval/input/source-job 및 native code/mesh hashes |
| ADE/FDE | original response 값 보존, native 자체 metric은 별도 diagnostic |

Native metadata는 episode_id/source_units=mm/scale_to_meters=.001/coordinate_frame 네 필드만 생성한다.
Native metadata에 split/model/metrics를 새로 꾸미지 않는다.

## 9. Native interpolation / derived type

densify_poses는 adjacent XYZ를 linear, orientation을 SLERP로 subdivision한다(≤5mm/3°).
Original corner/endpoints와 source index+fraction parameter를 유지한다. T_RR은 native round orientation/parameter composition도 그대로 사용한다.
Welding-Agent는 새 보간을 생성하지 않고 endpoint/corner/order/segment membership/no overshoot 및 source XYZ binding만 검사한다.
`SimulatorPlaybackTrajectory`: source_artifact_id, source_point_count=9, playback_point_count=N,
interpolation_method, derived=true, coordinate_frame=simulator2_scene, units=mm.
Native solution TCP는 mm/RPY°, joints radians, world mesh meters다.
Path는 source9, Robot motion만 derivedN을 사용한다.
현재 guided 3D export는 하나의 ordered N9 계약이다. 이 계약에 없는 weld/travel segment를 invent하거나
독립 2D mask regions를 flatten하지 않는다. 다중 3D segment는 별도 VLA 계약 확장이 필요하다.

## 10. Orientation / safety provenance

orientation_source=simulator2_policy, vla_orientation=false.
Native fixture/round policy orientation을 VLA XYZ artifact에 덧붙여 모델 출력으로 저장하지 않는다.
simulation_only=true, physical_robot_executable=false, fixture_ready=false, validated_simulation=false 유지.
기존 B_PR_TOOL_CLEARANCE_FAIL와 registry evidence는 보존한다. 새 IK pass는 clearance pass가 아니다.

## 11. Versioned client / dependency / rollback

Current preview만 WELD_SIM_BACKEND=legacy|dataset_v2로 dispatch한다. Default=legacy.
신규 DatasetSimulatorV2Client는 backend-owned WELD_SIM2_ROOT를 사용한다.
Existing replay는 WELD_SIM_ROOT와 sample/data/prediction/launcher strict config를 그대로 사용한다.
신규 backend 실패 시 legacy나 다른 sample/fixture로 자동 fallback하지 않는다.

Candidate 설정(이번 root .env에는 적용하지 않음):

```dotenv
WELD_SIM_BACKEND=dataset_v2
WELD_SIM2_ROOT=D:/Research_and_Paper/2026경남AISW경진대회/code/simulator2
WELD_SIM_LAUNCHER=D:/isaacsim/python.bat
```

Rollback은 WELD_SIM_BACKEND=legacy 후 backend restart; 기존 WELD_SIM_ROOT를 유지한다.
Native Python에 없던 trimesh/rtree만 repo cache에 설치했다. 외부 Python/Isaac는 변경하지 않았다.
다른 PC에서는 native numpy/scipy/h5py 확인 후 root에서 다음을 실행한다:

```powershell
& 'C:/Users/hong_/anaconda3/envs/py3_12/python.exe' -m pip install --no-cache-dir --no-deps --target .cache/simulator2/python-deps -r requirements-simulator2-offline.txt
```

## 12. 실제 B_PP current VLA offline result

Job=9256ee42-ea9c-41fa-8a63-a8ac98be195a, B_PP_03_0001, train.
Artifact=5450d82a-e927-434e-b365-4ddb11b74850, attempt=e968a420-7316-4325-9ce9-84d972e87290 재사용.
Path/Robot package 둘 다 source/mask/approval/current job/native assets child gate PASS.
Native source/raw/playback=**9/9/9**. Intervals가 native 조건을 이미 만족하여 추가 점이 삽입되지 않았다. 33점 변환 없음.
Original/copied NPZ hash는 모두 `42b496dfd1e0286fb262fddea7c5bb4d34525ee5be4229b477a136cb9679b307`.
Original ADE=38.28097915649414mm, FDE=51.84674835205078mm 유지.
Native 자체 ADE는 P0 제외 정의/float precision의 별도 diagnostic이며 source/UI metrics를 대체하지 않는다.
Native interpolated tip residual=0.001322372846141029mm, mount gap=0, position max=3.188872858294072e-13mm.

## 13. Artifact / gates / evidence

새 private schemas: current-vla-preview-v3, simulator2-current-package-v1. 기존 v1/v2 보존.
`.cache/simulator/prediction-packages/<UUID>/predictions/<sample>/trajectory.npz`는 original byte-copy.
`native/trajectory_solution.npz`, `native/report.json`은 별도 derived output.
Descriptor는 `.cache/simulator/current-previews/packages/<UUID>/preview.json`, readiness pointer만 별도 cache.
Current job/source/proof/approval/input/normalized RGB/H5/OBJ/native solution/code/mesh hashes를 native math 뒤와 GUI 전 재검증한다.
Child gate는 stdlib-only이며 SimulationApp import보다 먼저 실행된다.

최종 evidence: `.cache/simulator2/audits/8d1be224-9ef2-4a9b-a990-8597d4f42b99/report.json`, `status.json`.
Family evidence는 prior_bounded_audit=6f232bed-8181-4bf9-a601-b2e464f9021a의 immutable 결과를 참조한다.
Path descriptor=506999d5-4b12-41ac-9669-1fda9eb0293a; Robot descriptor=49e7d4f2-b397-41b0-b632-3805a32fcca6.
Protected original/native files unchanged=true. Injected fresh API current_preview.configured=true, B_PP path/robot readiness=true, runtime STOPPED/pid=null.

## 14. Web/API / failures

Path/Robot POST URL와 UUID-only request boundary를 유지했다.
신규 `POST /api/simulator/current-vla/preview-preflight`는 explicit offline Robot math/package만 실행하며 runtime.submit/queue/GUI를 호출하지 않는다.
기존 `/current-vla/preflight` export API를 변경하지 않았다. GET status/capabilities는 native process를 호출하지 않는다.
Simulator tab에 sample/family/backend, source9/playbackN, 각각의 readiness와 offline 확인 버튼을 표시한다.
Robot은 native prepared joint/TCP array를 소비한다. 새 IK/XYZ interpolation을 renderer에서 생성하지 않는다.
원본 path/P0/P4/P8 capture와 derived motion count를 별도 기록한다.
status에는 backend/version/family/source/playback counts를 추가했다. Absolute paths/matrices/point arrays는 HTTP summary에 없다.

Typed safe codes: SIMULATOR2_SAMPLE_UNSUPPORTED, SIMULATOR2_H5_MISSING, SIMULATOR2_OBJ_MISSING,
SIMULATOR2_FRAME_MISMATCH, SIMULATOR2_SCENE_BUILD_FAIL, SIMULATOR2_IK_FAIL, SIMULATOR2_PLAYBACK_FAIL.
실패 후 자동 retry/fallback은 없다. Existing replay validation은 완화하지 않았다.

## 15. Family별 bounded preflight

각 family 한 sample의 exact H5/OBJ + native scene math만 확인했다. 전체 dataset scan/benchmark가 아니다.
H5/OBJ는 30개 모두 exact basename으로 존재했다. PENDING은 해당 sample의 current VLA/native Robot IK를 검증하지 않았다는 뜻이다.
C_PP_03_0001은 trajectory와 original_points에 NaN/Inf가 있다(joint_values finite).
이 sample만 차단했고 다른 C_PP sample로 fallback하거나 데이터를 보정하지 않았다.

| Family | Exact sample | H5/OBJ | Path/Workpiece offline | Robot | Native source→playback |
|---|---|---|---|---|---|
| B_PP | B_PP_03_0001 | FOUND | PASS | B_PP current VLA offline PASS | 9→9 |
| B_PR | B_PR_03_0001 | FOUND | PASS | PENDING | 150→150 |
| B_PS | B_PS_03_0001 | FOUND | PASS | PENDING | 150→150 |
| B_RR | B_RR_03_0001 | FOUND | PASS | PENDING | 150→150 |
| B_RS | B_RS_03_0001 | FOUND | PASS | PENDING | 150→150 |
| B_SS | B_SS_03_0001 | FOUND | PASS | PENDING | 49→49 |
| C_PP | C_PP_03_0001 | FOUND | FAIL: nonfinite H5 | PENDING | —→— |
| C_PR | C_PR_03_0001 | FOUND | PASS | PENDING | 150→150 |
| C_PS | C_PS_03_0001 | FOUND | PASS | PENDING | 150→150 |
| C_RR | C_RR_03_0001 | FOUND | PASS | PENDING | 50→50 |
| C_RS | C_RS_03_0001 | FOUND | PASS | PENDING | 150→150 |
| C_SS | C_SS_03_0001 | FOUND | PASS | PENDING | 49→73 |
| E_PP | E_PP_03_0001 | FOUND | PASS | PENDING | 150→150 |
| E_PR | E_PR_03_0001 | FOUND | PASS | PENDING | 150→150 |
| E_PS | E_PS_03_0001 | FOUND | PASS | PENDING | 150→150 |
| E_RR | E_RR_03_0001 | FOUND | PASS | PENDING | 150→150 |
| E_RS | E_RS_03_0001 | FOUND | PASS | PENDING | 150→150 |
| E_SS | E_SS_03_0001 | FOUND | PASS | PENDING | 150→150 |
| L_PP | L_PP_03_0001 | FOUND | PASS | PENDING | 150→150 |
| L_PR | L_PR_03_0001 | FOUND | PASS | PENDING | 150→150 |
| L_PS | L_PS_12_0001 | FOUND | PASS | PENDING | 150→150 |
| L_RR | L_RR_03_0001 | FOUND | PASS | PENDING | 150→150 |
| L_RS | L_RS_03_0001 | FOUND | PASS | PENDING | 150→150 |
| L_SS | L_SS_03_0001 | FOUND | PASS | PENDING | 49→49 |
| T_PP | T_PP_03_0001 | FOUND | PASS | PENDING | 150→150 |
| T_PR | T_PR_03_0001 | FOUND | PASS | PENDING | 150→150 |
| T_PS | T_PS_12_0001 | FOUND | PASS | PENDING | 50→154 |
| T_RR | T_RR_03_0001 | FOUND | PASS | PENDING | 150→150 |
| T_RS | T_RS_03_0001 | FOUND | PASS | PENDING | 150→150 |
| T_SS | T_SS_12_0001 | FOUND | PASS | PENDING | 121→169 |

## 16. Tests

Python 전체 회귀 **475 passed**, 마지막 Runtime error-code 보강 후 관련 **45 passed**, frontend E2E **33 passed**, build/compileall/diff check PASS.
Fake native fixtures로 original9/derived17, identity/assets/frame/hash, noGTsubstitution, corner/endpoints/order/overshoot,
no fallback/retry, UUID-only API, preflight/GUI 분리, legacy replay/API를 검증했다.
Playwright는 fake backend와 설치된 Chrome을 사용했다. Automated tests에서 real native/model/Isaac는 실행하지 않았다.

## 17. Isaac smoke 전 gate / 남은 확인

B_PP에 SIMULATOR2_ADAPTER_PASS, SAMPLE_IDENTITY_PASS, H5_OBJ_PASS,
VLA_SOURCE_PATH_PRESERVED, SIMULATOR2_PLAYBACK_PACKAGE_PASS 모두 충족했다.
실제 GUI/Tool USD visual/FK/capture/result/owned cleanup lifecycle은 미실행이다.
별도 사용자 smoke에서 candidate env와 backend restart 후 기존 B_PP VLA_READY job의 Path, 그다음 Robot을 확인할 수 있다.
다른 family의 actual VLA/IK 결과 없이 GENERAL_ROBOT_PREVIEW_READY나 전체 sample 성공을 선언하지 않는다.

## 18. 최종 질문 A–G

| 질문 | 답변 |
|---|---|
| A 모든 sample VLA 생성? | 미확정. 9-view/label/split/native planner/approval/remote guided contract가 필요하다. 이번 모델0회, 전체 sample 검증 없음. |
| B prediction을 simulator2가 받는가? | 검증된 current N9 XYZ는 가능. 실제 B_PP native prediction_targets/prepare PASS. 나머지는 exact identity/frame/finite/native preflight 필요. |
| C exact H5/OBJ 자동 scene? | 가능. Canonical exact assets +native resolver/builder. Missing/nonfinite/builder failure는 해당 sample 거부. |
| D 모든 family Path? | source30개 지원. 대표29개 scene math PASS; C_PP_03_0001 nonfinite FAIL. 전체 sample와 실제 GUI는 미확정. |
| E 모든 family Robot? | 미확정. Current B_PP VLA의 native IK만 PASS. 다른29 family의 VLA/IK와 GUI는 PENDING. |
| F 원본/보간 분리? | source NPZ N9 byte-copy +별도 SimulatorPlaybackTrajectory/solution, derived=true. Path9/RobotN과 result counts 분리. B_PP nativeN9. |
| G 미지원/차단 대상? | 30개 밖의 family/비정규 ID, C_PP_03_0001 nonfinite, missing/changed assets/frame, native builder/IK 실패 sample. 전체 실패 목록 scan 없음. |

## 19. Final verdict / production

SIMULATOR2_ADAPTER_READY + SIMULATOR2_FAMILY_LIMITED.
General Path/Robot GUI success 및 production default 전환은 아직 선언하지 않는다.
Legacy rollback/Current Preview/existing replay/registry/upstream model pipeline을 보존했다.

## 20. 재검증

JSON에 original/protected/native hashes, source/derived counts, native reports, family readiness와 호출0회를 기록했다.
Owned code 변경 시 오래된 descriptor/readiness는 무효화된다. Explicit offline preflight로 새 UUID package를 생성한다.
이는 모델 재호출이 아니며 GUI는 별도 사용자 동작으로만 시작한다.

## 21. B_PP_03_0006 capture lifecycle follow-up

P0 FK 성공 후 Kit codepage 오류 + 20초 capture incomplete가 발생했다.
Dataset-v2에서는 screenshots를 optional diagnostic으로 분리했고 ASCII staging을 적용했다.
전체 native playback/원본9점/FK/core export gate는 유지한다. Capture warning만 있으면 READY를
유지하고 Stop까지 GUI/lease를 보존한다. 이전 package/IK를 재계산하지 않고 audited 이전
renderer release만 검증해 새 descriptor UUID로 갱신하는 offline CLI도 제공한다.
현재 sample source9/playback9, 원본/approved mask/package/native solution hashes unchanged.
수정 후 live 재실행은 하지 않았다. [실제 실패 evidence/정책/수동 확인](simulator2-capture-fix.md).
