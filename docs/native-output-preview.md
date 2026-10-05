# Native original-output preview

The dated report below describes the original strict candidate implementation.
The current display policy also shows minimally renderable **hard-invalid** raw
outputs through a separate owned snapshot, while retaining all acceptance gates.
See [current Segment2/Trajectory3 display contract](model-output-display.md).

## Cause confirmed from saved artifacts

The previous `_generate_rough3d` built a Guided-compatible preview, ran mask geometry
validation and raised `MODEL_OUTPUT_INVALID` before persisting anything when validation
failed. Complete native points could therefore exist without a visible web result.
Generation, native artifact reading, preview validation and downstream acceptance were
presented as one failure category. Those outcomes are now separate.

The five latest existing Trajectory3 sessions were inspected read-only, without inference:

| Owned rough3d_v3 session | Existing artifacts | Completed plan |
|---|---|---|
| `20261001_161139_615295_B_PR_03_0001` | guidance, query views, reference, refiner, retrieval, clarification | missing |
| `20261001_160848_123572_B_PP_03_0001` | guidance, query views, reference, refiner, retrieval | missing |
| `20261001_160715_728669_B_PP_03_0001` | guidance, query views, reference, refiner, retrieval | missing |
| `20261001_160555_740167_B_PP_03_0001` | guidance, query views, reference, refiner, retrieval | missing |
| `20261001_155744_355948_B_PR_03_0001` | guidance, query views, reference, refiner, retrieval | missing |

These are under `.cache/native-models/outputs/rough3d_v3`. The newest diagnostic
`6d01d75d-acef-4669-947c-afa2fbe72ac8.native.log` shows YOLO reuse → REFINE → retrieval
→ GPT planner → CLARIFY → exit=0, cleanup complete, 47.343 seconds.
Its clarification status is `needs_clarification`. That attempt **did not generate a
completed native plan**; it was not rejected by web geometry validation. No clarification
questions, full plan text or hidden reasoning were copied into chat or this report.
Old outputs and user jobs were preserved; historical partials are not attached to a job
without proving its current approval/instruction lineage.

## Candidate and state contract

`NativeTrajectoryCandidate` retains `native_artifact_id`, session basename, sample ID,
primary camera, native pixel/normalized frames, `units=px`, and separate segments.
Each segment retains native string `segment_id`, `source_mask_id`, original
`points_pixel`, original `points_normalized`, `connected_to_next=false`, and direction
from the native decision when available. The direction field never reverses the candidate
array. Native Trajectory3's source `trajectory.py` requires at least two distinct finite
points; its `cot.py/build_query_image_guidance` supplies the two frames and mask IDs.
No skeleton, interpolation, correction, clipping or new point generation happens here.

| `native_output.status` | Candidate | Accepted Rough / VLA |
|---|---|---|
| `NATIVE_OUTPUT_MISSING` | none | blocked |
| `PARTIAL_NATIVE_OUTPUT` | none; partial artifact availability | blocked |
| `NATIVE_OUTPUT_READY_UNVALIDATED` | original points if hard checks pass | blocked |
| `NATIVE_OUTPUT_VALIDATED` | original points plus accepted existing preview | explicit Guided action allowed |

The separate validation report contains PASS/WARN/FAIL and fixed safe issue summaries.
Unvalidated output remains `INSTRUCTION_READY`; it is not labeled `ROUGH_PATH_READY`
or validated. Hard failure exposes no candidate or image URLs. Partial artifact summary
does not treat the earlier query guidance as a completed planner output. The original
files remain immutable, with UUID capture records and job-specific proofs owned here.
Incomplete native reports/visuals can produce an unvalidated candidate only after the
full hard JSON/provenance checks succeed; they never produce accepted Rough.

## Validator classification

