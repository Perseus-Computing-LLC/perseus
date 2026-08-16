# CCRM retry-isolation benchmark — results (#972)

- simulation: 4000 seeded trials, cascade ratio 7.1x (paper: ~7.1x)
- gate: **PASS**

| policy | pass@3 |
|---|---|
| IID (overestimate) | 99.5% |
| contaminated cascade | 88.8% |
| clean restart (fenced) | 99.5% |

- IID overestimate: **10.63pp** (paper: 17.4pp on SWE-bench Verified; gate ≥ 8pp)
- clean-restart recovery: **10.63pp** (gate ≥ 8pp)
- allocation: T* = 87.853 → 16 attempts from budget 1000.0
- fence demo: 3 turns quarantined, summary 58 tokens, event digest `15e281f26f598d21…`

