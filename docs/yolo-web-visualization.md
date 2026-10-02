# YOLO web display: native contract, implementation and offline audit

This is read-only visualization of stored Segment2 output. YOLO, Segment2 retrieval,
prompts and thresholds, Trajectory3 inputs/reuse, Guided VLA and simulator2 are unchanged.
No model, SSH retrieval or Isaac invocation is needed to display the layer. The Agent
receives no bbox arrays or additional native JSON.

## 1. Actual native detections schema

Audited current job: `1bcbe8ee-d689-49b9-a64f-c04562ffe5f8`, sample `B_PR_03_0001`.
The current F-mask points to artifact `e4d3c6c5-567a-4a08-9bb2-8ec0d1432d88`, session
`.cache/native-models/outputs/segment2/20261002_150309_953491_B_PR_03_0001`.
Actual `yolo/detections.json` fields:

| Location | Fields actually present |
| --- | --- |
| Top level | `schema_version`, `bbox_source`, `sample_id`, `request_id`, `weights`, `ultralytics_version`, `confidence`, `margin`, `bbox_policy`, `coordinate_frame`, `cameras`, `manifest_path` |
| `cameras[view]` | `status`, `width`, `height`, `boxes`, `full_image_path`, `crop_xyxy`, `target_image_path` |
| `boxes[]` | `xyxy`, `confidence`, `class_id` |

Schema version is 1, source `server_yolo`, frame `original_image_pixels_xyxy`, policy
`union_of_class_0_detections`. The real artifact contains one class-ID-0 detection per
camera with actual confidence scores. No class name, class mapping, native detection
ID or timestamp is supplied in this JSON. Top-level confidence is the configured
threshold, not a per-box score. Session/timestamp evidence exists separately in the
existing native record/mask provenance. No new native fields are manufactured.

## 2–4. Views, original pixels and coordinate mapping

Canonical order: **B/F/L/R/S1/S2/S3/S4/T**. YOLO runs over all `query.images` in native
`vlm_segment2/mask.py::retrieve_sample`, independent of the F/R/S4 VLM mask prediction
set. `mask_data.py` binds `<sample>_<camera>_Color.png` to camera IDs. All nine YOLO views
in the audited artifact have original dimensions **1920×1080**.

`vlm_segment2/retrieval_client.py::detect_images` uploads fixed camera filenames, saves
the returned JSON unchanged, and draws `box['xyxy']` directly on the original
`Image.open(images[camera])` without a transform. Accordingly the web preserves float
`[x0,y0,x1,y1]` coordinates exactly. `crop_xyxy` is a retrieval crop including margin;
it is not substituted for the detection box.

The local artifact/client does **not** contain YOLO input size, letterbox/padding or a
scale factor. The remote detector implementation is not in the audited local sources.
Its explicit original-image output frame and native preview define the available
output contract; we do not claim to have inspected remote preprocessing. No guessed
inverse transform is applied. Any other frame is rejected as `YOLO_COORDINATE_INVALID`.

Native `yolo/{camera}.jpg` and `yolo/detections_all.jpg` were confirmed for all nine
views, and remain unchanged. Structured Canvas boxes are the main visualization.

## 5–6. Backend display schema and read-only API

`GET /api/weld/{job_id}/yolo` accepts only a typed UUID path, no query parameters,
native path, commands or body. A missing job is HTTP 404; missing/malformed YOLO returns
HTTP 200 availability/warnings, without changing the workflow or invoking recovery.

```text
source = segment2_native_yolo, display_only = true
job_id, scene_id, sample_id, artifact_id, available
coordinate_space = image_pixel
frame = image_top_left_x_right_y_down
views[view] = {image_width, image_height, detections}
detections[] = {detection_id, class_id?, confidence?, bbox}
bbox = {x_min, y_min, x_max, y_max}
warnings[], trajectory3_reuse_verified
```

