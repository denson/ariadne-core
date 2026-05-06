"""Empirical bug-detection probe — runs the actual production doc 9f143eb3
through the post-fix local chunker and confirms the design §5 4a/4b targets.

This probe is NOT a pytest test. It requires:
  - A valid auth token in keyring for ariadne-core-production.up.railway.app
  - Network access to fetch the doc with include_chunks=true

Run manually with:
  cd src && PYTHONUTF8=1 python ../tests/verification/ariadne--mr6/probe_real_world_9f143eb3.py

CAPTAIN_VERA executed this on the worktree at commit 6414c0d on 2026-05-06
and recorded the result in the verification verdict. The probe is checked in
so the result can be reproduced by anyone with prod auth, and so a future
regression run can verify the empirical anchor still holds.

Recorded result (2026-05-06, commit 6414c0d):
  Reconstructed markdown: 253,775 chars from 318 production (pre-fix) chunks
  POST-FIX chunks: 231
  POST-FIX bucket distribution: {'<10': 0, '10-49': 0, '50-199': 75,
                                 '200-499': 156, '>=500': 0}
  POST-FIX chunks below 50 tokens: 0
  POST-FIX chunks that are bare single-line headings: 0
  Probe 4a (ratio 231/318 = 0.726 < 0.85): PASS
  Probe 4b (zero chunks below 50 tokens): PASS
  Probe 4c (zero bare single-line `## ...` chunks): PASS

This is the strongest possible bug-detection signal short of a post-merge
re-ingest probe (which is PLINY's responsibility, not VERA's).
"""

from __future__ import annotations

import json
import sys
import urllib.request


PROD_HOST = "https://ariadne-core-production.up.railway.app"
DOC_ID = "9f143eb3-18a2-46b5-9176-ed5ad13bd56b"


def main() -> int:
    from ariadne_core_client.auth import get_access_token

    token = get_access_token(PROD_HOST)
    if not token:
        print("ERROR: no auth token available; run `ariadne login` first.")
        return 1

    url = f"{PROD_HOST}/api/documents/{DOC_ID}?include_chunks=true"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        body = json.loads(resp.read())

    chunks = sorted(body["chunks"], key=lambda c: c["chunk_id"])
    md = "\n\n".join(c["text"] for c in chunks)
    print(f"Reconstructed markdown: {len(md):,} chars from {len(chunks)} chunks")

    from pipeline.chunking.chunker import chunk_document
    post = chunk_document(md, "doc-recon", "default", "pdf")
    print(f"POST-FIX chunks: {len(post)}")

    buckets = {"<10": 0, "10-49": 0, "50-199": 0, "200-499": 0, ">=500": 0}
    below_50 = []
    bare = []
    for c in post:
        tc = c.token_count
        if tc < 10:
            buckets["<10"] += 1
        elif tc < 50:
            buckets["10-49"] += 1
        elif tc < 200:
            buckets["50-199"] += 1
        elif tc < 500:
            buckets["200-499"] += 1
        else:
            buckets[">=500"] += 1
        if tc < 50:
            below_50.append((tc, c.text[:90]))
        s = c.text.strip()
        if s.startswith("## ") and s.count("\n") == 0:
            bare.append((tc, s[:90]))

    print(f"POST-FIX bucket distribution: {buckets}")
    print(f"POST-FIX chunks below 50 tokens (sub-floor): {len(below_50)}")
    print(f"POST-FIX bare single-line chunks: {len(bare)}")

    ratio = len(post) / 318
    print()
    print(f"Pre-fix:  318 chunks, 15 below 10 tokens, 33 in 10-49 = 48 sub-floor")
    print(f"Post-fix: {len(post)} chunks, {buckets['<10']} below 10, "
          f"{buckets['10-49']} in 10-49 = {len(below_50)} sub-floor")
    print(f"Probe 4a (ratio < 0.85): {ratio:.3f}  "
          f"-> {'PASS' if ratio < 0.85 else 'FAIL'}")
    print(f"Probe 4b (zero sub-floor): "
          f"-> {'PASS' if len(below_50) == 0 or len(post) <= 1 else 'FAIL'}")
    print(f"Probe 4c (zero bare): "
          f"-> {'PASS' if len(bare) == 0 else 'FAIL'}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
