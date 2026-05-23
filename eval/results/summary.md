# BDP Eval -- bootstrap run

Embedder: `sbert`

| Pipeline | R@1 | R@5 | R@10 | MRR | ID leak |
|---|---:|---:|---:|---:|---:|
| raw | 0.054 | 0.430 | 0.616 | 0.420 | 1.000 |
| redact | 0.002 | 0.018 | 0.060 | 0.053 | 0.000 |
| read_only | 0.001 | 0.021 | 0.046 | 0.064 | 0.674 |
| bdp | 0.053 | 0.320 | 0.539 | 0.321 | 0.000 |

## Recall@5 by query category

| Pipeline | longitudinal | lookup | reasoning |
|---|---:|---:|---:|
| raw | 0.335 | 0.372 | 0.630 |
| redact | 0.027 | 0.000 | 0.037 |
| read_only | 0.038 | 0.000 | 0.037 |
| bdp | 0.199 | 0.326 | 0.444 |
