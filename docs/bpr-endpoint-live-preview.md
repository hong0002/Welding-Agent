# B_PR endpoint conditioning and viewport polling

The October 6 operator-supplied endpoint is **dataset_gt_endpoint**, not a manually selected point. This is a demonstration with an explicitly supplied GT endpoint, not blind prediction or a performance evaluation. No GT interior trajectory is provided to GPT.

Start remains the original verified first H5 XYZ, applied once: `[654.8400268554688, -5.519999980926514, 303.82000732421875]`. Supplied end: `[679.4199829101562, -8.199999809265137, 235.24000549316406]`. Both use `source_robot_frame_unaligned_with_isaac`, mm.

## Endpoint contract

`GET /api/weld/{job_id}/endpoint-context` reads the original known-start admission (first H5 row only). `POST /api/weld/{job_id}/endpoint` accepts only `end_xyz_mm` and declared `source` (`user_selected_3d` or `dataset_gt_endpoint`); initially B_PR_03_0001 only. Backend owns job/sample/scene/instruction/revision/hash/time. There is no automatic endpoint lookup. A changed endpoint archives Final/prediction and stops this job's owned preview; F mask, approval and Rough remain. Mask or instruction replacement clears the bound endpoint.

The Path panel shows Start/End/frame/mm, an explicit provenance selector, and endpoint error diagnostics. Applying an endpoint does not invoke any model. Press the existing GPT Final button explicitly afterward.

The external `vlm_final_gpt2` repository is unchanged. An owned supplied-endpoint boundary loads its original source, substitutes only endpoint context, uses its existing endpoint prompt semantics in both native Rough/Corners calls, and extends output metadata. The original GT endpoint loader is never called. Native Proposal, model/reasoning, known-start addition, interpolation and NPZ export math are untouched. An absent endpoint takes the exact previous entry path. No snapping, warping, translation or endpoint replacement is performed.

The original native endpoint experimental flag remains off: it would read query GT arrays. Explicit supplied-endpoint provenance is separate. When the declared source is dataset_gt_endpoint, `gt_endpoint_used_as_model_input=true` honestly denotes that single supplied endpoint; `gt_interior_path_used_as_model_input=false`. No query GT/baseline NPZ is present in native query inputs. Native/normalized metadata and immutable completion proofs verify the endpoint object, interface fingerprint, context and numeric error diagnostics. Existing no-endpoint hashes are unchanged.

Optional backend-only `WELD_GPT2_LOCAL_RETRIEVAL_CACHE` selects an owned genuine retrieval JSON. The existing native request/config fingerprint, TRAIN/self-exclusion and file hashes still apply. A mismatched cache fails; no silent fallback. The smoke used the already confirmed matching current-instruction cache and references B_PR_M_0001/B_PR_M_0011/B_PR_M_0002, with zero retrieval/model-encoder reruns. This override was process-local; root .env was not edited.

## Viewport

`dataset_final` now produces one atomic latest JPEG/status pair during the original native playback updates, one in-flight callback, throttled to 4 FPS. No native camera, texture resolution, scene, coordinates, IK, timing or playback loop changes. Original start/middle/end PNG captures remain. Producer closes before the end evidence capture; the native GUI continues holding the final pose.

`GET /api/simulator/current-preview/live-frame/{session}/{request}?job_id=...&artifact_id=...&version=...` returns a validated JPEG or 204, with no-store and `X-Frame-Sequence`. It retains exact current job/artifact/session/request, immutable source/approval/package checks and rejects stale/foreign bindings. Existing v2/STP MJPEG delivery remains.

The web 실시간 tab uses non-overlapping polling with a 250 ms pause between responses, one abort controller/timer, bounded blob URLs and immediate cleanup on state/selection/session changes. On completion it shows the end capture; Stop hides old frames. This is viewport snapshot polling, not camera video. Proof verification added about 189 ms per real frame read, giving approximately 2.16 FPS received versus 4 FPS capture in this smoke. No gate was weakened to increase FPS.

