# UX pass 2: workflow navigation and mask eraser

## Scope

The forest-green operator console, 72/28 desktop split, Inspector tabs, grouped stepper and bottom Console remain. Changes are confined to frontend presentation, navigation, MaskCanvas display/input handling, and browser regression tests. Backend, endpoints, schemas, models, trajectory planning, storage, simulator bridge, prediction adapter, `.env`, external repositories and dependencies are unchanged. `mask.ts` and `useSimulator.ts` are unchanged as well.

## Eraser root cause and fix

The old `<Layer opacity={opacity}>` passed opacity into each child shape through Konva's `getAbsoluteOpacity()` / `_applyOpacity()`. Thus a `destination-out` eraser inherited the same 0.45 opacity as the brush. On a filled stroke, the first erase retained alpha approximately `255 × 0.45 × (1 - 0.45) = 63`. A browser regression reproduced **alpha 63 where 0 was expected** before the fix.

The mask Layer now composites brush and eraser strokes at alpha 1. Only the completed native canvas receives CSS display opacity, via the public `getNativeCanvasElement()` API. This retains the existing three layers (RGB, editable mask, path/cursor) and confines erasing to the mask. Erasers still use `destination-out`; no background-colored covering stroke is used. After the fix the same browser regression reads **alpha 0** throughout the erased corridor.

Continuous round-cap / round-join lines are retained, including a fast stroke with only one intermediate mouse move. Pointer release records a final position when needed; App ignores repeated identical endpoints so a stationary click retains its circular stamp. The existing thin cursor outline and common brush/eraser size slider remain.

`exportBinaryMask()` continues to rasterize the source-resolution stroke history independently of display opacity and stage scale, then writes opaque grayscale 0/255 pixels. It was not changed. Tests inspect the actual PNG Blob passed to browser fetch before any backend normalization, decode every pixel, and compare both PNG-byte and decoded-pixel SHA-256 values. The test observer forwards the original request unchanged; it is not included in production code.

## Navigation and presentation

- Successful instruction parsing reveals a prominent **경로 계획으로 계속** action below the Inspector's scroll area. Re-parsing remains available as a secondary button.
- Successful planning/validation reveals **Simulator로 이동**. It only changes the selected tab; it never starts or runs the simulator. The next-action copy explains that simulation uses the separate existing VLA sample.
- On desktop the next action stays visible below scrolling content. On short desktop displays it is compact; on mobile it is in normal document flow, not fixed over the viewport.
- Stepper buttons map Instruction → Command; Rough/Refine/Validate → 경로 계획; Simulator → 시뮬레이션. Scene/Mask focus the canvas. Current and completed states remain derived from the existing backend result. Pending-step navigation is also harmless: unavailable actions stay disabled.
- Stepper navigation selection follows the Inspector tab and is visually separate from workflow completion. External navigation moves keyboard focus to the destination tab; mobile also scrolls the Inspector into view.
- Primary actions are localized: 장면 · 마스크, 브러시, 지우개, 실행 취소, 전체 지우기, 지시 분석, 용접 경로 생성, 시뮬레이터 시작/중지, 기존 용접 샘플 실행. Technical names such as RGB, VLA, READY and 2D PREVIEW remain.
- Editing a previously confirmed mask displays **변경됨**, **마스크가 변경되었습니다**, and **다시 확정**. Existing downstream invalidation is retained, and obsolete next actions disappear. Changing display opacity does not mark a mask dirty.
- Simulator runtime, sample and primary actions precede last-run information. Import status and launcher details live in the initially collapsed **환경 상세 · Isaac 진단** section. Polling and simulator action guards are untouched.
- The existing Console error indicator and manual open/close behavior are retained. No auto-opening or new API was added.
- Individual existing layer controls are retained. Optional comparison presets were omitted to keep this pass focused.

## Viewport

