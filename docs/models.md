# Native Segment / Rough integration

`NATIVE_PARITY_PASS` is the source of truth. Native mode runs the original CLIs, retrieval,
prompts and artifact writers. Dummy mode remains available. VLA is not connected; native
Workflow plans stop at `ROUGH_PATH_READY` and direct refine requests are rejected.

## Windows configuration

The verified interpreter is `C:/Users/hong_/anaconda3/envs/py3_12/python.exe` for both stages.
The fixed cwd/entrypoints are sibling `vlm_segment/mask.py` and `vlm_trajectory/cot.py`.
Neither a browser request nor an Agent tool can choose paths, Python or configuration.
`NativeRuntime` rejects a different interpreter/repository for real launches. It uses shell=False,
-B, UTF-8, an owned process tree and a bounded deadline. All generated files and Windows configs
must be inside Welding-Agent. No sibling source/config/output/bytecode is written.

Local `.env` now selects `native`. The checked-in `.env.example` keeps `dummy` as the portable default.
`real` is a migration alias for native, not the old image-only route. Restart the backend after changes.

```dotenv
WELD_SEGMENT_BACKEND=native
WELD_ROUGH_BACKEND=native
WELD_SEGMENT_PYTHON=C:/Users/hong_/anaconda3/envs/py3_12/python.exe
WELD_ROUGH_PYTHON=C:/Users/hong_/anaconda3/envs/py3_12/python.exe
WELD_SEGMENT_CONFIG=.cache/native-integration/configs/segment.windows.yaml
WELD_ROUGH_CONFIG=.cache/native-integration/configs/rough.windows.yaml
WELD_SEGMENT_NATIVE_BINDING=.cache/native-integration/configs/binding.json
WELD_ROUGH_NATIVE_BINDING=.cache/native-integration/configs/binding.json
WELD_SEGMENT_TIMEOUT=900
WELD_ROUGH_TIMEOUT=900
WELD_AGENT_RUN_TIMEOUT=1200
```

The active owned configs preserve parity retrieval/model/prompt parameters and use the extracted
Windows dataset at `D:/용접로봇데이터/42.용접로봇 행동 생성 데이터/3.개방데이터`.
Segment `mask.dataset_root` is its `2.데이터(NIA)` subdirectory; Rough `data.root` is the
`3.개방데이터` parent because its original loader appends `2.데이터(NIA)` itself. The same native
API key file and verified SSH alias `IDEA-DEV-1` remain configured. Native child processes omit inherited
OPENAI_API_KEY so native key-file lookup matches parity. No secret is copied to config or manifests.
The `data.mask_sessions` setting now points at our approved input root; `--mask-session` is explicit.
Output roots are `.cache/native-models/outputs/segment` and `outputs/rough`. All paths in the local
YAML are absolute. The old five-sample cache and historical configs/outputs are preserved for parity;
they are no longer production inputs. Retrieval-selected references load directly from the full
extracted dataset without copying them into staging or altering ranking/reference IDs.
`action_bundle.output` now points to owned `.cache/native-models/action-bundles/welding_actions_v1`;
it is an unused prepare_actions.py generation destination, not cot.py's retrieval input. No bundle
generation, training or benchmark is part of this transition.

The backend-owned binding has `sample_id`, `camera`, `image` (the original absolute dataset image),
and optional `views` (native Segment view override). Current binding is B_PR_03_0001/F and omits
views, preserving the native default query views. Uploaded normalized RGB must match this image
pixel-for-pixel. Filename alone never determines identity. Arbitrary uploads fail before inference.
The old `mask_session` binding field is retained for reading old operator files but is NOT used by
web Rough: every web input comes from current human approval.

Read-only setup checks (no API, SSH, heavy imports or dataset traversal):

```powershell
.\.venv\Scripts\python.exe -m backend.native_models check segment
.\.venv\Scripts\python.exe -m backend.native_models check rough
```

