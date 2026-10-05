# Retrieval service

This directory is server-only. It receives a sample ID, embeds the sample's stored
full/target views, searches all nine train indexes on GPU, and returns sample IDs
and scores as JSON. It does not call OpenAI and does not read welding GT masks.

## Server access

The retrieval server is accessible to authorized clients over SSH. Remote clients
run `service.action_rpc` through the SSH session and exchange JSON through standard
input/output. The resident GPU worker itself is not exposed as a public HTTP/TCP
service: it listens on a same-user Unix socket inside the server.

The database bundles, FAISS indexes, embeddings, YOLO weights, and runtime logs are
intentionally excluded from this repository. They must be placed separately at the
paths expected by the service on the server. Server hostname, SSH username, port,
and key paths must be supplied through the deployment/client configuration and
must not be committed to Git.

Example SSH connectivity check:

```bash
ssh <server-user>@<server-host> 'hostname && test -d /NHNHOME/WORKSPACE/26moe002_B/IDEA/JuyoungKim/VLA_TEST/server/vlm_embedding_server'
```

This confirms shell and deployment-path access only. It does not start a retrieval
request or expose the GPU worker publicly.

Run:

```bash
cd /NHNHOME/WORKSPACE/26moe002_B/IDEA/JuyoungKim/VLA_TEST/server/vlm_embedding_server
PYTHONPATH="$PWD:$PWD/incoming/code" \
/home/bk-gnu/miniconda3/envs/welding-rag/bin/python -m service.retrieve \
  --sample-id T_SS_12_0012 --top-k 3
```
