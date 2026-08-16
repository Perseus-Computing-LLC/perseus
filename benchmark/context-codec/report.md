# Context Codec benchmark — results (#971)

- dataset: `dataset.json` (`f9b065fd1f501763…`, 5 sessions)
- gate: **PASS**

| session | atoms (crit/safety) | CAR | WAR | round-trip | tokens | fail-closed |
|---|---|---|---|---|---|---|
| codec-01 | 5 (1/1) | 100% | 100% | 100% | 83→255 | ✅ |
| codec-02 | 5 (3/3) | 100% | 100% | 100% | 96→251 | ✅ |
| codec-03 | 5 (2/2) | 100% | 100% | 100% | 92→252 | ✅ |
| codec-04 | 6 (1/1) | 100% | 100% | 100% | 92→283 | ✅ |
| codec-05 | 5 (3/3) | 100% | 100% | 100% | 71→236 | ✅ |