The timeout budget matches the prior parity supervisor: setup 60s, retrieval 120s, each model
stage 240s and 900s total. Browser stage requests allow 960 seconds and the local Agent turn
budget is 1200 seconds. Historical failures and later controlled live results are recorded below.

Status is cached process state, not a remote health guarantee. There is no automatic fallback/retry
in Welding-Agent; native SDK retry behavior remains unchanged. A zero exit without the expected
plan/mask artifacts is a failure, including native clarification requests under --once.

## Canvas and approval contract

1. Upload the bound original RGB. Enter the task in the manual instruction field or explicitly ask
   the Assistant for automatic detection. Native mode also has an **AI 마스크 검출** button.
2. Segment runs original `mask.py --config <owned-config> --sample-id <bound-id> --instruction=<text> --once`.
   Native retrieval, predicted masks, result.json, comparison/overlay and few-shot images remain untouched.
   The selected view's original binary PNG is normalized to the shared Mask artifact schema.
3. Canvas shows `vlm_segment` / 승인 대기. No instruction or Rough can run before confirmation.
   `POST /api/masks/approve` accepts only current `job_id` and `mask_id`, records approved_at, and
   preserves the unchanged AI mask's ID/source. There is no Agent approval tool.
4. Brush/Eraser submission through `/api/masks/manual` creates a new immutable binary PNG, source
   `manual_edited`, edited_from_mask_id and native lineage. This explicit submission confirms the new
   binary. Native editing does not auto-confirm when sending an Assistant message. Old downstream
   instruction/rough/final/validation are invalidated by the existing backend state machine.
5. The current binary and its backend-owned metadata are passed to NativeRoughClient. It creates a
   fresh immutable approved session, then calls the original `cot.py --config ... --mask-session ...
   --instruction=<unaltered-text> --once`. Browser and Agent cannot supply a mask-session path.

Source contract: `vlm_trajectory/data.py:load_accepted_session` reads ONLY these files:

```text
.cache/native-models/approved/<UUID>/
  status.json                  {"status":"ok","accepted_iteration":1}
  iteration_001/result.json    {sample_id,instruction,predictions:{F:{camera_id,polylines:[{points:[{x,y}]}]}}}
```

Status is written only after an actual explicit Canvas/API confirmation recorded in the current
Mask. Segment --once is never implicitly approved. No fake native metrics, response IDs, notes or
approval of unseen views are generated. The source Segment directory remains unchanged.

`cot.py` does **not** read a PNG mask. The minimal adapter uses the existing native vector lines
and clips them to the confirmed binary (at subpixel probes, preserving original corners/direction).
Unchanged lines keep their original vertices exactly. It does not invoke a skeleton, infer a new
centerline, modify prompts or generate rough points. Native `build_query_rough_action` alone
simplifies approved lines into rough points. Preview normalization only reads its actual output.

Supported edits remove/trim existing seam geometry, or restore painted pixels within the original
native mask. New pixels outside the original native mask, missing vector coverage, or multiple
vector runs within one connected component are rejected BEFORE a paid call. A separating eraser
cut can create independent native lines if each matches a distinct retained 8-connected component.
This restriction is deliberate: a general binary-to-centerline inverse is not available in the native
contract. Unsupported Brush changes must not silently reuse an old centerline.

A sibling proof file `approved/<UUID>.json` stores mask ID/source, approval timestamp, selected
view(s), minimum area, native source artifact/session ID, binary pixel hash and hashes of both
native input files. Input integrity is verified before and after execution; sessions are never reused
or overwritten. Backend normalized masks are retained independently of native artifacts.

## Rough normalization and artifact ownership

Native artifacts are authored ONLY by their original projects, under our configured output roots.

- Segment: retrieval.json; iteration_001/result.json; F/R/S4 prediction and GT masks;
  comparisons; fewshots/<view>/<rank>_<reference>_<view>_mask.jpg.
- Rough: retrieval.json; query_rough_action.json; refiner.json; query_masks.jpg;
  references/<rank>_<sample>/{mask_views.jpg,rough_action.jpg};
  iteration_001/{plan.json,cot_ko.md,vla_prompt.md,rough_trajectory_overlay.jpg}.

