# Current F-mask refinement

`MASK_REFINEMENT_ADAPTER_READY` / `LIVE_MASK_REFINE_SMOKE_PENDING`.
The adapter and offline contracts are implemented. No real OpenAI, Segment2,
Trajectory3, Guided VLA, SSH retrieval or Isaac was called for this work.

## Model boundary

The sibling `vlm_segment2/mask.py` CLI does not accept edited binary masks.
The owned `native_mask_refine_entry.py` imports its existing `predict_camera`,
`CameraMaskPrediction`, developer prompt and `mask_data.rasterize` read-only.
A conditioning transport replaces only the query envelope: original F RGB,
current full-resolution F binary PNG, and the exact user refinement instruction.
No examples, retrieval, H5/OBJ, other views, local paths or sample/job IDs enter
the external payload. Static F/dimension/schema/refinement rules identify the
two images. Model/reasoning/line width come from the existing backend Segment2
config; Agent tools cannot set them or a launcher/path. Orchestrator generates
no pixels or coordinates. Image inputs use data URLs and native structured
output through Responses `parse` ([official image inputs](https://developers.openai.com/api/docs/guides/images-vision),
[structured output](https://developers.openai.com/api/docs/guides/structured-outputs?api-mode=responses)).

Only Welding-Agent root `.env` (`OPENAI_API_KEY`, UTF-8/BOM compatible) is read.
No sibling keys.json or inherited token is used. The destination is fixed to
`https://api.openai.com/v1`; SDK tracing/raw payloads/reasoning/exception text are
not logged. `store=false`. Supervisor ownership, `shell=False`, fixed native
Python/cwd and the repository lease are reused. No application retry/fallback
wrapper is added; the native SDK's default retry policy remains unchanged.
This turn runs only injected SDK/process fakes, never that real worker.

## Evidence and validation

Every UUID attempt is under native records `refinement/<UUID>/`:

- `F_rgb.png`, `F_current_mask.png`, private `request.json`;
- `input_manifest.json`: job/scene/sample/parent-mask ID, pixel and file hashes,
  source/config/worker hashes, local command and minimal external-input list;
- `iteration_001/result.json`: native geometry projection, operation, SDK status;
- `iteration_001/F_prediction.png`: unmodified native raster when renderable;
- a locally verified byte-copy of prior `yolo/detections.json`, when available.

No result contains the native free-form note, raw SDK payload or hidden reasoning.
Malformed/unparsed responses retain only safe status evidence; there may be no
raster to display. Original source outputs and existing mask PNGs are immutable.
Native records hash all evidence and record the process exit. Display sealing
publishes bounded PNG/geometry evidence via the existing job-bound endpoint,
including rejected results. A foreign camera is never relabeled as F.

Validation rejects malformed/nonfinite/out-of-bounds/duplicate vertices,
wrong sample/instruction/camera, changed input/source/config/worker, incomplete
SDK responses, empty/filtered-empty masks and PNG/native-polyline disagreement.
Each current planning region must map to exactly one output component: omitted,
split or bridged regions fail `MASK_REFINEMENT_OUTPUT_PARTIAL`. This action
does not delete entire regions; use a separate explicit MASK_EDIT operation.
Disconnected model polylines stay separate for downstream approval.

Manual ancestor revisions identify pixels removed by the user. Output containing
any such pixel still excluded in the CURRENT mask fails
`MASK_REFINEMENT_CONSTRAINT_VIOLATION`. A later explicit Brush addition supersedes
an older erasure at that pixel. Validation never clips/repaints the model result
and never silently switches to MASK_REDETECT. Failures preserve the current mask
and its approval/state, plus raw attempted output for review. Raw evidence alone
is not a new accepted draft and cannot authorize downstream tools.

## Lifecycle and use

Brush/Eraser changes are synchronized as an unapproved manual draft before
Assistant processing. Ask “현재 수정한 마스크 기준으로 보정해줘” with the desired
refinement. Semantic routing selects MASK_REFINE → refine_weld_mask only.
A passing result becomes a new unapproved `ai_refined` mask with current scene,
parent mask and new native session provenance. Canvas displays
**AI Refined from Manual**. Review it and explicitly press mask confirmation.
Approval is never automatic; request_mask_approval is only a notice.

A new draft invalidates the instruction, Trajectory3/Rough, final prediction,
validation and current Simulator package admission. Stored preview/package
evidence is retained. After human approval, the existing approved-session
adapter uses the refined native polylines and locally copied YOLO evidence;
it does not skeletonize the manual mask. No YOLO inference runs during refinement.
If prior YOLO evidence is unavailable, later Trajectory3 admission remains strict.

## Verification

Fake SDK/process tests cover edited pixel and instruction inputs, lineage and
input integrity, missing regions, incomplete/empty/malformed/foreign responses,
user-removal resurrection, raw output preservation, no detection retry/fallback,
approval waiting, downstream invalidation and approved refined-vector handoff.
Playwright verifies Canvas refresh, source label, review button and safe failure
reason/raw evidence. Unit tests forbid real OpenAI construction and subprocess
launches. See the final work report for pytest/Playwright/build/compileall results.

The native Python import-only dependency check confirms PIL, dotenv and Responses
parse availability. It constructs no API client and invokes no native inference.
Live mask quality, provider/model availability and real latency remain untested.

Verification on 2026-10-05: refinement tests **17/17**, related semantic/display
regressions **67/67**, and focused environment/clarification/capture rechecks
**35/35** passed. The final full ASCII-temp pytest run was **811 passed / 2 failed**,
both at the unchanged atomic JSON `os.replace` with Windows `WinError 5`; those
cases passed in the fresh-directory recheck. An earlier repository-local temp run
also failed seven existing capture tests because their injected staging directory
must be ASCII. The capture/storage policy was not changed to bypass either issue.
Full Playwright was **70/71**: the existing native-approval test encountered an
interrupted Scene-image GET. That case plus all three semantic/refinement browser
tests passed **4/4** in a separate fake-server run. Frontend build, backend
compileall and diff check passed. The existing bundle-size warning remains.
Whole-suite clean-pass status is not claimed. Real model/SSH/Isaac calls: **0**.

## Files changed for this adapter

- `backend/model_clients/native_mask_refine.py`, `native_mask_refine_entry.py`:
  owned conditioning process, native geometry validation and immutable evidence.
- `backend/model_clients/native.py`, `contracts.py`, `model_display.py`:
  Segment2 capability, safe error codes and foreign-camera display rejection.
- `backend/orchestrator/workflow.py`: current edited input/ancestor-removal guard,
  failure evidence and unapproved draft/downstream lifecycle.
- `backend/agent/{semantic_tools.py,prompts.py}`: refinement intent/tool contract.
- `frontend/src/api.ts`: safe refinement failure reasons; existing App source
  label/Canvas draft refresh are reused.
- `tests/{mask_refinement_fakes.py,test_mask_refinement.py,native_stack_fakes.py,
  test_semantic_workflow.py,agent_e2e_app.py}` and
  `frontend/e2e/semantic-mask.spec.ts`: offline SDK/process and browser coverage.
- `README.md`, `docs/architecture.md`, this file and
  `docs/semantic-mask-and-rough.md`: current contracts and verification limits.

Root `.env`, sibling research repositories, dataset and Isaac files were not
modified. Existing semantic/multi-region implementation changes were retained.
