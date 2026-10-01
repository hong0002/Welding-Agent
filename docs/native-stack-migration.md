# Native Segment2 / Trajectory3 migration

Baseline: `MODULE_INTEGRATION_COMPLETE`, HEAD `e485063` (시뮬레이터 연결).
Initial staged work was committed during initial inspection; the subsequent
`git status --short`, unstaged/stat and cached/stat checks were clean. Migration
changes do not reset/stage/commit existing work. Simulator/current-preview code,
fixture, clearance and all four sibling source/config/output trees remain read-only.
Production selection is retained until all acceptance gates pass.

## Source audit and contract diff

Segment call chain: `mask.py.main → mask_data.load_sample → retrieval_client.retrieve_sample
→ detect_images → service.detect → service.retrieve --query-manifest → prepare_examples
→ predict_camera (OpenAI Responses parse) → prediction_paths → mask_data.rasterize`.
Trajectory call chain: `cot.py.main → resolve_input → data.load_accepted_session
→ data.load_sample → yolo_client.prepare_yolo → build_query_image_guidance
→ refine_instruction → retrieve_actions (service.retrieve_action)
→ prepare_reference_assets → select_reference_trajectory_3d → generate_plan → JSON/visual/Markdown`.
The native functions own geometry, prompts and model calls throughout.

| Segment contract | vlm_segment | vlm_segment2 | Impact |
|---|---|---|---|
| Entrypoint / cwd | `mask.py`, own repo | Same, new repo | ADAPTER_REQUIRED: versioned fixed repo |
| CLI | config/sample-id/instruction/views/top-k/once | Identical | DROP_IN_COMPATIBLE |
| Python / dependencies | py3_12; openai/pydantic/Pillow/yaml/numpy | Same requirements | DROP_IN_COMPATIBLE; isolated imports PASS |
| Config | server/retrieval/mask | Adds retrieval.bbox_source and yolo settings | ADAPTER_REQUIRED: owned Windows config |
| Dataset loader / sample/split | Label JSON + original RGB under NIA Training/Validation | `mask_data.py` byte-identical | DROP_IN_COMPATIBLE |
| SSH/retrieval | DB query by sample ID | Original RGB upload; server YOLO; query manifest; BatchMode | ADAPTER_REQUIRED: new native server dependency, no DB fallback |
| References | results[].sample_id; self excluded; local original/GT fewshots | Retained, adds detection | DROP_IN_COMPATIBLE; preserve detection provenance |
| Camera order | B F L R S1 S2 S3 S4 T | Identical | DROP_IN_COMPATIBLE |
| Actual query views | Native default is cameras with query full_welding labels; B_PR F/R/S4 | Identical source selection; existing new B_PR output F/R/S4 | DROP_IN_COMPATIBLE; no synthetic masks |
| GPT/prompt | welding-mask-v2; sequential per-view responses.parse; native model/effort | Identical | DROP_IN_COMPATIBLE; no prompt addition / SDK retry changes |
| result.json | sample/instruction/prompt/iteration/feedback/retrieval/response/metrics/predictions | Identical | DROP_IN_COMPATIBLE |
| prediction/polyline | predictions[view].camera_id, polylines[].points[{x,y}], note | Identical | DROP_IN_COMPATIBLE |
| Binary PNG / dimensions | `<view>_prediction.png`, grayscale L, 0/255, original size | Same; actual existing output 1920×1080 | DROP_IN_COMPATIBLE |
| Session name | YYYYMMDD_HHMMSS_sample | YYYYMMDD_HHMMSS_microseconds_sample; created before retrieval | BREAKING_CHANGE for old glob/regex; versioned adapter required |
| Files / artifacts | retrieval.json, fewshots, iteration_001/result/masks/comparisons/comparison_all | Retained + yolo/detections.json, per-view previews, detections_all.jpg | DROP_IN_COMPATIBLE for mask reader; ADAPTER_REQUIRED for availability/lineage |
| Approval | --once does not approve; explicit status.json + accepted iteration + native vectors | Same | DROP_IN_COMPATIBLE; actual human gate retained |

Existing Segment2 output audited read-only:
`../vlm_segment2/outputs/mask_sessions/20261001_123145_276329_B_PR_03_0001`.
All F/R/S4 masks are original 1920×1080 L PNG with values exactly 0/255,
one polyline each. This is fixture evidence, not this migration's live execution.