`vla_prompt.md` is a native textual artifact only; producing it does not run VLA.
Records `.cache/native-models/<artifact-UUID>.json` contain hashes and locations, not rewritten
native content. Workflow stores normalized Mask/Rough plus native session ID, relative artifact
availability, source lineage and approved-input hash. No full Markdown or reasoning enters Agent tools.

Normalization verifies primary_camera, mask_normalized:<camera>, finite pixel/normalized agreement,
region/segment bijection, independent segments, operation order, selection and forward/reverse
semantics. Only native pixel coordinates are copied (or reversed by the native decision) into
image_pixel trajectories. Existing own-component geometry checks also run before acceptance.
This is 2D preview validation, not robot safety validation.

`experimental` explicitly selects the legacy image-only workers, none/fixed references and skeleton
adapter. Those modules are unreachable as an execution path in native mode. `dummy` preserves the
full Dummy preview. No real VLA, Isaac or physical robot is triggered by native planning.

## Nine-view migration contract

Actual B_PR_03_0001 files and both native CAMERAS constants establish this canonical order:

| Index | View ID | Filename |
| --- | --- | --- |
| 0 | B | B_PR_03_0001_B_Color.png |
| 1 | F | B_PR_03_0001_F_Color.png |
| 2 | L | B_PR_03_0001_L_Color.png |
| 3 | R | B_PR_03_0001_R_Color.png |
| 4 | S1 | B_PR_03_0001_S1_Color.png |
| 5 | S2 | B_PR_03_0001_S2_Color.png |
| 6 | S3 | B_PR_03_0001_S3_Color.png |
| 7 | S4 | B_PR_03_0001_S4_Color.png |
| 8 | T | B_PR_03_0001_T_Color.png |

Pattern: `<sample_id>_<view_id>_Color.png`. Native camera_from_filename checks these suffixes;
load_sample uses an explicitly supplied sample ID to locate exactly one <sample_id>.json and
exactly one matching source directory. It reads RGB filenames and full_welding annotations from
the label JSON, preserving the Training/Validation split. Welding-Agent does not infer an ID from
an uploaded filename; the backend binding and pixel comparison establish identity. A future
filename parser must remove the complete known view suffix (sample IDs themselves contain underscores).

Segment default query views are F, R, S4 for THIS sample: canonical CAMERAS filtered by the label's
available full_welding polylines. These are three model calls within one native CLI execution.
The SSH image retrieval uses the indexed nine views, separate from these local VLM query views.
Rough uses accepted session views for query visuals, mask descriptors and action retrieval grounding.
Native mask_descriptor is ordered by CAMERAS (nine slots); absent approved views are empty slots.
Current Canvas approves only F, so this integration supplies only F, never unreviewed R/S4.
Native primary priority is F,R,S4,L,S1,T,B,S2,S3; only the selected primary view produces 2D points.
The previous parity Rough used F/R/S4. Native action retrieval still uses the dataset's image index
and accepted masks/text; it is not a query of the single Canvas image alone.

The native predictions map and approval proof's approved_views remain view-keyed. A future 9-view
workspace needs per-view scene/mask IDs and explicit approval aggregation, then one primary-view
preview per result. Current normalization rejects projecting points onto a different view. No
frontend nine-view redesign or inferred camera calibration is included in this change.

## Verification and limits

Automated pytest/Playwright use fake processes/fixtures only. The actual explicitly authorized
B_PR_03_0001 smoke uses an isolated storage directory and one-attempt markers under
`.cache/native-integration`. Its browser images, responses and final report are retained there.
See the recorded result appended below. Further inference requires a separate intentional run.

This remains a single-backend-process research MVP. Before wider use: provision the required
native dataset/reference set, add per-view approval UI, define newly painted seam geometry, expand
language directions beyond left/right, and separately agree on VLA RGB/mask/rough coordinates.
No EX3 sample-only endpoint is treated as a web conditioning interface.

