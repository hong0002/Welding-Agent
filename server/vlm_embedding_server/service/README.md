# Retrieval service

This directory is server-only. It receives a sample ID, embeds the sample's stored
full/target views, searches all nine train indexes on GPU, and returns sample IDs
and scores as JSON. It does not call OpenAI and does not read welding GT masks.

Run:

```bash
cd /NHNHOME/WORKSPACE/26moe002_B/IDEA/JuyoungKim/VLA_TEST/server/vlm_embedding_server
PYTHONPATH="$PWD:$PWD/incoming/code" \
/home/bk-gnu/miniconda3/envs/welding-rag/bin/python -m service.retrieve \
  --sample-id T_SS_12_0012 --top-k 3
```
