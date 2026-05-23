# BDP Ablation Study

Embedder: `sbert`. Same corpus and queries as `summary.md`.

| Variant | R@1 | R@5 | R@10 | MRR | ID leak | $\Delta$ R@5 vs BDP |
|---|---:|---:|---:|---:|---:|---:|
| **bdp (full)** | 0.053 | 0.320 | 0.539 | 0.321 | 0.000 | --- |
| bdp_no_format | 0.005 | 0.073 | 0.105 | 0.127 | 0.000 | -0.247 |
| bdp_no_category | 0.064 | 0.232 | 0.287 | 0.267 | 0.000 | -0.088 |
| bdp_no_hmac | 0.003 | 0.018 | 0.066 | 0.056 | 0.000 | -0.301 |