## Recorded integration check — 2026-09-30

Verdict: **IMPLEMENTED_OFFLINE_PASS_LIVE_E2E_INCOMPLETE**.

- Live browser uploaded B_PR_03_0001/F and invoked Native Segment once. Native retrieval and F
  output were created in `.cache/native-models/outputs/segment/20260930_142815_B_PR_03_0001`.
- The 300-second deadline expired during the remaining views. R/S4 and final result.json were
  absent. Workflow kept the scene without applying partial AI output. Native Rough was never
  called, so this attempt produced no new plan.json/cot_ko.md/vla_prompt.md. No automatic retry.
- The earlier complete parity mask `20260930_140052_B_PR_03_0001` was separately replayed OFFLINE.
  Its unchanged approved F polyline was preserved exactly. A 30-pixel-radius eraser cap moved the
  input start from (897,512) to (896.9083,542.75); binary provenance became manual_edited.
- Original native data.load_accepted_session and build_query_rough_action accepted both inputs;
  the edited binary changed native input geometry and its native-constructed rough action. This
  check made ZERO OpenAI/SSH calls and is not claimed as a completed live planner run.
- Both external repositories remained byte/mtime identical (86 Segment files, 80 Rough files).
- Report: `.cache/native-integration/report.json`; contract proof: offline-contract.json; original
  loader output: native-offline-reader.json. The previous parity Rough artifacts remain under
  `.cache/native-parity/outputs/rough/20260930_140314_B_PR_03_0001` and are NOT new E2E results.
- Timeout is now 900 seconds to match the earlier parity supervisor; this change needs a separately
  intentional live run. The 300-second failure does not establish the cause of remote response delay.

Remaining live gate: fresh Segment completion → Canvas approval → actual Native Rough → native
Markdown/plan acceptance. Do not describe this integration as a successful live E2E until that passes.

Automated verification: full pytest 210 passed; later focused backend checks 76 passed; final
native suite 21 passed (including three added regressions). Full Playwright 23 passed using
installed Chrome, plus a final targeted native approval check. TypeScript/Vite build and backend
compileall passed. Automated checks used fake processes only; no API/Isaac calls.

## Timeout diagnosis — no live rerun

The subsequent artifact/source audit classifies the 300-second failure as **E. UNKNOWN**.
F comparison finished at 14:28:25.547 KST; the timeout response was saved at 14:32:41.380,
a 255.832-second gap. Retrieval was already complete and all nine reference JPEGs match parity.
Config differs only in output_dir. Installed SDK defaults permit a 600-second request wait and
two retries, but no historical HTTP/request trace exists to establish that this actually occurred.
The old integration discarded native progress/error stdout and wrote records only on success.
The last native output and R request state cannot be recovered from the saved artifacts.

The earlier change to total timeout=900 does **not** restore parity's stage watchdogs (setup 60,
retrieval 120, per-model-stage 240). Current evidence does not justify a 900-second live rerun.
No live command or model call was made during this diagnosis; the existing timeout setting remains.
See `.cache/native-integration/diagnosis.txt` and diagnosis.json for the full timeline/comparison.

Future invocations now write `.cache/native-models/diagnostics/<attempt-UUID>.jsonl`: UTC and
monotonic process/retrieval/view milestones, observed artifact names/mtime, timeout and cleanup.
No raw stdout, request payload, key or reasoning is stored. A view_started marker precedes native
image encoding and is not an HTTP-request-start marker. Forced Windows cleanup may return 0,
so termination_reason=timeout remains authoritative. Tests use small local stubs only (24 passed).

## Controlled Segment rerun — 2026-09-30

Result: **SEGMENT_LIVE_PASS**. The previous 300-second failure remains **E. UNKNOWN**;
this success does not establish its cause. Exactly one Segment CLI invocation used B_PR_03_0001
with native default F/R/S4, no wrapper retry, and no Rough/VLA/Isaac invocation.