Absent optional class/score fields are omitted. A display ID such as `F:0` is explicitly
camera + original array index, unique within one immutable artifact, not a native
tracking ID. No class names are inferred: the UI displays `Class 0 0.83` or only ID if
confidence is absent. No filesystem/SSH path, weights location, API key, prompt,
retrieval internals, arbitrary server metadata or reasoning enters this response.

Resolution is current stored job → primary F mask's `native_source_artifact_id` → exact
backend-owned record → its Segment2 session → that `yolo/detections.json`. No session
glob, sample search or fallback to another session occurs. Existing single-process
storage locking is preserved; this does not claim multi-worker safety.

Validation binds current job/scene/sample, F-mask ID and source scene, native stack
`native_v2`, artifact ID, session name, native result/detection hashes, scene proof and
normalized-image hashes/dimensions. Native upload filename must match camera and exact
request ID. Only Welding-Agent `.cache` session paths are readable. Invalid lineage
hides all boxes; an invalid camera hides only that camera; an invalid box is skipped
with a safe warning and valid boxes remain. Coordinates must be finite, ordered and
within `[0,width] × [0,height]`; actual confidence must be finite in `[0,1]`. No new
threshold, clipping or confidence/class filtering is applied.

Safe warnings: `YOLO_OUTPUT_NOT_AVAILABLE`, `YOLO_OUTPUT_STALE`, `YOLO_SAMPLE_MISMATCH`,
`YOLO_VIEW_MISMATCH`, `YOLO_COORDINATE_INVALID`, `YOLO_ARTIFACT_MALFORMED`.

## 7–10. Canvas layer, toggles, thumbnails and Inspector

The non-listening Konva `yolo-objects` Layer contains thin blue Rects and always-visible
labels below the box. This avoids existing Region labels above it and cannot intercept
Brush/Eraser. Boxes remain original pixels and inherit the same fitted Stage transform
as mask/trajectory. Strokes and labels use `1/scale` for constant screen size. No DOM
overlay geometry is used. Mask is pink, YOLO blue, guidance/path amber or mint.

`YOLO Objects` defaults ON and shows active-view count. Only that view's detections are
rendered. Missing/empty views display zero without copying any boxes. Native-present
views receive compact thumbnail count badges alongside IMAGE/MASK/APPROVED. Inspector
shows view/count, safe class-ID/score labels and separate YOLO/mask provenance. Long
detection lists scroll. The mask's display checkbox is independent of binary export,
opacity, approval and drawing operations.

## 11–13. Lifecycle, manual edits and verified reuse

Asynchronous responses are bound to job, scene, sample and Segment2 artifact revision.
New scenes immediately hide old overlays; late responses are discarded. Manual/Agent
detection progress hides boxes, then reads only the lineage in the completed current
job. Agent reuse of an existing valid mask restores its current boxes without detection.
A failed segmentation never triggers a search for another artifact: only the mask
still in the current stored job can resolve, subject to the same validation.

Brush/Eraser changes preserve original Segment2 YOLO lineage. Inspector can show
`YOLO source: Segment2 detection` alongside `Mask source: manual_edited`. Painting
never becomes YOLO geometry and never triggers detection.

`trajectory3_reuse_verified` additionally requires the sealed current native output,
matching detection hash, native `mode=explicit_previous_stage` provenance and the
`[YOLO REUSE]` milestone in that exact captured session's diagnostics. Missing evidence
returns false and does not hide valid boxes. The audited current job passes all these
checks. The display-only browser fixture clears its downstream proof and thus does
not claim reuse. Native `vlm_trajectory3/yolo_client.py` reuse behavior is unchanged.

## 14. Actual artifact replay

The one audited B_PR job above was replayed through the production normalizer and
isolated offline API/Canvas. All nine views contain one detection. Original float
coordinates match every normalized box exactly. **50 protected files remained unchanged**
(job/record/native artifacts/source RGB/masks and sibling source files).

Generated evidence:

