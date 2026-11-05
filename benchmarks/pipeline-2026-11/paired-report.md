`pipeline-2026-11-dedup-off` → `pipeline-2026-11-dedup-on`, same questions, paired.

| Suite | Answers | Correctness (mean) | Fully correct | Faithfulness v2 (mean) | Unsupported claims | False refusals | Complete evidence | Wall p50 / p95 ms |
|---|---|---|---|---|---|---|---|---|
| lexml_fulltext | 100 | 0.710 → 0.700 [-0.030 ; +0.000] | 70 → 69 +0 / −1 (p = 1.00) | 0.990 → 0.990 [+0.000 ; +0.000] | 1 → 1 | 2 → 2 | — | 10605 / 19264 → 12574 / 22837 |
|   ↳ lexml_fulltext: dedup dropped 19 passages in 12 questions; judge protocol faithfulness-presented-context-v2 → faithfulness-presented-context-v2 | | | | | | | | |
| legi_versions | 100 | 0.930 → 0.940 [+0.000 ; +0.025] | 92 → 94 +2 / −0 (p = 0.50) | 0.965 → 0.980 [+0.000 ; +0.035] | 4 → 3 | 0 → 0 | — | 11125 / 18447 → 13788 / 39963 |
|   ↳ legi_versions: dedup dropped 0 passages in 0 questions; judge protocol faithfulness-presented-context-v2 → faithfulness-presented-context-v2 | | | | | | | | |
| eurlex_compliance | 100 | 0.812 → 0.830 [-0.007 ; +0.053] | 79 → 82 +3 / −0 (p = 0.25) | 0.985 → 1.000 [+0.000 ; +0.040] | 2 → 0 | 1 → 1 | — | 11439 / 25429 → 12929 / 28467 |
|   ↳ eurlex_compliance: dedup dropped 2 passages in 2 questions; judge protocol faithfulness-presented-context-v2 → faithfulness-presented-context-v2 | | | | | | | | |
| br_expat | 38 | 0.592 → 0.574 [-0.065 ; +0.012] | 16 → 17 +1 / −0 (p = 1.00) | 1.000 → 1.000 [+0.000 ; +0.000] | 0 → 0 | 0 → 0 | 0.432 → 0.405 +0 / −1 (p = 1.00) | 14449 / 28343 → 14487 / 33621 |
|   ↳ br_expat: dedup dropped 1 passages in 1 questions; judge protocol faithfulness-presented-context-v2 → faithfulness-presented-context-v2 | | | | | | | | |