The launcher now restores the parity watchdog policy: setup 60s, retrieval 120s, each GPT stage
240s, overall 900s. Only `[RETRIEVE]`, `[GPT]` and `[REFINE]` reset stage deadlines, matching
the parity supervisor. The SDK's internal timeout/retry defaults and external native source
remain unchanged. Both gate/native Python use unbuffered output; PYTHONUNBUFFERED=1 is explicit.

Attempt UUID: `25cd41aa-ddba-4c6f-ab2c-746167406bd9`. The new owned config differs from parity
only in mask.output_dir. Native output is preserved under
`.cache/native-controlled-segment/25cd41aa-ddba-4c6f-ab2c-746167406bd9/outputs/20260930_151755_B_PR_03_0001`.
The adjacent report.json contains the full timeline and before/after preservation audit.
The one-shot segment.started marker prevents reusing this runner for another live invocation.

| Stage | Start (KST) | End (KST) |
| --- | --- | --- |
| Process | 15:17:41.732 | 15:18:23.734, exit=0 |
| Retrieval | 15:17:43.074 | 15:17:55.385 |
| F | 15:17:56.743 | 15:18:07.121 |
| R | 15:18:07.123 | 15:18:17.086 |
| S4 | 15:18:17.088 | 15:18:23.263 |
| result.json | — | 15:18:23.265 |
| Cleanup | — | 15:18:23.737 |

View start is native `[GPT]`; end is comparison-file mtime, not an HTTP response timestamp.
Total native runtime was 42.031s. All three predicted masks are L-mode, 1920×1080, values 0/255.
Native artifact record: `.cache/native-models/47300c47-24f5-4714-a480-02b732b5365b.json`.
Diagnostic JSONL and separate sanitized merged native stdout/stderr are
`.cache/native-models/diagnostics/7603e232-c690-42df-81bf-bd9298a2b0dd.jsonl` and `.native.log`.
The log contains retrieval IDs, GPT view markers, result metrics, an owned comparison path,
process exit and cleanup. Exceptions retain only class and allowlisted safe message fragments.
API keys, raw request payloads, hidden reasoning and full prompts are not logged.

Byte hashes/mtime remained identical for external Segment (86 files), external Rough (80),
old parity Segment (21), and old partial Segment (13). Offline regression: 29 tests passed,
including deadline/reset/overall-cap, pipe draining, redaction and no-retry stub checks;
backend compileall and git diff --check passed. No model calls occurred in automated tests.
Fresh Segment → Canvas approval → Native Rough live E2E remains a separate, unfinished gate.

## Fresh Segment → Canvas approval → Rough attempt — 2026-09-30

Verdict: **ROUGH_REFERENCE_ASSET_MISSING**, not NATIVE_SEGMENT_ROUGH_LIVE_E2E_PASS.
The controlled Segment success above was reused without another Segment invocation. No older
parity/partial Segment was used as input. The isolated real frontend displayed its F binary mask;
the explicit unchanged-mask smoke approval called the actual /api/masks/approve endpoint.

- Fresh source: `20260930_151755_B_PR_03_0001`, artifact `47300c47-24f5-4714-a480-02b732b5365b`.
- F Mask ID: `c87b2b68-bfa8-4012-bf04-47f71df0fb09`; 1920×1080, binary 0/255, vlm_segment.
- Approved at `2026-09-30T06:35:10.358879Z` (15:35:10.358879 KST), with
  human_mask_confirmation in Workflow history. Mask pixels and original native vertices match.
- Approved session: `.cache/native-models/approved/cc21817f-e742-4833-84a7-18faa3afdba7`.
  Native status.json/result.json were created only after approval; approved views contain F only.
- Native Rough ran exactly once using py3_12, original cot.py, shell=False and unchanged
  native refiner/retrieval/planner settings. Only the owned output root changed for isolation.
