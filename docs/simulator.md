# Simulator

Use `WELD_SIM_BACKEND=dataset_final`, configure its original native source/assets and explicit `WELD_SIM_LAUNCHER`. See [setup](setup.md) and [external assets](external-assets.md).

In the web Simulator tab, select a current model 3D output, use Path Preview then Robot Preview, inspect Live/latest capture, and Stop as needed. This is simulation only. Immutable source/approval/lineage proof must pass for STRICT; it does not certify collision safety. Orientation belongs to the simulator policy, not the model.

The older dataset_stp client remains available for explicit operator rollback with separate external sources/assets. No automatic fallback is allowed. Automated tests use stub processes; live Isaac playback is never part of pytest/E2E or this source-only release verification.
