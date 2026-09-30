# Segment / Rough integration validation — 2026-09-30

## Scope and result

Implemented real-module Segment/Rough adapters and web/Assistant integration, with Dummy fallback
selected only by configuration. User deferred real VLA; no EX3 or current-plan simulator adapter.
Default runtime remains Dummy. Separate Segment/Rough Python 3.12 environments were created and
their requirements installed using the tested runtime constraints. Backend dependencies were not merged.
Real model activation, remote API availability/quality and inference
latency are **not yet verified**. No real OpenAI request, SSH connection, Isaac GUI, robot execution,
model download, training or dataset scan was performed during development.

## Automated checks

| Check | Result |
|---|---|
| Backend full pytest | **192 passed**, 83.48 s |
| Frontend full Playwright E2E | **22 passed**, about 1.5 min |
| TypeScript + Vite production build | Passed; existing >500 kB bundle advisory remains |
| `python -m compileall -q backend` | Passed |
| `python -m pip check` | No broken requirements in backend and both independent model environments |
| `git diff --check` | Passed |

After the final explicit region-ID mapping/error-classification refinement, the 21 model-adapter
tests and compileall passed again. No full-suite rerun was needed for that focused backend change.

Pytest and E2E use fake workers/models/simulator. The new browser case checks AI overlay appearance,
full-resolution binary export, erasing through the AI base mask, three resulting independent regions,
manual_edited provenance, selected-region replanning, no repeated segmentation, and waiting for
manual redraw. Existing opacity/eraser/undo/clear, Assistant/session/SSE, independent simulator,
multi-region/no-bridge, desktop/mobile and keyboard navigation coverage remains passing.

Earlier targeted failures found and fixed JSON serialization of UUID/datetime provenance, updated
tool-count/schema assertions, and the new test's wrong English eraser button locator. The final full
suite passed once; it was not repeatedly looped. Native build/browser launch needed the same local
Windows permissions as the earlier project's verification; no application code workaround was added.

## Actual external function compatibility, offline

An additional bounded source probe imported each sibling module with external bytecode writes
disabled and sockets blocked. Synthetic RGB plus fake structured model responses exercised:

- Segment: actual `predict_camera`, `prediction_paths`, `rasterize`; same-size L-mode 0/255 output.
- Rough: actual `build_query_rough_action`, `refine_instruction`, `generate_plan`, query rendering;
  two disconnected segments, 9 points total, original pixels/normalized coordinates consistent.

Both passed with **zero live API calls**, first in the diagnostic backend environment and then
in each new independent model environment. This confirms callable compatibility on the inspected
source and these environments, not model accuracy or real inference success. Probe artifacts are
local under `.cache/models/source-probe`.

External Segment and Rough source/config SHA256 fingerprints matched the pre-integration values
in [model-contracts.md](model-contracts.md). No source, checkpoints, sample outputs or secrets in
the sibling directories were edited. Their directories are not Git repositories.

## Live smoke / performance / remaining work

| Stage | Status | Latency / remote peak GPU memory |
|---|---|---|
| Segment live smoke | Not run: automatic OpenAI calls prohibited | Not measured |
| Rough live smoke | Not run: automatic OpenAI calls prohibited | Not measured |
| One-image Segment → Rough live smoke | Pending individual live passes | Not measured |
| Real VLA / three-model E2E | Deferred by user | Not measured |

`backend.model_smoke segment` and `rough` configuration checks ran without `--live`; they observed
the unchanged default Dummy mode. Interpreter paths and explicit image-only reference settings
were subsequently added to local `.env`; credentials and backend mode selections were preserved.
[models.md](models.md) contains independent environment setup,
explicit reference modes and the one-image live commands. Original arbitrary-upload RAG retrieval
is not integrated; current reference choices are explicit image-only or fixed examples. Broad,
branched or closed binary regions may be rejected by the documented centerline conversion.

Simulator current-plan connection remains unavailable. The existing pre-exported VLA sample
playback and its existing validation/ownership rules are preserved.