| Trajectory contract | vlm_trajectory2 | vlm_trajectory3 | Impact |
|---|---|---|---|
| Entrypoint/cwd | cot.py in own repo | Same native entrypoint, new repo | ADAPTER_REQUIRED |
| CLI | config/mask-session/instruction/once | Adds standalone sample-id; preserves mask-session | DROP_IN_COMPATIBLE for approved path; optional-mask path prohibited here |
| Config / dependencies | data/action_bundle/rough_trajectory/server/retrieval/models/planning/output | Adds yolo settings; requirements unchanged | ADAPTER_REQUIRED: owned Windows paths |
| Accepted session loader | Explicit status=ok, accepted_iteration, iteration result predictions polylines | data.py byte-identical | DROP_IN_COMPATIBLE |
| YOLO dependency | None | yolo_client imports fixed ../vlm_project/retrieval_client.py | BREAKING_CHANGE: that sibling is absent locally |
| Fixed import bridge | Not needed | Owned launcher loads unchanged Segment2 native retrieval_client under native cached alias | ADAPTER_REQUIRED; no detector reimplementation, no external writes |
| YOLO reuse | None | Only explicit previous session yolo/detections.json; validates sample/views/dimensions/source/manifest | ADAPTER_REQUIRED: byte-copy verified upstream detection into immutable approved session |
| SSH/action retrieval | image/text/mask → service.retrieve_action | Adds query_manifest and mask_available; optional no-mask weighting | ADAPTER_REQUIRED: native controls this; no request/prompt rewriting |
| Refiner/planner | welding-instruction-refiner-v1 / welding-detailed-plan-v2 | v2-optional-mask / v3-optional-mask; stricter grounded IDs, clarification | ADAPTER_REQUIRED: fail closed on clarification or mask absence |
| Query views / primary | All original views on query sheet; guidance primary approved camera by priority F R S4 L S1 T B S2 S3 | Same; optional-mask fallback only outside Web | DROP_IN_COMPATIBLE; approved F only |
| Plan JSON | welding-cot-v3, refined_task, plan, references, guidance, 3D | Same schema plus mask_available/previous_mask_session/yolo_request_id | ADAPTER_REQUIRED: explicit approved-branch checks |
| ImageGuidance2D | welding-image-guidance-v1; primary/image_size/frames/segments/point budget | Adds mask_available=true in approved branch | DROP_IN_COMPATIBLE; reject false/empty optional branch |
| Points / frame | points_pixel and points_normalized = pixels / [width,height]; image_pixel:F / image_normalized:F | Unchanged | DROP_IN_COMPATIBLE; structured JSON is numeric source |
| Direction | plan.segment_decisions direction=forward/reverse, weld_enabled and grounded mask IDs | Unchanged schemas.py | DROP_IN_COMPATIBLE; direction separate from source points |
| Regions/segments | Disconnected separate, connected_to_next=false; image/ref segments distinct | Same; optional path uses reference IDs only | DROP_IN_COMPATIBLE with mask; no merged weld paths |
| Reference 3D | points_xyz_mm from retrieved rough_action.points_start_relative_mm | Selection retained; no-mask selection method added | DROP_IN_COMPATIBLE with mask |
| Reference unit/frame | mm, retrieved_teaching_start_relative; source frame retained | Same | DROP_IN_COMPATIBLE |
| Registration/execution | registered_to_query=false, is_robot_executable=false | Same | DROP_IN_COMPATIBLE; never VLA final prediction |
| Native Markdown | cot_ko.md / vla_prompt.md | Same files, optional-mask descriptions added | DROP_IN_COMPATIBLE for preservation; never numeric reverse parsing / direct Guided request |
| Query visualization | query_masks.jpg | query_views.jpg | BREAKING_CHANGE for required-file reader |
| Visual outputs | image_guidance_2d_overlay / rough_trajectory_3d / review_all | Same with approved masks | DROP_IN_COMPATIBLE |
| Session names | Seconds timestamp | Microseconds timestamp | BREAKING_CHANGE for old regex; versioned adapter |
| Multi-region | Native supports independent segments, Guided currently one approved F region | Unchanged | DROP_IN_COMPATIBLE; multi-region remains 2D baseline |

Trajectory3's existing output directories contain copied Trajectory2 plans
(planner prompt v2, no mask_available/yolo fields and query_masks.jpg). They are
**legacy fixtures**, not evidence of a successful Trajectory3 run. Synthetic tests
exercise the new schema; actual native source generates the live candidate later.
README's tree still says query_masks.jpg; source actually writes query_views.jpg.
Source wins when docs and code differ.