| Existing check | Classification and consequence |
|---|---|
| malformed JSON, absent required coordinate arrays, non-numeric/bool coordinates, non-finite values, fewer than two distinct points, unequal array lengths, actual count mismatch | HARD_INVALID; no candidate/downstream |
| unknown pixel/normalized frame, native schema/camera, image dimensions, out-of-bounds points or pixel/normalized mismatch | HARD_INVALID; no candidate/downstream |
| sample, raw instruction, current job, approved mask ID/hash/timestamp, source or normalized RGB, candidate/proof/native file hash mismatch | HARD_INVALID; no candidate/downstream |
| guidance/plan/refiner/reference JSON copies, retrieval query/self-exclusion/reference identity/coordinates, approved-mask branch, YOLO lineage/previous session mismatch | HARD_INVALID; no candidate/downstream |
| duplicate native segment or decision IDs, unknown mask ID/camera association, connected segments/travel, duplicate/unknown accepted region or non-weld mode | HARD_INVALID; no candidate/downstream |
| 80% own mask-component proximity within 2 px | SOFT_WARNING for display; acceptance blocked |
| selected-region/native-segment correspondence ambiguity, expected region geometry, missing segment-direction decision | SOFT_WARNING for display; acceptance blocked |
| spatial direction inconsistency; current F-only/single-segment Guided compatibility restriction | SOFT_WARNING for display; acceptance blocked |
| unfinished auxiliary MD/visualizations, missing final output or native clarification | SOFT_WARNING/partial summary; acceptance blocked |

The injected preview validator still runs on the accepted-format candidate. Its bounds,
finite, dimension, duplicate, unknown-region and weld-mode errors remain hard. Generic
segment correspondence and proximity are soft only for NativeRough3D display. Dummy
and baseline 2D validation/transitions are unchanged. The compatibility serializer and
Guided mask proximity checks remain strict for submission.

## UI, Assistant and VLA

Canvas has a `Native model path` display layer and warning dashed style. Path shows
MODEL OUTPUT / VALIDATION / GUIDED VLA independently, a raw-view button only when a
safe candidate exists, artifact availability and fixed links to original native images.
Raw view switches to its actual camera. Each native segment is its own Konva Line;
the exact array is passed to the renderer without reversing or merging.

A soft failure returns a job so Assistant can say the model generated a path but
validation failed. Tool/workspace summaries include status, generated, validation status,
warning count, segment/point counts and safe issues; no raw arrays, filesystem paths,
native Markdown or reasoning. Missing/partial output retains a precise generation error
and the frontend fetches the persisted report without re-running the model.

Default VLA policy requires `NATIVE_OUTPUT_VALIDATED` and PASS, rechecked at Workflow,
client preparation, pre-health dispatch and immutable attempt verification. A changed
source, approval session or candidate blocks use. No automatic VLA execution was added.
Research override is deliberately **disabled**: `user_override=false`,
`override_available=false`, `physical_robot_executable=false`. No hidden override endpoint,
LLM tool or clickable continue action exists. A later explicit research feature would need
its own audited action/provenance and may never override hard failures.

## Offline verification

`tests/test_native_output_preview.py` uses fake native processes/output fixtures for A–G:
PASS, soft FAIL, hard contract/integrity failures, missing output, clarification partials,
exact source hashes/coordinates/order (including reverse direction), and correct Agent
summary/message. It also checks original-image routes, disabled override, input invalidation,
and that blocked outputs never reach even the fake health/prediction transport.

Playwright's `native-output-preview.spec.ts` checks exact points in the **actual Konva
Line**, warning/dash style, layer toggle, raw-view camera switch, original image loading,
partial refresh, absence of a fake completed-path button and disabled VLA. Tests use
the explicit fake factory; real model APIs, SSH, VLA, Simulator and Isaac are not called.

Final verification on 2026-10-01: **384 pytest PASS**, **28 Playwright PASS**;
the two raw-output browser checks also passed after the final Canvas badge placement fix.
`npm.cmd run build`, backend `compileall` and `git diff --check` passed.
Windows tests used fresh directories to avoid previously created temporary-folder ACLs;
the final pytest cache-write warning did not affect the 384 passing tests.
Actual Segment/Rough/OpenAI/SSH/VLA/Simulator/Isaac execution count was zero.
Verdict: **RAW_MODEL_OUTPUT_PREVIEW_READY**.