- Refiner completed ready; retrieval returned B_PR_03_0002, B_PR_M_0011, B_RS_03_0005.
  The first two reference visual pairs were saved. The third reference is outside the five-sample
  `.cache/native-parity/dataset` mirror currently used by config. Original data.load_sample finds
  zero B_RS_03_0005.json files there and raises RuntimeError before the planner starts.
- Process start 15:35:11.008 KST; refiner marker 15:35:12.682; retrieval start 15:35:23.772;
  retrieval end 15:35:38.777; RuntimeError 15:35:39.005; exit=1 at 15:35:39.312;
  cleanup 15:35:39.316. Total supervisor elapsed 28.312s. No timeout and no automatic retry.

Partial native output:
`.cache/native-fresh-e2e/0aad1d4a-9ca3-4d1a-9e6a-93cbe953fa3a/outputs/rough/20260930_153512_B_PR_03_0001`.
retrieval.json, query_rough_action.json, refiner.json and query_masks.jpg exist. plan.json,
cot_ko.md, vla_prompt.md and rough_trajectory_overlay.jpg were not generated. The native partial
action contains one F segment/nine points, mask_normalized:F, connected_to_next=false; pixel
and normalized coordinates agree. No plan exists to validate operation ordering/weld_enabled,
so no Welding-Agent RoughTrajectory was accepted. Workflow remains INSTRUCTION_READY.

The adjacent report.json records the 13 requested completion fields, artifact availability,
diagnostics, lineage, unchanged approval contract and integrity. reference-check.json records a
read-only data-loader check of the three returned IDs against that small mirror; it made no SDK
or SSH calls and did not extract/copy data. Canvas screenshots preserve the actual review state.
Native diagnostics: `.cache/native-models/diagnostics/0bdae2f5-d38a-4d38-831e-21272fc38f63.jsonl`
and `.native.log`. The generic live RuntimeError message was omitted by the safe allowlist;
the missing-label message is separately established by the read-only native loader check.

External Segment (86 files), external Rough (80), fresh Segment (21), old partial (13), and
parity Segment/Rough (21/14) remained byte/mtime identical. The temporary web server was shut
down. No Segment retry, Rough retry, VLA, Isaac, simulator, training, benchmark or full dataset
scan occurred. The original Segment timeout diagnosis remains E.UNKNOWN.

Before another separately authorized live attempt, provision native label/RGB assets for actual
dynamic retrieval results; do not replace the returned reference IDs with cached examples.
The current five-sample mirror establishes parity for its saved references, not general coverage.
Rough diagnostics now observe refiner/query/plan/Markdown/overlay availability. Agent summaries
expose only regions, counts, frame, status and Markdown availability, never native Markdown bodies.
Targeted native tests: 30 passed using fake processes; no full pytest rerun or test model calls.

## Full Windows dataset migration and approved-session continuation — 2026-09-30

Verdict: **NATIVE_SEGMENT_ROUGH_LIVE_E2E_PASS**.
The earlier ROUGH_REFERENCE_ASSET_MISSING was caused by B_RS_03_0005 being absent from the
bounded five-sample cache. The newly extracted original dataset resolves that asset availability
problem. No conclusion about the older Segment timeout changes; that remains E.UNKNOWN.

Full root: `D:/용접로봇데이터/42.용접로봇 행동 생성 데이터/3.개방데이터`.
The previously missing reference was checked at these exact paths before any broader loader calls:

- Label: `2.데이터(NIA)/Training/02.라벨링데이터/TL_Butt_RS(Round-Structural)/03(3mm)/B_RS_03_0005/B_RS_03_0005.json`
- RGB directory: `2.데이터(NIA)/Training/01.원천데이터/TS_Butt_RS(Round-Structural)/03(3mm)/B_RS_03_0005`
- All nine Color views B/F/L/R/S1/S2/S3/S4/T exist. The hierarchy already matches native loaders.

