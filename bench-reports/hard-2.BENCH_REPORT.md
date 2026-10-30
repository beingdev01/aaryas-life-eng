# Engineering benchmark report

- Run: hard-2
- Finished: 2026-10-30 23:36:41 IST (2026-10-30T18:06:41Z)

## Quality suite
Depth 4. Hidden tests are written only after the build, so neither mode can code to them.

| mode | tests passed | rate | tasks fully solved | seconds | lane calls | cost |
|---|---|---|---|---|---|---|
| baseline | 10/20 | 50% | 1/2 | 233.7 | 2 | 0.0 |
| engine | 19/20 | 95% | 1/2 | 3702.2 | 17 | 0.0 |

The pipeline moved the hidden-test pass rate from 50% to 95% (+45%), on the same free models, at a total reported cost of 0.0.

### Per task

| task | mode | passed | rate | seconds | note |
|---|---|---|---|---|---|
| expr-eval | baseline | 0/10 | 0% | 134.1 |  |
| expr-eval | engine | 9/10 | 90% | 1822.0 |  |
| justify-text | baseline | 10/10 | 100% | 99.6 |  |
| justify-text | engine | 10/10 | 100% | 1880.2 | FAILED |