The previous maximum display scale of 1 is removed: even a small source RGB image can now fill the available viewport. The stage uses `min(availableWidth / sourceWidth, availableHeight / sourceHeight)` and pointer positions use its inverse; strokes still use original source pixels. Aspect ratio and the complete frame are preserved. At 1920×1080 the 16:9 test image occupies approximately 90% of the visualization area's height, including its metadata rows. Wider/portrait source ratios naturally fit the limiting dimension. Margins baked into the source image are not cropped.

A 320×180 source is tested at an enlarged desktop display scale and after switching to 390px mobile. Source resolution, selected pixel coordinates and exported PNG bytes remain unchanged.

## Files

| File | Change |
| --- | --- |
| `frontend/src/MaskCanvas.tsx` | Full-strength compositing, display-only opacity, uncapped fit and pointer release |
| `frontend/src/App.tsx` | Navigation wiring, localized scene controls, dirty-mask presentation and duplicate endpoint guard |
| `frontend/src/components/NextAction.tsx` | New next-step action area |
| `frontend/src/components/Inspector.tsx` | Next-action slot and localized tabs |
| `frontend/src/components/WorkflowStepper.tsx` | Accessible navigation and selection mapping |
| `frontend/src/components/CommandPanel.tsx` | Localized analysis action and secondary styling after success |
| `frontend/src/components/PathPanel.tsx` | Localized plan action and secondary styling after validation |
| `frontend/src/components/WorkspaceToolbar.tsx` | Localized drawing and history controls |
| `frontend/src/SimulatorPanel.tsx` | Localized actions and lower-priority diagnostics |
| `frontend/src/styles.css` | Compact next area, stepper selection and dirty state |
| `frontend/e2e/eraser.spec.ts` | Four browser tests for mask alpha, actual PNG data, opacity, undo and scaled coordinates |
| `frontend/e2e/navigation.spec.ts` | Next actions/stepper, no implicit mutations, dirty invalidation and screenshots |
| `frontend/e2e/workflow.spec.ts` | Existing assertions retained with updated action selectors |
| `frontend/e2e/simulator.spec.ts` | Existing mocked simulator assertions retained with updated labels |
| `frontend/e2e/workspace.spec.ts` | Four-viewport regression and next-step navigation on mobile |
| `docs/ux-pass2.md` | This implementation and verification record |

## Verification

- Production build: PASS, TypeScript and Vite. Non-failing main-bundle warning remains (approximately 601 kB / 187 kB gzip).
- Mask-specific suite: **4 passed**. Before the fix the original alpha-removal test failed with 63; after the fix it passes with 0.
- Backend regression: **136 passed**, 24.51s. Existing Starlette/httpx deprecation warning only.
- Python compileall: PASS.
- SHA-256 comparison against the pre-change snapshot: **36 protected files, 0 changed**, including backend source/dependencies, frontend API/types/mask export, simulator hook, `.env`, `.env.example` and dependency manifests.
- Full E2E: **17 passed**, 59.6s (all 12 prior scenarios retained, plus four mask tests and one navigation test). Four viewport workflows and screenshots passed with no horizontal overflow.

Mask browser checks cover: selected=255 before erase; erased center, continuous corridor and round footprint=0; every PNG RGB channel is 0/255 and every alpha channel 255; opacity 20/45/80 produces identical PNG and raster hashes; Clear → Undo preserves erased bytes; Erase → Undo restores original bytes; a single click erases fully at each opacity; resize/upscale preserves source dimensions and coordinates.

Simulator APIs are mocked for action tests and the Simulator screenshot. No actual Isaac GUI or existing welding sample was launched. Navigation tests assert that no POST is added by next buttons, stepper navigation, or tab changes.

## Screenshots

1920×1080 artifacts in `frontend/test-results/`:

- `ux-pass2-command.png`
- `ux-pass2-path.png`
- `ux-pass2-simulator.png` — mocked READY state, not an actual simulator run
- `ux-pass2-eraser.png` — one fast erase across the center of a brush stroke

The existing four viewport screenshots are also refreshed: `redesign-1920x1080.png`, `redesign-1440x900.png`, `redesign-1366x768.png`, `redesign-mobile.png`.