Original Rough data.load_sample successfully loaded that reference offline: **FULL_DATASET_REFERENCE_LOAD_PASS**.
After switching the active configs, original Segment mask_data.load_sample and Rough data.load_sample
both resolved B_PR_03_0001, B_PR_03_0002, B_PR_M_0011, B_PR_06_0001 and B_RS_03_0005, including
all nine RGB views. These were targeted original-loader calls, with no OpenAI/SSH, extraction,
custom parser, whole-dataset hash/inventory, or dataset writes.

Active configs remain `.cache/native-integration/configs/{segment,rough}.windows.yaml`:
mask.dataset_root now points to the full NIA directory, data.root to its full parent. binding.json
points at the original full-dataset F PNG, verified byte-identical to the previous mirror copy.
The unused action_bundle.output generation target moved to an owned native-models path; no bundle
was generated. Ranking, weights, top_k, SSH, native key selection, models, prompts and SDK defaults
are unchanged. Config backups and semantic changes are saved in the attempt below. Historical
parity/smoke configs and bounded datasets remain preserved.

The existing Workflow job `7237e867-c2b4-4682-9798-96c050e372fb` was continued directly:

| Item | Result |
| --- | --- |
| Fresh Segment source | 20260930_151755_B_PR_03_0001 |
| Current F mask | c87b2b68-bfa8-4012-bf04-47f71df0fb09 |
| Original approval | 2026-09-30T06:35:10.358879Z, unchanged |
| Reused approved session | cc21817f-e742-4833-84a7-18faa3afdba7 |
| New Rough session | 20260930_161910_B_PR_03_0001 |
| Native runtime / exit | 61.079s / 0 |
| Refiner / retrieval / planner | all completed |
| Retrieval refs, in native order | B_PR_03_0002, B_RS_03_0005, B_PR_M_0001 |
| Primary camera / native frame | F / mask_normalized:F |
| Normalized web output | 1 segment / 9 points, image_pixel, px |
| Final Workflow state | ROUGH_PATH_READY |

The continuation harness reuses the exact approved session through NativeRoughClient's existing
predict/normalization flow and checks its approval proof against the current binary, mask ID,
timestamp, native lineage and unchanged polylines. It never calls prepare() to mint another
session or reapproves the mask. The raw language is identical to the previous approved job.
The normal Workflow geometry/state validation applies; no new route, skeleton, points or prompt.
Normalized point arrays equal native points_pixel exactly (this plan selected forward direction).
points_normalized agree with pixel coordinates divided by 1920×1080 within 1e-6. connected_to_next
is false. Operations are approach → follow_segment → retract → finish; weld_enabled is true only
for follow_segment. No robot execution semantics are inferred from this 2D preview.

All required native files exist unchanged under
`.cache/native-models/outputs/rough/20260930_161910_B_PR_03_0001`:
retrieval.json, query_rough_action.json, refiner.json, query_masks.jpg, and iteration_001/
plan.json, cot_ko.md, vla_prompt.md, rough_trajectory_overlay.jpg. Markdown stays in native storage;
Agent receives counts/frame/status/availability only. The native `[VLA]` log line announces
vla_prompt.md creation, not an invocation of a VLA model.

Attempt/report/config backups/offline checks:
`.cache/native-full-dataset/b905841f-17c8-4bc5-815e-523b99216fde`.
Diagnostics: `.cache/native-models/diagnostics/34446583-1c04-4755-bbc2-db52a52f5978.jsonl`
and `.native.log`. Native artifact record: `.cache/native-models/f865f791-5802-4fc4-9ca2-d41fb1e71e80.json`.
The original job and trajectory export are saved in the existing fresh-e2e storage; before-job.json
backs up its prior INSTRUCTION_READY state, while workflow-result.json records the successful state.

Segment calls 0; Rough calls 1; new approvals 0; wrapper retries 0; VLA/Isaac/Simulator calls 0.
Both external native repositories (86/80 files), fresh output, approved session/proof, mask/scene
files, prior failed Rough and old parity/partial outputs passed byte/mtime preservation checks.
No full dataset was hashed. Two focused fake-process approval/state regressions passed; all real
native data checks were offline, separate from the explicitly authorized single live Rough run.
