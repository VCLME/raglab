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
- **Sous v2, les deux runs sont à 0,928 et 0,930.** L'écart publié (0,935 contre 0,895) n'est donc plus observé avec le protocole v2. Il venait en grande partie de ce que le juge ne voyait pas les lignes de version.
- **Ce n'est pas une démonstration de causalité complète :**
  - les deux runs n'ont pas les mêmes réponses, donc la comparaison entre runs n'est pas appariée ;
  - un juge reste un modèle, et 100 réponses par run, c'est peu ;
  - une part de l'écart d'origine peut tenir aux réponses elles-mêmes.
- **Les résultats publiés en v1 restent tels quels.** Les nouveaux runs notés porteront `judge_protocol: faithfulness-presented-context-v2`.
- **L'exactitude des réponses (`answer_correctness`) n'est pas concernée** par ce changement : le juge la note contre la réponse attendue, sans contexte. Sa calibration sur des cas juridiques multilingues reste à faire (audit, hors lot 2).