- `.cache/yolo-overlay/real-artifact-audit.json`: sample/session/counts and hashes unchanged.
- `.cache/yolo-overlay/real-artifact-response.json`: sanitized API response.
- `frontend/test-results/yolo-real-artifact.png`: visually inspected actual-image Canvas.

`tests/yolo_replay.py` copies only display inputs and the existing native record to
isolated test storage. It never dispatches a model or reconstructs detections. The
original outputs remain READ-ONLY. Its `/api/test/yolo-replay` route exists only in the
explicit offline test factory, never in the normal application.

## 15–18. Tests and call limits

`tests/test_yolo_overlay.py` forbids SDKs, subprocess launch and HTTP network transport.
Fake native fixtures test exact binding, wrong sample/view, dimensions, nonfinite,
reversed/out-of-bounds boxes, score range, IDs, absent scores/classes, missing/malformed
output, stale hashes/session, running detection, manual edits and HTTP admission.
Agent summaries still contain no bbox arrays.

`frontend/e2e/yolo-overlay.spec.ts` tests actual Konva nodes and fit transforms, toggle,
F/R/empty view, simultaneous mask/guidance/YOLO, thumbnails/Inspector, manual provenance,
re-detection hide/refresh, valid-mask Agent reuse, new job/different sample clearing,
late responses, malformed-output nonfatal behavior and the stored real artifact.

Full pytest, Playwright, frontend build, backend compileall and whitespace checks are
required. Playwright uses installed Chrome via `WELD_TEST_BROWSER` and isolated fake
ports 5185/8012 so the user's normal servers remain untouched. Test temp roots must be
ASCII for existing screenshot-staging tests. Vite's temporary config writing requires
execution outside this host's restricted sandbox. Model/SSH retrieval/simulator call
counts for this work are **0**.

## 19–20. Changed files and operator check

- Backend: `backend/main.py`, `backend/services/yolo_overlay.py`.
- Frontend: `frontend/src/App.tsx`, `MaskCanvas.tsx`, `api.ts`, `types.ts`,
  `useYoloOverlay.ts`, `styles.css`; components `Inspector.tsx`, `SceneViews.tsx`,
  `YoloObjects.tsx`.
- Offline checks: `tests/native_stack_fakes.py`, `tests/agent_e2e_app.py`,
  `tests/test_yolo_overlay.py`, `tests/yolo_replay.py`, `frontend/e2e/yolo-overlay.spec.ts`.
  `frontend/e2e/workflow.spec.ts` ensures the Canvas is visible before pointer drawing
  after a mobile image-load scroll-anchor change.
- Docs: `README.md`, `docs/architecture.md`, this report.

Restart Backend to load the new read-only route, refresh frontend, restore a job with
current Segment2 mask provenance and use `YOLO Objects` / the nine thumbnails. No new
segmentation is needed. Final verification results are recorded below after checks.

## Final verification

Verdict: **YOLO_WEB_VISUALIZATION_READY**.

| Check | Result |
| --- | --- |
| Backend pytest (ASCII temporary directory, offline) | 527 PASS, including 28 YOLO cases |
| Full Playwright (installed Chrome, fake servers) | 47 PASS, including 5 YOLO scenarios and real-artifact display replay |
| `npm.cmd run build` | PASS |
| `python -m compileall -q backend` | PASS |
| Diff/whitespace check | PASS |
| Existing Agent/Mask/Trajectory3/Guided VLA/simulator2 regression | PASS using fake transports/launchers |
| Actual inference/retrieval/simulation calls | 0 |
| Native source/artifact modification | None |

Nonblocking output: pytest cannot persist its local node-ID cache (permission warning);
Vite reports the existing >500 kB bundle-size warning. Neither affects check success.
An initial sandbox atomic-file permission failure and the unsuitable non-ASCII test
temp root were resolved by the final ASCII, offline test run. The mobile browser test
now scrolls the Canvas into view before pointer actions rather than drawing offscreen.
Twenty repository files are changed, including documentation and test fixtures above.