py3_12: `C:/Users/hong_/anaconda3/envs/py3_12/python.exe`, OpenAI 2.15.0,
Pydantic 2.10.6. Each native project imports successfully in its own isolated
process. An initial combined import probe exposed normal same-name retrieval_client
module collision; production uses separate fixed native processes, not shared imports.

## Versioned integration

Candidate backends are `native_v2` (Segment2) and `native_3d_v3` (Trajectory3).
Rollback choices `native_v1`, `native_3d_v2`, existing `native`/`real` aliases and
`baseline_2d` remain. NativeRuntime/process supervisor/Job Object/UTF-8/900-second
overall deadline/immutable approval/artifact records are reused; shell=False.
Native SDK settings are unchanged. There is no automatic fallback.

`native_trajectory3_entry.py` resolves only fixed sibling paths and registers the
actual Segment2 detector under `welding_shared_yolo_client`, the exact alias
recognized by native yolo_client. Then it executes unchanged native cot.py.
Source fingerprints include Trajectory3, Segment2 and the owned bridge.
Approved sessions contain only native status/result and, when available, the
verified upstream detection byte-copy. Their proof lives outside native layout;
all copied files are hashed and rechecked. Original Segment output is untouched.

Windows configs are generated by `python -B -m backend.native_stack_windows`:
`.cache/native-integration/configs/segment2.windows.yaml` and
`.cache/native-integration/configs/trajectory3.windows.yaml`.
Full dataset root is `D:/용접로봇데이터/42.용접로봇 행동 생성 데이터/3.개방데이터`.
The existing audited SSH alias is retained; native YOLO/remote roots/models/effort
remain from the new configs. Key file paths are backend-only, values never copied
to configs/logs/chat. Existing configs are preserved on a mismatch.

## Agent and Web behavior

`detect_weld_mask()` has no arguments. Explicit mask intent is routed before
planning tools through the configured SegmentClient. The same semantic operation
serves SDK calls and deterministic clear-intent routing; tool lock, admission,
pending mutation ownership and workspace revision checks still apply.
It returns views/region counts/approval summary only. No LLM pixels or vectors.
No approval tool exists. Human F Canvas confirmation is still required before
Instruction/Rough/Guided VLA. Existing masks are retained unless explicit
re-detection is requested. Re-detection preserves prior files/metadata, creates
unapproved masks and invalidates downstream instruction/Rough/VLA.

Frontend preflight recognizes only this allowed mask intent; it does not autosave
or approve a mask during detection. Unsaved manual edits require confirmation or
explicit re-detection. SSE workspace refresh replaces the F Canvas mask, clears
stale drafts and refreshes native result-view badges without page reload. The
9-view layout/Brush/Eraser/baseline controls are preserved.

Guided serialization remains `/v1/predict-guided` multipart sample_id/split/cot/masks:
human-approved F PNG only; cot comes from structured 2D JSON via the existing
serializer. Native Markdown and 3D reference are never sent. Frame and normalized
points/direction remain unchanged; `reference_in_request=false`.

## Acceptance result — 2026-10-01

**NEW_MODEL_STACK_INTEGRATION_COMPLETE** and **AGENT_MASK_WORKFLOW_READY**.
All seven gates passed before the root `.env` was changed. The injected production
factory now resolves NativeSegmentV2Client + NativeRough3DV3Client and both fixed
runtime configurations pass read-only validation. Restart the backend to apply
the selection to an already running process. No automatic fallback or restart.

| Gate | Evidence |
|---|---|
| SEGMENT2_NATIVE_PASS | One B_PR_03_0001 live process, F/R/S4, native result/masks, exit=0 |
| TRAJECTORY3_NATIVE_PASS | One approved-F live process, new prompt/schema/YOLO lineage, plan/MD/visuals, exit=0 |
| AGENT_MASK_WORKFLOW_PASS | Eight intents, get_workspace_state → detect_weld_mask only; live semantic route PASS |
| HUMAN_APPROVAL_PASS | New masks unapproved; planning rejected; explicit user-authorized smoke confirmation; real timestamp |
| GUIDED_VLA_INPUT_COMPAT_PASS | Existing structured JSON serializer; 9 points, F-only train package, integrity PASS, unconsumed |
| NINE_VIEW_WEB_PASS | Chat load/detection refresh, native badges, Canvas, approval, edit drafts, Rough3D, fake VLA_READY |
| BASELINE_REGRESSION_PASS | 354 pytest; 26 distinct browser tests; build/compileall/diff-check PASS |

