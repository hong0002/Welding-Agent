# Frontend UI/UX redesign — 2026-09-29

## Scope and behavior

The existing RGB → binary mask → instruction → per-region rough path → VLA preview → geometry validation workflow is preserved. This change reorganizes its presentation into an industrial operator workspace. No backend, API, schema, mask export, planning algorithm, simulator launcher, dependency, or environment configuration was changed.

The original vertically stacked inspector cards made the page tall and reduced canvas space. The new desktop shell uses a 56px header, 56px rail, grouped progress indicator, and approximately 72% canvas / 28% Inspector split. Both panels share available viewport height. The Inspector scrolls internally on shorter displays; the canvas retains its aspect ratio without cropping. Mobile stacks the canvas above the Inspector.

## UI structure

- **Command:** language input, direction presets, region inclusion/exclusion, Parse Instruction, collapsed structured output, and a Path navigation action. Existing prerequisites and invalidation rules are unchanged.
- **Path:** selected regions, Generate Weld Plan, actual rough/final point counts, validation result, preview limitations, and JSON download. Independent regions are never rendered as one polyline.
- **Simulator:** existing status fields, sample ID, owned process ID when returned, cached import diagnostic, Start / Run Existing Welding Sample / Stop actions, last sample result, and environment diagnostics. STOPPED is neutral, STARTING amber, READY green, RUNNING_SAMPLE blue, and FAILED red. Status text accompanies color.
- **Console:** collapsed initially, manually opened or closed, displays the existing latest-200 stdout/stderr log entries. Errors add an indicator without forcing the drawer open. There is no new polling endpoint or WebSocket.
- **Stepper:** PREPARE (Scene / Mask / Instruction), PLAN (Rough / Refine / Validate), EXECUTE (independent Simulator). Simulator readiness does not overwrite the current preview preparation step.
- **Canvas:** selected drawing tool, brush size, Undo / Clear, opacity, layer controls, region labels, and filled start / hollow end markers are retained. ResizeObserver fits the displayed stage to available width and height. Stored strokes and mask exports remain full-resolution source pixels.

## Design and accessibility

CSS tokens retain the green identity: background `#F5F6F2`, primary `#20563E`, sidebar `#123A32`, white surfaces, neutral borders, and separate status colors. A local system font stack avoids external font requests. Titles use 24–25px, section titles 16px, primary controls and copy 13px; dense metadata uses smaller utility text. Spacing follows 4/8/12/16/24/32px, corners are 6–8px, shadows are minimal, and interactions use 140ms transitions.

Controls retain accessible names and disabled states. Inspector tabs use tab/tabpanel semantics, roving focus, Arrow Left/Right and Home/End navigation. Focus indicators, a skip link, explicit status text, reduced-motion support, collapsible JSON, and a labeled Console toggle are included. At smaller desktop heights the Inspector can be scrolled to reach downloads and diagnostics. No claim of full keyboard-based freehand drawing is made.

## Changed files

| File | Change |
| --- | --- |
| `frontend/src/App.tsx` | Layout, component wiring, Inspector and Console presentation state; workflow handlers retained |
| `frontend/src/styles.css` | Tokens, operator layout, responsive styles, focus and reduced motion |
| `frontend/src/MaskCanvas.tsx` | Display-only fitting to container height and width |
| `frontend/src/SimulatorPanel.tsx` | Simulator Inspector presentation |
| `frontend/src/useSimulator.ts` | Existing polling/action guards extracted so they stay mounted across tabs |
| `frontend/src/components/Icon.tsx` | Existing inline SVG approach shared between controls |
| `frontend/src/components/StatusBadge.tsx` | Shared status presentation |
| `frontend/src/components/WorkflowStepper.tsx` | Grouped preview and independent runtime progress |
| `frontend/src/components/WorkspaceToolbar.tsx` | Annotation controls |
| `frontend/src/components/Inspector.tsx` | Accessible tab shell |
| `frontend/src/components/CommandPanel.tsx` | Command and region presentation |
| `frontend/src/components/PathPanel.tsx` | Plan controls and result presentation |
| `frontend/src/components/ConsoleDrawer.tsx` | Collapsible log area |
| `frontend/e2e/workflow.spec.ts` | Existing functional checks preserved with tab navigation |
| `frontend/e2e/simulator.spec.ts` | Existing mocked control checks plus status colors and Console navigation |
| `frontend/e2e/workspace.spec.ts` | Four viewport workflows, layout bounds, keyboard navigation and failed Console |
| `docs/ui-redesign.md` | This implementation and verification record |

`RegionSelector.tsx`, `api.ts`, `types.ts`, `mask.ts`, `package.json` and the lockfile are unchanged. No UI framework or icon package was added.

## Verification

- `npm.cmd run build`: PASS (TypeScript + Vite). The non-failing bundle-size warning remains: main JS approximately 599 kB before gzip / 186 kB gzip.
- `npm.cmd run test:e2e`: **12 passed**, 41.1 seconds on the final run, using installed Chrome and dedicated local test servers. All seven existing regression scenarios were retained; five workspace scenarios were added.
- `.venv/Scripts/python.exe -m pytest -q --basetemp=.cache/pytest-ui-redesign`: **136 passed**, 6.73 seconds. One existing Starlette/httpx deprecation warning.
- Compared SHA-256 values for 35 protected files against the pre-change snapshot in `.cache/ui-redesign-protected-hashes.json`: **0 changed**. These cover backend source/dependencies, `.env`, `.env.example`, frontend API/types/mask implementation, and package manifests.
- Browser checks exercise upload, drawing, eraser, undo, clear, display opacity, original mask dimensions, region selection, parse, both directions, planning, validation, download, invalidation, separate rendered paths, tab switching, and Console operation.
- 1920×1080, 1440×900, 1366×768 and 390×844: no horizontal document overflow. Desktop screenshots fit the viewport with approximately 72% workspace width and equal-height panels.
- Simulator actions were tested with intercepted API responses, including empty request bodies, prerequisites, READY transitions, failure handling, and no automatic action when planning or changing tabs. **No actual Isaac GUI was launched.** Simulator screenshots contain test fixtures and are not evidence of an actual simulator run.

## Screenshots

Artifacts are generated by real browser workflows under `frontend/test-results/`:

- `redesign-1920x1080.png`
- `redesign-1440x900.png`
- `redesign-1366x768.png`
- `redesign-mobile.png` (390×844, full page)
- `redesign-390x844.png` (same mobile workflow)
- `redesign-command.png`
- `redesign-simulator-ready.png` (mocked runtime)
- `redesign-simulator-failed.png` (mocked runtime and open Console)

These screenshots were visually reviewed, including the narrow desktop validation area and mobile toolbar/layers. Existing workflow regression screenshots are also regenerated. Generated test storage remains under this repository's `.cache` directory.
