# Required external assets (never committed)

## Dataset

`WELD_DATASET_ROOT` names `3.개방데이터`, not a sample directory:

```text
3.개방데이터/
  1.데이터/Other/Other/로봇티칭데이터/<category>/<shape>/<thickness>/<sample>/
    <sample>.h5
    <sample>.obj
  2.데이터(NIA)/
    Training/01.원천데이터/TS_*/<thickness>/<sample>/<sample>_<view>_Color.png
    Training/02.라벨링데이터/TL_*/<thickness>/... label JSON
    Validation/01.원천데이터/VS_*/<thickness>/<sample>/<sample>_<view>_Color.png
    Validation/02.라벨링데이터/VL_*/<thickness>/... label JSON
```

Use the original label/filename mapping, not renamed or reconstructed data. Canonical 9-view order is `B, F, L, R, S1, S2, S3, S4, T`. Native Segment defaults query `F/R/S4`; approved F remains the web editing authority. Native Trajectory3 selects its cameras from mask/session provenance and original camera-priority policy.

## LOCAL retrieval

Configure `WELD_GPT2_LOCAL_RETRIEVAL_ROOT` to a complete backend tree, or supply the following external files beside the packaged `service/` sources:

```text
vlm_embedding_server/
  incoming/database_source/welding_train_v1/
    metadata.sqlite
    ... full/target RGB files referenced by database records
  incoming/action_source/welding_actions_v1/actions.jsonl
  index/welding_train_v1/dinov2_base_v1/
    index_manifest.json
    <view>/record_ids.json
    <view>/full.faiss
    <view>/target.faiss
  index/welding_actions_v1/multilingual_e5_base_v1/
    index_manifest.json
    sample_ids.json
    task.faiss
    action.faiss
    mask.faiss
  service/weights/work_target_v2-2/best.pt
```

Also supply the original TRAIN reference RGB/seam labels/teaching actions. Existing manifests/index bytes and ranking/top-k policy are preserved; never rebuild them for release setup. The owned LOCAL adapter rebinds the root and uses CPU FAISS when GPU FAISS is unavailable. Encoders still need the existing CUDA-compatible PyTorch environment and original `facebook/dinov2-base` / `intfloat/multilingual-e5-base` cache snapshots. No model weights or cache are shipped and offline launch never downloads them. Copied resident lock/daemon files are not used by the direct-call path.

## Simulator / Isaac

Install compatible Isaac Sim independently. Supply the original native files below at the configured simulator_final root. Do not create dummy substitutes to pass admission:

```text
ATU01035_welding_tool.usd
rb10_trajectory_with_ATU01035.usda
rbpodo_description/robots/rb10_1300e_u.urdf  (source included)
rbpodo_description/meshes/...  (external)
```

`rb10_trajectory_with_ATU01035.usda` is the original native reference scene required by source/proof checks, not an arbitrary newly generated stage. The environment geometry follows the native `12/데이터수집 환경구축.stp` reference convention already encoded in source. Tool/CAD/mesh redistribution is intentionally excluded; keep originals read-only. Exact URDF mesh references in the included description are listed below:

