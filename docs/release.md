# Competition source release

Branch: `gyeongnam-ai-sw-2026-final`, based on `origin/main` (`8dbc340`). All release work happened in a separate clean clone; the original research checkout and external projects were not modified. No force push or history rewrite is used.

## Included / excluded

Backend, frontend, tests, public configs, setup script and eight native source modules are included. Segment2/Trajectory3 are necessary current adapters in addition to the five named model/simulator modules and local retrieval service. See `source-inventory.json` for classification and original native Python hashes.

Datasets, real RGB/H5/OBJ, prediction/session NPZ, retrieval FAISS/SQLite/embeddings, model weights/cache, native CAD/USD/meshes, credentials, environments, Node dependencies and generated outputs are excluded. External originals and ignored runtime assets stay outside the release commit. The submission is approximately 3.4 MB of source; no submitted file exceeds 50/90/100 MiB.

## Portability changes

Backend-owned root discovery supports `modules/` and the original sibling layout. Native Python comes from root `.env`; allowlists remain fixed. Packaged Mask/Rough use their existing env-key contract from root `.env` instead of publishing credential JSON. Verified native helper sources are independent of external retrieval asset location. Local service root defaults are portable; scoring/ranking/index bytes are unchanged. Git attributes preserve native bytes used by protocol hashes.

Windows native Mask/Rough config templates retain the actual GPT-6-Luna/low and retrieval policies. GPT2 remains GPT-6-Luna/medium with original prompt, interpolation, coordinate logic and point counts. Native predictor/interpolation/simulator source hashes remain unchanged; only public filesystem/connection defaults are sanitized. Public config fingerprints are updated accordingly, with algorithm/prompt fingerprints retained.

## Verification

- Backend/setup compileall and key backend/client imports: PASS.
- Actual local service `.py` imports and existing FAISS import: PASS; no encoder load or retrieval search.
- Final root/key/proof/native/helper focused pytest suite: **113 passed**.
- Additional release-layout/CPU compatibility/GPT2 suite after separating external retrieval assets: **35 passed**.
- Endpoint/native prediction-only/clearance/live focused suite: **84 passed** before the final portability boundary checks.
- Fake Playwright GPT2 selection/STRICT-DEMO/live polling/endpoint provenance: **7 passed**.
- Frontend TypeScript/Vite production build: PASS; existing bundle-size advisory remains.
- Secret-pattern plus exact-known-secret matching and prohibited-asset/large-file scan: PASS. Variable names and offline test placeholders are allowed; no real secret values are in submitted source.
- **OpenAI calls = 0; SSH calls = 0; Isaac launches = 0.** npm/Git network operations only.

No new live model/simulator claim is made for this clean source tree. Operators must provide the external assets and their local settings. Existing successful B_PR demonstration is described as endpoint-conditioned, never a blind benchmark or physical/collision-certified execution.

## Rollback

The existing `main` and `server` branches are preserved. If the release branch is no longer wanted, an operator can delete only that remote branch:

```powershell
git push origin --delete gyeongnam-ai-sw-2026-final
# After switching away from the branch in the clean clone:
git branch -D gyeongnam-ai-sw-2026-final
```

Do not reset/clean the original research working tree. Runtime backend rollback to dataset_stp remains explicit and requires its separate external source/assets; there is no automatic fallback.