Pytest and all browser tests use fake native processes/Runner/Guided transport/
simulator. No real APIs or heavy simulator in automated tests. Default Playwright
Chromium was absent; installed Chrome was used via WELD_TEST_BROWSER. Full suite
passed 25 tests; the new test initially checked the transcript instead of the
preflight alert. Corrected targeted browser test passed. This is 26 distinct PASS
cases, not an assertion that the initial full run was green. Build retains the
existing large-chunk warning. No new frontend source changes followed validation.

### One-shot live evidence

Run UUID: `5d37b3d2-163f-4dbf-be4e-bec03076e6b5`.
Job UUID: `389f97f2-1c59-4e5b-8644-4026664d912f`.
Sample/split: `B_PR_03_0001` / `train`.
Owned report directory:
`.cache/native-integration/migration-live/5d37b3d2-163f-4dbf-be4e-bec03076e6b5`.

| Artifact | Owned path / result |
|---|---|
| Segment2 session | `.cache/native-models/outputs/segment2/20261001_153712_124697_B_PR_03_0001` |
| Segment2 timing | Workflow/chat 55.218s; native supervisor 53.516s; exit=0; cleanup complete |
| Segment diagnostics | `.cache/native-models/diagnostics/7539d6b7-8e9e-4fec-8abd-a601d18df269.jsonl` and `.native.log` |
| Segment actual masks | F/R/S4 only; 1920×1080 L 0/255; F has one planning component |
| Approved mask | `dd6e944c-daf8-4d4e-a444-6a8ab19362cf`; approval recorded in smoke-approval.json |
| Immutable native input | `.cache/native-models/approved/37718082-b009-4ecd-b931-6b8be70d4c0c` |
| Approved contract | status.json: status=ok, accepted_iteration=1; iteration_001/result.json: approved F native polylines; yolo/detections.json verified byte-copy |
| Trajectory3 session | `.cache/native-models/outputs/rough3d_v3/20261001_153807_175048_B_PR_03_0001` |
| Trajectory3 timing | Workflow 64.890s; supervisor 64.578s; exit=0; cleanup complete |
| Trajectory diagnostics | `.cache/native-models/diagnostics/3e42a361-3b8f-4ff4-9b3f-fc2fee1fff09.jsonl` and `.native.log` |
| Native plan and Markdown | Above Trajectory session `iteration_001/plan.json`, `cot_ko.md`, `vla_prompt.md` preserved unchanged |
| 2D guidance | Primary F, image_pixel:F / image_normalized:F, 1920×1080, one segment / nine points |
| Reference 3D | Retrieved `points_xyz_mm`; mm / retrieved_teaching_start_relative; registered_to_query=false; normalized is_robot_executable=false |
| YOLO reuse | Native `[YOLO REUSE]`; provenance mode=explicit_previous_stage; approved copy SHA-256 equals Segment2 detection |
| Guided offline attempt | Report directory `guided-attempts/7ce5e779-b526-4994-9dc6-41bd3abb65ae` |
| Manifest SHA-256 | `7c3e8044ed4a7f5668a4f2fc8a9c05de629d3af3ba854aeb7ca50b57b41e0831` |
| Submission | absent; live_called=false; reference_in_request=false; no HTTP/health call |

Live process launches: **Segment2=1, Trajectory3=1**. Native Segment2 internally
calls its sequential F/R/S4 GPT requests; native Trajectory3 calls its refiner and
planner. No extra Orchestrator model, retry wrapper, Guided prediction, Simulator,
Isaac, benchmark or full-dataset scan. Permanent one-shot claim prevents accidental
repeat of the migration CLI. Partial/prior outputs are preserved.
All four sibling source/config fingerprints match before and after. Generated
native files are under Welding-Agent-owned configured roots. Original sessions
are never rewritten by normalization, approval or Guided packaging.

### Production selection and rollback

The root `.env` changed only these model selection groups: WELD_SEGMENT_ and
WELD_ROUGH3D_ BACKEND/REPO/PYTHON/CONFIG/NATIVE_BINDING/TIMEOUT. Other lines are
byte-identical, including all secret/token lines. `.env.example` keeps Dummy and
existing opt-in examples, with explicit candidate/rollback comments.
`production-selection.json` and `rollback-model-selection.json` in the report
directory contain only allowlisted non-secret settings; acceptance.json records gates.

