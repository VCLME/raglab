# Re-notation des mêmes réponses (protocole du juge v2)

Ce dossier répond au lot 2 de l'audit du 4 novembre 2026. Le rédacteur lit chaque passage avec son en-tête (rang, fichier, score) et, avec l'option `versions`, une ligne de statut. Le juge de fidélité lisait le texte brut des chunks (protocole v1). Le protocole v2 lui donne les passages tels que le rédacteur les a lus : voir [docs/benchmarks/protocole.md](../../docs/benchmarks/protocole.md).

**Méthode.** On reprend les réponses enregistrées dans les rapports détaillés des deux runs du jeu « versions », du 4 novembre 2026, sans les régénérer. On les note deux fois avec le même juge (Gemma 4 26B-A4B, llama.cpp, température 0) : une fois sur le texte brut (v1), une fois sur les passages présentés (v2). Ces passages sont reconstruits à partir des chunks et des versions enregistrés, avec l'horloge figée au 4 novembre 2026 :

```bash
raglab bench rejudge <bench-protocol>/data/reports/recall-legi_versions-20261104-045447.json --clock 2026-11-04 --out benchmarks/judging/recall-legi_versions-20261104-045447-v2.json
raglab bench rejudge <bench-protocol>/data/reports/recall-legi_versions-20261104-041726.json --clock 2026-11-04 --out benchmarks/judging/recall-legi_versions-20261104-041726-v2.json
```

Les deux runs :
- **`versions-full-v1`** (`…-045447`) : filtre `in_force`. Les 100 contextes portent une ligne de version ; fidélité publiée 0,895.
- **`versions-full-all-v1`** (`…-041726`) : sans filtre, aucune annotation ; fidélité publiée 0,935. C'est le témoin : seuls les en-têtes séparent v1 de v2.

## Résultats (mêmes 100 réponses par run, appariées)

| Run | Contextes annotés | Publié (v1) | v1 refait | v2 | Écart v2 − v1 (IC 95 %, bootstrap) | Notées 1,0 seulement en v1 / seulement en v2 | p (McNemar exact) |
|---|---|---|---|---|---|---|---|
| `versions-full-v1` | 100 / 100 | 0,895 | 0,885 | **0,928** | +0,043 [+0,008 ; +0,082] | 0 / 7 | 0,016 |
| `versions-full-all-v1` (témoin) | 0 / 100 | 0,935 | 0,930 | 0,930 | 0,000 [−0,045 ; +0,040] | 5 / 3 | 0,73 |

**Bruit du juge.** Refaire la notation v1 change la note de 2 réponses sur 100 dans le premier run, et de 5 dans le témoin. C'est l'ordre de grandeur de la variabilité d'une passe à l'autre, à température 0.

## Ce qu'on peut en dire

- **Sur les réponses à contexte annoté, la notation v2 relève la fidélité de façon significative** (+0,043, 7 réponses notées 1,0 en v2 seulement, aucune dans l'autre sens). Sur le témoin, sans annotation, les en-têtes seuls ne changent rien de mesurable.
- **Les deux runs se comparent question par question.** Ils portent sur les mêmes 100 questions (identifiants vérifiés : 100 en commun, aucun d'un seul côté), même si leurs réponses diffèrent. Une première version de ce document les disait non appariables ; c'était faux (corrigé après la contre-relecture des PR #83 à #85).

  Écart de fidélité, run filtré (`versions-full-v1`) moins run sans filtre (`versions-full-all-v1`), sur les mêmes questions. Intervalle à 95 % par bootstrap apparié ; McNemar exact sur les réponses notées 1,0 d'un seul côté :

  | Notation | Sans filtre | Filtre `in_force` | Écart (IC 95 %) | Notées 1,0 seulement sans filtre / seulement avec filtre | p |
  |---|---|---|---|---|---|
  | publiée (v1) | 0,935 | 0,895 | −0,040 [−0,090 ; +0,015] | 13 / 6 | 0,17 |
  | v1 refaite | 0,930 | 0,885 | −0,045 [−0,105 ; +0,020] | 14 / 6 | 0,12 |
  | v2 | 0,930 | 0,928 | −0,002 [−0,055 ; +0,050] | 8 / 9 | 1,0 |

- **Ce qu'on en conclut :**
  - la baisse publiée (0,935 → 0,895) n'était **pas significative**, même dans le protocole v1 ;
  - en v2, l'écart moyen tombe à −0,002 ;
  - **une différence non significative ne démontre pas l'équivalence** : avec 100 questions, l'intervalle laisse encore la place à un écart de ±5 points ;
  - ce qui est établi, c'est l'effet du protocole sur les mêmes réponses (tableau précédent).
- **Limites :** un juge reste un modèle, et 100 réponses par run, c'est peu. Une part de l'écart d'origine peut tenir aux réponses elles-mêmes, qui diffèrent d'un run à l'autre.
- **Les résultats publiés en v1 restent tels quels.** Les nouveaux runs notés porteront `judge_protocol: faithfulness-presented-context-v2`.
- **L'exactitude des réponses (`answer_correctness`) n'est pas concernée** par ce changement : le juge la note contre la réponse attendue, sans contexte. Sa calibration sur des cas juridiques multilingues reste à faire (audit, hors lot 2).

## Artefact de preuve

`proof-<rapport>-v2.jsonl`, un par run, permet de vérifier la re-notation sans relancer le juge. Le corpus est public : codes consolidés de Légifrance. La première ligne décrit le run : rapport source et son empreinte, juge, horloge, protocoles, commit. Chaque ligne suivante contient, pour une réponse :
- la question et la réponse enregistrée ;
- le contexte du rédacteur dans les deux protocoles (texte brut v1, passages présentés v2) ;
- les notes du juge (publiée v1, v1 refaite, v2) et leurs raisons ;
- les empreintes sha256 de la réponse et de chaque passage.

```bash
python scripts/judging_proof.py benchmarks/judging/<re-notation>.json <rapport>.json benchmarks/judging/proof-<rapport>-v2.jsonl
python scripts/judging_proof.py --verify benchmarks/judging/proof-<rapport>-v2.jsonl <rapport>.json
```

`--verify` reconstruit les contextes à partir du rapport détaillé et contrôle chaque empreinte. Pour les deux runs « versions », il est passé sans écart. Les rapports détaillés eux-mêmes ne sont pas versionnés (ils pèsent 3 Mo chacun). L'artefact contient déjà les contextes, ce qui suffit à refaire la notation.