## Verified live evidence

- GPT2 attempt: `e948b055-8176-452c-b34d-8e56813fb779`; current job `f6b980f0-6bf7-4939-9168-58a9f463750a`.
- Artifact: `b04f337c-3837-4fa4-8bdc-856fdc8cba98`; 33/33 finite XYZ. Rough/Corners PASS, exactly two OpenAI stage calls; LOCAL search/SSH calls zero; native elapsed 82.625 s (HTTP action 83.031 s).
- Start error 0 mm; end error 2.469835181452792e-7 mm, unsnapped. Native `predicted_path_m` exactly equals source XYZ × .001. Native NPZ is byte-copied into the simulator package.
- Package: `a94be994-7e80-4cf2-9c4e-5ea1723d0a02`; STRICT session `9be4f41a-9206-40a5-b566-92702bf97754`, request `ce38bff7-8ebf-4ccb-a700-c93a4b383a67`.
- One Isaac launch: native playback/capture SUCCEEDED, 33 source and 33 playback points, 62 generated live frames and 33 distinct received images. Total preview action/warmup/playback/evidence 35.39 s. Start/middle/end images inspected; robot/table/workpiece/tool visible.
- Existing B_PR-only outward 30° / 10 mm virtual TCP standoff remains unchanged. Uncorrected versus corrected source_to_scene, workpiece vertices, raw predicted XYZ and planned target XYZ remain identical. GT is not a robot target; physical execution remains disabled.
- Previous GPT2 native NPZ hash is unchanged. No external project/assets, .env, registration or interpolation code was edited.
- Focused pytest: 78 PASS across endpoint/live/GPT2/STRICT/clearance suites. Two focused fake Playwright tests PASS using installed Chrome; no browser/model downloads. Frontend build and backend compileall PASS. Actual live JPEG updates were checked through the bound API; the fresh in-app browser profile did not contain the operator's restored job/session.

Evidence: `.cache/bpr-endpoint-live/` (job-before, endpoint, Final, invocation/preview results, first/latest observed JPEG, final audit). Permanent PNGs are in the above owned session's `outputs/<request>/` directory. Full native trajectory NPZ remains in `.cache/native-models/gpt2-trajectory/<attempt>/trajectory.npz`.

After evidence verification the owned preview was stopped, and the normal backend restarted without the temporary B_PR cache environment override. Final artifact and endpoint remain current, backend/proxy health are OK, and current/robot configuration are true. Runtime is STOPPED; old live URLs reject with 409. The user can explicitly start this artifact again through Robot Preview; no additional automatic launch occurred.

## Rollback and scope

Use a job without endpoint for the unchanged native GPT2 path; replacing the instruction clears endpoint and invalidates Final through normal backend transitions. Disable/remove the isolated EndpointControl/native endpoint boundary and simulator_final_live observer to roll back these two additions; do not restore the earlier B_PR clearance prepare file. Do not reuse older descriptors after code changes: create new immutable native preparation/proof through normal preflight. dataset_stp remains available as the existing explicit backend rollback; no automatic fallback.

No loop playback was added (`NOT_IMPLEMENTED_TIME_LIMIT`). This preview is not collision certification or hardware execution.

Modified files: backend/schemas.py, backend/main.py, backend/orchestrator/{workflow,state_machine}.py, backend/model_clients/{guided_workflow,gpt2_trajectory,gpt2_trajectory_entry,gpt2_endpoint_native}.py, backend/services/{user_endpoint,gpt2_prediction_proof,simulator2_gate,simulator_final_gate,current_preview_live,preview_live_producer,simulator_final_live}.py, backend/simulator_final_preview.py; frontend/src/{App,api,types,styles}, frontend/src/components/{PathPanel,EndpointControl,SimulatorViewport,viewportPolling}; tests/test_bpr_endpoint_live.py, frontend/e2e/simulator-live.spec.ts; this document, README.md and docs/architecture.md. Existing simulator_final_prepare.py/B_PR clearance changes were preserved.
