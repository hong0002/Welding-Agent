# Semantic mask operations and independent Trajectory3 segments

## Scope and runtime status

Refinement adapter status: `MASK_REFINEMENT_ADAPTER_READY`.
Live refinement status: `LIVE_MASK_REFINE_SMOKE_PENDING`.

The production `SDKRunner` performs task selection with GPT Agents SDK function
tools. Ordinary messages are no longer diverted to the old keyword router before
SDK execution. The legacy router remains for injected compatibility Runners and
explicit native clarification receipts. No live model or Simulator was invoked
to develop this change. Offline function-call fixtures establish dispatch and
admission correctness; they do not establish live natural-language accuracy.

`get_workspace_state → choose_welding_action → typed action tool` is the default
SDK sequence. One turn cannot switch to another action. Tools check the current
job revision, serialize mutations, retain job/session leases, and reject action
mismatch before inference. The backend determines connected components and
geometry; the Agent receives no pixel/path coordinate parameters.

## Mask edit, refinement and detection are separate operations

| Action | Tool | Input and behavior |
| --- | --- | --- |
| MASK_EDIT | edit_weld_mask | REMOVE / KEEP_ONLY; LEFT/RIGHT/TOP/BOTTOM/MIDDLE/FIRST/SECOND; F/R/S4; semantic reason only |
| MASK_REFINE | refine_weld_mask | Current F binary mask, F RGB and user feedback through the owned Segment2 conditioning adapter; new unapproved draft on validation pass |
| MASK_REDETECT | redetect_weld_mask | Fresh configured Segment2 detection; no current-mask conditioning |
| MASK_APPROVE | request_mask_approval | Human Canvas approval notice only; never approves |
| ROUGH_TRAJECTORY_GENERATE | generate_rough_trajectory | Approved F, semantic direction/order/skips, native Trajectory3 |
| FINAL_TRAJECTORY_GENERATE | run_final_trajectory_prediction | Existing backend selector, separate final readiness and single-region gates |
| STATUS_OR_EXPLANATION | workspace/status tools | No predictor inference |

Editing selects whole 8-connected planning components. FIRST/SECOND refer to
current raster-order IDs, before threshold filtering. Spatial relations require
unambiguous ordering of component bounds/centroids. A single connected component
or ambiguous spatial relation returns a safe clarification question; no arbitrary
half-image crop is performed. Original binary data and native output stay intact.

A new edited mask has `manual_edited` source and its parent mask ID/native lineage.
Approval and approval timestamp are cleared. Instructions, native Rough, final
prediction and downstream current-preview admission are invalidated. Current
Simulator evidence remains stored; it cannot represent the revised input lineage.

Frontend Canvas edits are uploaded through `/api/masks/manual` with
`require_review=true` before Assistant processing. This creates an unapproved
draft. Existing explicit manual-confirm behavior remains compatible: the human
Canvas button confirms the submitted edit or calls `/api/masks/approve`. Sending
a chat message no longer constitutes approval. Drafts in other views must first
be saved/confirmed. New primary-mask IDs refresh the Canvas for every source.

## Native Segment2 conditioned refinement

The read-only `vlm_segment2/mask.py` audit found `predict_camera` receives RGB,
native few-shot examples, `previous: CameraMaskPrediction` (polyline text), and
`feedback`. Its CLI has no existing binary mask or conditioned-refinement mode.
Native redetection therefore does not preserve current user edits as conditioning.

Following explicit user approval, `NativeSegmentV2Client.refine` now uses the
owned `NativeMaskRefinementClient`/fixed worker. It reuses the native inference
function, developer prompt, output schema and rasterizer read-only while adding
the edited binary as a second image. No other dataset views/retrieval/assets or
local paths enter the request; key lookup uses only root UTF-8 `.env`.
Fresh detection remains a separate action and is never a failure fallback.

The Workflow records current parent provenance and rejects restored user removals.
Input/worker/config integrity, empty/malformed/partial results, dropped or joined
regions and raster/vector consistency are checked before replacing the mask.
Raw safe geometry/raster and immutable input lineage survive failure; the current
mask/state/approval remain intact. Passing output creates an unapproved
`ai_refined` revision, invalidates downstream and needs human review/approval.
After approval, native refined vectors and locally carried verified YOLO evidence
enter the existing Trajectory3 input contract; no manual skeleton is generated.
See [mask-refinement.md](mask-refinement.md) for the complete contract. All actual
model calls remain zero for development; `LIVE_MASK_REFINE_SMOKE_PENDING`.