```dotenv
# Current production (all paths below resolved against Welding-Agent root)
WELD_SEGMENT_BACKEND=native_v2
WELD_SEGMENT_REPO=../vlm_segment2
WELD_SEGMENT_CONFIG=.cache/native-integration/configs/segment2.windows.yaml
WELD_ROUGH3D_BACKEND=native_3d_v3
WELD_ROUGH3D_REPO=../vlm_trajectory3
WELD_ROUGH3D_CONFIG=.cache/native-integration/configs/trajectory3.windows.yaml

# Explicit rollback: replace the six lines above, keep fixed Python/binding/900s
# WELD_SEGMENT_BACKEND=native_v1
# WELD_SEGMENT_REPO=../vlm_segment
# WELD_SEGMENT_CONFIG=.cache/native-integration/configs/segment.windows.yaml
# WELD_ROUGH3D_BACKEND=native_3d_v2
# WELD_ROUGH3D_REPO=../vlm_trajectory2
# WELD_ROUGH3D_CONFIG=.cache/native-integration/configs/rough3d.windows.yaml
```

Change backend, repository and config together, then restart the backend. Existing
native/real aliases keep their legacy meanings. `baseline_2d` remains an explicit
per-job Workflow mode; it is not an automatic fallback from a failed new stack.

### Requested 22-item migration report

| Item | Final result |
|---|---|
| 1. Segment2 contract | Native mask.py/once/default query views; same native JSON/polylines/binary full-resolution masks |
| 2. Segment changes | Server YOLO/upload/query manifest + microsecond session; prompt/model mask semantics retained |
| 3. Trajectory3 contract | Native cot.py + immutable approved mask-session; structured 2D guidance/reference3D/native reports |
| 4. Trajectory changes | YOLO reuse/new, optional-mask branch, v3 planner, query_views.jpg and microsecond session |
| 5. Segment2 client | NativeSegmentV2Client through existing NativeRuntime; V1 alias retained |
| 6. Trajectory3 client | NativeRough3DV3Client + fixed native import bridge; V2 alias retained |
| 7. Windows configs | Owned segment2.windows.yaml / trajectory3.windows.yaml, full dataset, fixed py3_12/cwd |
| 8. Agent tool | detect_weld_mask() with zero arguments, configured Segment, counts/views/approval summary |
| 9. Intent routing | Eight explicit intents routed before planning; sample-load tool supports final chat UX |
| 10. Approval | Detection never approves; explicit F UI confirmation; smoke confirmation separately authorized |
| 11. Re-detection | Explicit only; previous mask files retained; source_mask_id lineage; Rough/VLA invalidated; new approval |
| 12. Nine views | Canonical B F L R S1 S2 S3 S4 T; actual F/R/S4 masks only; Canvas/badge refresh without reload |
| 13. 2D guidance | Native query JSON points preserved, F pixel/normalized frames, independent segments, no regeneration |
| 14. Reference 3D | Retrieved points/frame/unit preserved; unregistered/non-executable; distinct from VLA prediction |
| 15. Guided compatibility | Existing serializer/multipart sample_id/split/cot/masks; human-approved F only, no raw native MD/3D |
| 16. Offline tests | 354 pytest, 26 distinct Chrome browser tests, build/compile/diff PASS; fake APIs only |
| 17. Live Segment2 | B_PR_03_0001 once, 55.218s, F/R/S4, native result/artifacts, exit=0 |
| 18. Live Trajectory3 | Same approved sample once, 64.890s, plan/MD/visuals, 9-point guidance, exit=0 |
| 19. Production | Root selection changed only after seven PASS gates; secrets and other configuration untouched |
| 20. Rollback | Explicit native_v1/native_3d_v2 and baseline_2d preserved; no automatic fallback |
| 21. Web sequence | Load sample by chat → detect → inspect/edit → F confirmation → instruction/Rough → explicit VLA request |
| 22. Verdict | NEW_MODEL_STACK_INTEGRATION_COMPLETE; AGENT_MASK_WORKFLOW_READY |

Manual Canvas editing remains `manual_edited` and invalidates downstream. Native
approval clipping preserves original vector geometry and uses the current binary
mask. Arbitrary Brush additions outside native geometry are rejected before Rough
inference; no fabricated centerline. Current Guided supports one F region; multiple
regions remain supported in baseline_2d. Trajectory3 → Guided was validated offline
only in this migration; a fresh actual Guided prediction was intentionally not made.
Simulator/Isaac/current-preview code, fixture and clearance behavior are unchanged.
