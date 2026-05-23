# Clinical Accuracy (backend: `gemini`, n=30)

| Pipeline | Acc (strict) | Acc (lenient) | Incorrect | n graded | skipped |
|---|---:|---:|---:|---:|---:|
| raw | 0.333 | 0.483 | 0.367 | 30 | 0 |
| redact | 0.200 | 0.233 | 0.733 | 30 | 0 |
| read_only | 0.000 | 0.000 | 1.000 | 30 | 0 |
| bdp | 0.267 | 0.367 | 0.533 | 30 | 0 |

## Per-category strict accuracy

| Pipeline | longitudinal | lookup | reasoning |
|---|---:|---:|---:|
| raw | 0.500 | 0.300 | 0.200 |
| redact | 0.000 | 0.000 | 0.600 |
| read_only | 0.000 | 0.000 | 0.000 |
| bdp | 0.200 | 0.500 | 0.100 |