## Multi-region native input and output

Read-only `vlm_trajectory3/cot.py` inspection confirmed independent polylines and
`query_image_guidance_2d.segments[]`, each `connected_to_next=false`. The integration
no longer imposes final prediction's single-region gate before Rough.

The immutable approved-mask session clips existing native polylines against the
approved raster as before; it never computes skeletons or new rough geometry.
It then filters/reorders those polylines by the resolved active `region_order`.
The sidecar proof records this order. `F:polyline_i` in native guidance maps to the
i-th approved input region. Candidate validation checks this correspondence,
direction and proximity to each segment's own component. The accepted display
retains `RoughTrajectory.segments[]`, independent weld segments in `image_pixel`.
Canvas continues to draw one line per segment, never a concatenated polyline.

Unedited native vectors and native point arrays remain unchanged. Newly painted
geometry outside the source native mask still fails closed before Rough
(`NATIVE_MASK_EDIT_UNSUPPORTED`); there is no model-independent centerline fallback.
Final Guided/GPT inputs remain single-region. Selecting final prediction for an
already planned multi-region mask returns a question asking which region to use.
No final prediction is dispatched for a Rough action under either backend selector.

## UI and verification

Decision events remain enum/boolean/count-only. They add mask edit/refinement/
approval actions and bounded region/segment counts. Action mismatch errors are
safe codes, not raw prompts or model reasoning. Canvas sources distinguish
`AI · VLM Segment`, `Manual edited` and `AI Refined from Manual`.

Tests use `ScriptedSemanticModel` through the actual SDK, fake native processes,
immutable approved-session fixtures and fake transports. They cover component
edits, ambiguity, unapproved drafts, refusal to substitute redetection, conditioned
provider constraints, multi-region/order/skip mapping, final-action separation,
stale revisions, read-only requests, schema constraints and Canvas refresh.
Existing clarification, YOLO, 9-view, model-output and Simulator contracts remain
separate. Root `.env` and external research/Isaac files were not modified.

Verification on 2026-10-05: full pytest completed with 793 passed and three
Windows `WinError 5` failures at temporary JSON `os.replace`. A subsequent fresh
directory run of those scenarios plus semantic/SDK coverage passed all 45 tests;
atomic storage checks were not bypassed. Full Playwright initially passed 69/70;
the old frontend-only approval assertion was migrated to the SDK/backend gate,
and that case plus five affected regressions passed 6/6. A previous focused
Canvas/approval/clarification run passed 7/7. Frontend build and backend compileall
passed. The existing build bundle-size warning remains. Live model/SSH/VLA/Isaac
calls are all zero. This is offline contract verification, not a native live pass.
The final semantic/clarification regression run passed 50/50 after checking that
a resolved semantic reply leaves the decision card completed rather than waiting.

## Modified files

- Agent: `backend/agent/{semantic.py,semantic_tools.py,context.py,decision.py,prompts.py,service.py,tools.py,welding_agent.py}`.
- Workflow/API: `backend/orchestrator/workflow.py`, `backend/main.py`, `backend/schemas.py`, `backend/services/{semantic_mask.py,segmentation_client.py}`.
- Native adapters: `backend/model_clients/{contracts.py,native.py,native_approval.py,native_rough3d.py,guidance_preview.py,native_candidate.py}`.
- UI: `frontend/src/{App.tsx,api.ts,types.ts,agentDecision.ts}`, `frontend/src/components/{AgentDecisionCard.tsx,AssistantPanel.tsx}`.
- Tests: `tests/{semantic_fakes.py,test_semantic_workflow.py,agent_fakes.py,agent_e2e_app.py,test_agent.py,test_module_workflow.py}`, `frontend/e2e/{semantic-mask.spec.ts,assistant.spec.ts,native-stack-migration.spec.ts}`.
- Documentation: this file, `README.md`, `docs/architecture.md`.