- `rbpodo_description/meshes/rb10_1300e/collision/link0.stl`
- `rbpodo_description/meshes/rb10_1300e/collision/link1.stl`
- `rbpodo_description/meshes/rb10_1300e/collision/link2.stl`
- `rbpodo_description/meshes/rb10_1300e/collision/link3.stl`
- `rbpodo_description/meshes/rb10_1300e/collision/link4.stl`
- `rbpodo_description/meshes/rb10_1300e/collision/link5.stl`
- `rbpodo_description/meshes/rb10_1300e/collision/link6.stl`
- `rbpodo_description/meshes/rb10_1300e/visual/link0.dae`
- `rbpodo_description/meshes/rb10_1300e/visual/link1.dae`
- `rbpodo_description/meshes/rb10_1300e/visual/link2.dae`
- `rbpodo_description/meshes/rb10_1300e/visual/link3.dae`
- `rbpodo_description/meshes/rb10_1300e/visual/link4.dae`
- `rbpodo_description/meshes/rb10_1300e/visual/link5.dae`
- `rbpodo_description/meshes/rb10_1300e/visual/link6.dae`
- `rbpodo_description/meshes/rb10_1300e_u/collision/link0.stl`
- `rbpodo_description/meshes/rb10_1300e_u/collision/link1.stl`
- `rbpodo_description/meshes/rb10_1300e_u/collision/link2.stl`
- `rbpodo_description/meshes/rb10_1300e_u/collision/link3.stl`
- `rbpodo_description/meshes/rb10_1300e_u/collision/link4.stl`
- `rbpodo_description/meshes/rb10_1300e_u/collision/link5.stl`
- `rbpodo_description/meshes/rb10_1300e_u/collision/link6.stl`
- `rbpodo_description/meshes/rb10_1300e_u/visual/link0.dae`
- `rbpodo_description/meshes/rb10_1300e_u/visual/link1.dae`
- `rbpodo_description/meshes/rb10_1300e_u/visual/link2.dae`
- `rbpodo_description/meshes/rb10_1300e_u/visual/link3.dae`
- `rbpodo_description/meshes/rb10_1300e_u/visual/link4.dae`
- `rbpodo_description/meshes/rb10_1300e_u/visual/link5.dae`
- `rbpodo_description/meshes/rb10_1300e_u/visual/link6.dae`
- `rbpodo_description/meshes/rb16_900e/collision/link0.stl`
- `rbpodo_description/meshes/rb16_900e/collision/link1.stl`
- `rbpodo_description/meshes/rb16_900e/collision/link2.stl`
- `rbpodo_description/meshes/rb16_900e/collision/link3.stl`
- `rbpodo_description/meshes/rb16_900e/collision/link4.stl`
- `rbpodo_description/meshes/rb16_900e/collision/link5.stl`
- `rbpodo_description/meshes/rb16_900e/collision/link6.stl`
- `rbpodo_description/meshes/rb16_900e/visual/link0.dae`
- `rbpodo_description/meshes/rb16_900e/visual/link1.dae`
- `rbpodo_description/meshes/rb16_900e/visual/link2.dae`
- `rbpodo_description/meshes/rb16_900e/visual/link3.dae`
- `rbpodo_description/meshes/rb16_900e/visual/link4.dae`
- `rbpodo_description/meshes/rb16_900e/visual/link5.dae`
- `rbpodo_description/meshes/rb16_900e/visual/link6.dae`
- `rbpodo_description/meshes/rb16_900e_u/collision/link0.stl`
- `rbpodo_description/meshes/rb16_900e_u/collision/link1.stl`
- `rbpodo_description/meshes/rb16_900e_u/collision/link2.stl`
- `rbpodo_description/meshes/rb16_900e_u/collision/link3.stl`
- `rbpodo_description/meshes/rb16_900e_u/collision/link4.stl`
- `rbpodo_description/meshes/rb16_900e_u/collision/link5.stl`
- `rbpodo_description/meshes/rb16_900e_u/collision/link6.stl`
- `rbpodo_description/meshes/rb16_900e_u/visual/link0.dae`
- `rbpodo_description/meshes/rb16_900e_u/visual/link1.dae`
- `rbpodo_description/meshes/rb16_900e_u/visual/link2.dae`
- `rbpodo_description/meshes/rb16_900e_u/visual/link3.dae`
- `rbpodo_description/meshes/rb16_900e_u/visual/link4.dae`
- `rbpodo_description/meshes/rb16_900e_u/visual/link5.dae`
- `rbpodo_description/meshes/rb16_900e_u/visual/link6.dae`
- `rbpodo_description/meshes/rb1_500es_u/collision/link0.stl`
- `rbpodo_description/meshes/rb1_500es_u/collision/link1.stl`
- `rbpodo_description/meshes/rb1_500es_u/collision/link2.stl`
- `rbpodo_description/meshes/rb1_500es_u/collision/link3.stl`
- `rbpodo_description/meshes/rb1_500es_u/collision/link4.stl`
- `rbpodo_description/meshes/rb1_500es_u/collision/link5.stl`
- `rbpodo_description/meshes/rb1_500es_u/collision/link6.stl`
- `rbpodo_description/meshes/rb1_500es_u/visual/link0.dae`
- `rbpodo_description/meshes/rb1_500es_u/visual/link1.dae`
- `rbpodo_description/meshes/rb1_500es_u/visual/link2.dae`
- `rbpodo_description/meshes/rb1_500es_u/visual/link3.dae`
- `rbpodo_description/meshes/rb1_500es_u/visual/link4.dae`
- `rbpodo_description/meshes/rb1_500es_u/visual/link5.dae`
- `rbpodo_description/meshes/rb1_500es_u/visual/link6.dae`
- `rbpodo_description/meshes/rb20_1800e_u/collision/link0.stl`
- `rbpodo_description/meshes/rb20_1800e_u/collision/link1.stl`
- `rbpodo_description/meshes/rb20_1800e_u/collision/link2.stl`
- `rbpodo_description/meshes/rb20_1800e_u/collision/link3.stl`
- `rbpodo_description/meshes/rb20_1800e_u/collision/link4.stl`
- `rbpodo_description/meshes/rb20_1800e_u/collision/link5.stl`
- `rbpodo_description/meshes/rb20_1800e_u/collision/link6.stl`
- `rbpodo_description/meshes/rb20_1800e_u/visual/link0.dae`
- `rbpodo_description/meshes/rb20_1800e_u/visual/link1.dae`
- `rbpodo_description/meshes/rb20_1800e_u/visual/link2.dae`
- `rbpodo_description/meshes/rb20_1800e_u/visual/link3.dae`
- `rbpodo_description/meshes/rb20_1800e_u/visual/link4.dae`
- `rbpodo_description/meshes/rb20_1800e_u/visual/link5.dae`
- `rbpodo_description/meshes/rb20_1800e_u/visual/link6.dae`
- `rbpodo_description/meshes/rb20_1900es_u/collision/link0.stl`
- `rbpodo_description/meshes/rb20_1900es_u/collision/link1.stl`
- `rbpodo_description/meshes/rb20_1900es_u/collision/link2.stl`
- `rbpodo_description/meshes/rb20_1900es_u/collision/link3.stl`
- `rbpodo_description/meshes/rb20_1900es_u/collision/link4.stl`
- `rbpodo_description/meshes/rb20_1900es_u/collision/link5.stl`
- `rbpodo_description/meshes/rb20_1900es_u/collision/link6.stl`
- `rbpodo_description/meshes/rb20_1900es_u/visual/link0.dae`
- `rbpodo_description/meshes/rb20_1900es_u/visual/link1.dae`
- `rbpodo_description/meshes/rb20_1900es_u/visual/link2.dae`
- `rbpodo_description/meshes/rb20_1900es_u/visual/link3.dae`
- `rbpodo_description/meshes/rb20_1900es_u/visual/link4.dae`
- `rbpodo_description/meshes/rb20_1900es_u/visual/link5.dae`
- `rbpodo_description/meshes/rb20_1900es_u/visual/link6.dae`
- `rbpodo_description/meshes/rb30_1400es_u/collision/link0.stl`
- `rbpodo_description/meshes/rb30_1400es_u/collision/link1.stl`
- `rbpodo_description/meshes/rb30_1400es_u/collision/link2.stl`
- `rbpodo_description/meshes/rb30_1400es_u/collision/link3.stl`
- `rbpodo_description/meshes/rb30_1400es_u/collision/link4.stl`
- `rbpodo_description/meshes/rb30_1400es_u/collision/link5.stl`
- `rbpodo_description/meshes/rb30_1400es_u/collision/link6.stl`
- `rbpodo_description/meshes/rb30_1400es_u/visual/link0.dae`
- `rbpodo_description/meshes/rb30_1400es_u/visual/link1.dae`
- `rbpodo_description/meshes/rb30_1400es_u/visual/link2.dae`
- `rbpodo_description/meshes/rb30_1400es_u/visual/link3.dae`
- `rbpodo_description/meshes/rb30_1400es_u/visual/link4.dae`
- `rbpodo_description/meshes/rb30_1400es_u/visual/link5.dae`
- `rbpodo_description/meshes/rb30_1400es_u/visual/link6.dae`
- `rbpodo_description/meshes/rb3_1200e/collision/link0.stl`
- `rbpodo_description/meshes/rb3_1200e/collision/link1.stl`
- `rbpodo_description/meshes/rb3_1200e/collision/link2.stl`
- `rbpodo_description/meshes/rb3_1200e/collision/link3.stl`
- `rbpodo_description/meshes/rb3_1200e/collision/link4.stl`
- `rbpodo_description/meshes/rb3_1200e/collision/link5.stl`
- `rbpodo_description/meshes/rb3_1200e/collision/link6.stl`
- `rbpodo_description/meshes/rb3_1200e/visual/link0.dae`
- `rbpodo_description/meshes/rb3_1200e/visual/link1.dae`
- `rbpodo_description/meshes/rb3_1200e/visual/link2.dae`
- `rbpodo_description/meshes/rb3_1200e/visual/link3.dae`
- `rbpodo_description/meshes/rb3_1200e/visual/link4.dae`
- `rbpodo_description/meshes/rb3_1200e/visual/link5.dae`
- `rbpodo_description/meshes/rb3_1200e/visual/link6.dae`
- `rbpodo_description/meshes/rb3_1200e_u/collision/link0.stl`
- `rbpodo_description/meshes/rb3_1200e_u/collision/link1.stl`
- `rbpodo_description/meshes/rb3_1200e_u/collision/link2.stl`
- `rbpodo_description/meshes/rb3_1200e_u/collision/link3.stl`
- `rbpodo_description/meshes/rb3_1200e_u/collision/link4.stl`
- `rbpodo_description/meshes/rb3_1200e_u/collision/link5.stl`
- `rbpodo_description/meshes/rb3_1200e_u/collision/link6.stl`
- `rbpodo_description/meshes/rb3_1200e_u/visual/link0.dae`
- `rbpodo_description/meshes/rb3_1200e_u/visual/link1.dae`
- `rbpodo_description/meshes/rb3_1200e_u/visual/link2.dae`
- `rbpodo_description/meshes/rb3_1200e_u/visual/link3.dae`
- `rbpodo_description/meshes/rb3_1200e_u/visual/link4.dae`
- `rbpodo_description/meshes/rb3_1200e_u/visual/link5.dae`
- `rbpodo_description/meshes/rb3_1200e_u/visual/link6.dae`
- `rbpodo_description/meshes/rb3_730es_u/collision/link0.stl`
- `rbpodo_description/meshes/rb3_730es_u/collision/link1.stl`
- `rbpodo_description/meshes/rb3_730es_u/collision/link2.stl`
- `rbpodo_description/meshes/rb3_730es_u/collision/link3.stl`
- `rbpodo_description/meshes/rb3_730es_u/collision/link4.stl`
- `rbpodo_description/meshes/rb3_730es_u/collision/link5.stl`
- `rbpodo_description/meshes/rb3_730es_u/collision/link6.stl`
- `rbpodo_description/meshes/rb3_730es_u/visual/link0.dae`
- `rbpodo_description/meshes/rb3_730es_u/visual/link1.dae`
- `rbpodo_description/meshes/rb3_730es_u/visual/link2.dae`
- `rbpodo_description/meshes/rb3_730es_u/visual/link3.dae`
- `rbpodo_description/meshes/rb3_730es_u/visual/link4.dae`
- `rbpodo_description/meshes/rb3_730es_u/visual/link5.dae`
- `rbpodo_description/meshes/rb3_730es_u/visual/link6.dae`
- `rbpodo_description/meshes/rb5_850e/collision/link0.stl`
- `rbpodo_description/meshes/rb5_850e/collision/link1.stl`
- `rbpodo_description/meshes/rb5_850e/collision/link2.stl`
- `rbpodo_description/meshes/rb5_850e/collision/link3.stl`
- `rbpodo_description/meshes/rb5_850e/collision/link4.stl`
- `rbpodo_description/meshes/rb5_850e/collision/link5.stl`
- `rbpodo_description/meshes/rb5_850e/collision/link6.stl`
- `rbpodo_description/meshes/rb5_850e/visual/link0.dae`
- `rbpodo_description/meshes/rb5_850e/visual/link1.dae`
- `rbpodo_description/meshes/rb5_850e/visual/link2.dae`
- `rbpodo_description/meshes/rb5_850e/visual/link3.dae`
- `rbpodo_description/meshes/rb5_850e/visual/link4.dae`
- `rbpodo_description/meshes/rb5_850e/visual/link5.dae`
- `rbpodo_description/meshes/rb5_850e/visual/link6.dae`
- `rbpodo_description/meshes/rb5_850e_u/collision/link0.stl`
- `rbpodo_description/meshes/rb5_850e_u/collision/link1.stl`
- `rbpodo_description/meshes/rb5_850e_u/collision/link2.stl`
- `rbpodo_description/meshes/rb5_850e_u/collision/link3.stl`
- `rbpodo_description/meshes/rb5_850e_u/collision/link4.stl`
- `rbpodo_description/meshes/rb5_850e_u/collision/link5.stl`
- `rbpodo_description/meshes/rb5_850e_u/collision/link6.stl`
- `rbpodo_description/meshes/rb5_850e_u/visual/link0.dae`
- `rbpodo_description/meshes/rb5_850e_u/visual/link1.dae`
- `rbpodo_description/meshes/rb5_850e_u/visual/link2.dae`
- `rbpodo_description/meshes/rb5_850e_u/visual/link3.dae`
- `rbpodo_description/meshes/rb5_850e_u/visual/link4.dae`
- `rbpodo_description/meshes/rb5_850e_u/visual/link5.dae`
- `rbpodo_description/meshes/rb5_850e_u/visual/link6.dae`
- `rbpodo_description/meshes/rb6_1700e_u/collision/link0.stl`
- `rbpodo_description/meshes/rb6_1700e_u/collision/link1.stl`
- `rbpodo_description/meshes/rb6_1700e_u/collision/link2.stl`
- `rbpodo_description/meshes/rb6_1700e_u/collision/link3.stl`
- `rbpodo_description/meshes/rb6_1700e_u/collision/link4.stl`
- `rbpodo_description/meshes/rb6_1700e_u/collision/link5.stl`
- `rbpodo_description/meshes/rb6_1700e_u/collision/link6.stl`
- `rbpodo_description/meshes/rb6_1700e_u/visual/link0.dae`
- `rbpodo_description/meshes/rb6_1700e_u/visual/link1.dae`
- `rbpodo_description/meshes/rb6_1700e_u/visual/link2.dae`
- `rbpodo_description/meshes/rb6_1700e_u/visual/link3.dae`
- `rbpodo_description/meshes/rb6_1700e_u/visual/link4.dae`
- `rbpodo_description/meshes/rb6_1700e_u/visual/link5.dae`
- `rbpodo_description/meshes/rb6_1700e_u/visual/link6.dae`

Runtime captures, transformed arrays and packages are created under repository `.cache`; original H5/OBJ/NPZ are never rewritten.
