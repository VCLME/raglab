# Pipeline fusionné, paramètres de production (novembre 2026)

Lot 4 de la contre-relecture des PR #83 à #85. Ce lot mesure le pipeline une fois les trois corrections fusionnées : intégrité des benchmarks (#86), déduplication par inclusion stricte (#87), preuves et juge vérifiable (#88). La mesure est faite avec les paramètres de production, déduplication désactivée puis activée, sur les mêmes questions, et les deux runs sont appariés.

Rien n'a été relancé ni recalculé à la main. Les chiffres viennent des fichiers de ce dossier et de `benchmarks/results/pipeline-2026-11-dedup-{off,on}.json`.

## Fiche de configuration

| Élément | Valeur |
|---|---|
| Code | branche `measure/pipeline-2026-11` : `origin/main` (4d3c072) + #86 + #87 + #88. Run « off » au commit `677286f`, run « on » au commit `ff68fe3` (seul ajout entre les deux : `scripts/pipeline_report.py`, qui ne touche pas au pipeline) |
| Commande | `raglab bench all --suite br_expat --suite legi_versions --suite lexml_fulltext --suite eurlex_compliance --ragas-limit 100 --generator-provider llamacpp --generator-profile qwen35b-moe-rag --no-dedup` puis `--dedup` |
| Options résolues | découpage `traditional`, recherche `hybrid` (poids lexical 0,5, RRF k = 60), reranking `BAAI/bge-reranker-v2-m3` sur GPU (40 candidats), `top_k` 5, résolution des citations active, versions `in_force`, traduction de la question active, graphe désactivé ; déduplication : réserve de 40 passages, inclusion stricte |
| Modèles | embeddings `intfloat/multilingual-e5-small` (CPU) ; rédaction `qwen35b-moe-rag` (llama.cpp) ; juge `gemma4-26b-a4b` (llama.cpp, autre famille que le rédacteur) |
| Protocole du juge | `faithfulness-presented-context-v2` (passages tels que présentés au rédacteur), sur les 100 premières questions de chaque jeu (38 pour br_expat) |
| Horloge | date du jour (2026-11-05), aucun `as_of` |
| Corpus et index | `bench_lexml_pt` (index `63b704a5`, 252 documents, empreinte `c6673250c61c`) ; `bench_legi_consommation_fr` (`e6521653`, 5 998 documents, `7ddeda0e4e94`) ; `bench_eurlex_compliance` (`cb69410c`, 4 236 documents, `549d2d09b317`) ; `bench_br_expat_pt` (`0e88055e`, 19 documents, `0d844e2742b1`). Le contrôle d'intégrité (#86) est passé sans problème pour les quatre corpus et les deux runs |
| Caches | cache du reranker et cache de traduction vides au début de chaque jeu (taux de réutilisation < 0,5 %) |
| Replis | un seul, dans le run « on » : la traduction de brx-17 a échoué (`writer_unavailable`, 20 s) parce que le modèle de rédaction était encore en train de charger ; la recherche s'est faite sur la question française |
| Matériel | RTX 3070 Ti Laptop 8 Go, 32 Go de RAM, Windows 11 ; 5 min de refroidissement entre les étapes |

Le champ `environment.generation_model` des fichiers de résultats indique `ollama:qwen2.5:7b`. C'est la valeur par défaut des réglages, pas le modèle utilisé : le champ `generator` (`llamacpp:qwen35b-moe-rag`) fait foi.

## Résultats

### Recherche

| Jeu | Recall@5 off → on | Questions où des passages ont été retirés | Effet |
|---|---|---|---|
| lexml_fulltext (277) | 0,823 → 0,830 | 12 (19 passages) | +2 / −0 (lexml-0017, lexml-0128, toutes deux parmi les 12) |
| legi_versions (100) | 0,930 → 0,930 | 0 | aucun : les deux runs donnent exactement les mêmes contextes |
| eurlex_compliance (300) | 0,717 → 0,717 | 2 | MRR 0,5861 → 0,5864 |
| br_expat (38) | 0,684 → 0,658 | 1 (brx-28) | −1 (brx-17), dû au repli de traduction et non à la déduplication |

Les deux gains LexML sont ceux déjà observés au lot 3.

Sur brx-28, la question qui avait motivé la déduplication, un passage a été retiré et sa place a été remplie plus bas dans la liste. La réponse n'a pas changé : le bon passage n'est toujours pas dans le top 5, et le modèle répond toujours 25 % au lieu de 1,10 % et 3,5 %.

### Réponses (`paired-report.md`)

| Jeu | Exactitude (moyenne) | Entièrement correctes | Fidélité v2 | Affirmations non étayées | Faux refus |
|---|---|---|---|---|---|
| lexml_fulltext | 0,710 → 0,700 [−0,030 ; +0,000] | 70 → 69 (+0 / −1, p = 1,00) | 0,990 → 0,990 | 1 → 1 | 2 → 2 |
| legi_versions | 0,930 → 0,940 [+0,000 ; +0,025] | 92 → 94 (+2 / −0, p = 0,50) | 0,965 → 0,980 | 4 → 3 | 0 → 0 |
| eurlex_compliance | 0,812 → 0,830 [−0,007 ; +0,053] | 79 → 82 (+3 / −0, p = 0,25) | 0,985 → 1,000 | 2 → 0 | 1 → 1 |
| br_expat | 0,592 → 0,574 [−0,065 ; +0,012] | 16 → 17 (+1 / −0, p = 1,00) | 1,000 → 1,000 | 0 → 0 | 0 → 0 |

Les intervalles sont des bootstraps appariés, par grappes pour br_expat (une paraphrase est tirée avec sa question d'origine). Les tests sur les réponses entièrement correctes sont des McNemar exacts. Aucun écart n'est significatif.

**Bruit de base.** Sur legi_versions, la déduplication n'a rien retiré et les 100 contextes sont identiques d'un run à l'autre. Pourtant, seules 40 réponses sont identiques mot pour mot, et 5 questions changent de note (exactitude ou fidélité). L'écart « +2 entièrement correctes » de ce jeu est donc du bruit pur, venu du rédacteur et du juge.

Sur les autres jeux, la plupart des changements de note tombent aussi sur des questions dont le contexte est identique. Aucune des questions où un passage a été retiré n'a changé de note. On ne peut donc attribuer à la déduplication aucun gain ni aucune perte au niveau des réponses.

### Niveaux de preuve (br_expat, groupes non relus)

| Niveau | Off | On |
|---|---|---|
| Article | 0,703 | 0,676 |
| Disposition | 0,541 | 0,514 |
| Preuves complètes | 0,432 | 0,405 |

Le seul changement est brx-17, qui passe de tout trouvé à rien trouvé à cause du repli de traduction. Les groupes de preuves de `evidence_v1.jsonl` sont une proposition automatique : ces niveaux ne seront publiables qu'après relecture humaine.

### Latence (`latency-br_expat-dedup-{off,on}.json`)

Profil mesuré sur br_expat, 38 questions, dans un seul processus, avec les réglages par défaut de l'API :

| | Off | On |
|---|---|---|
| Première question (chargement des modèles) | 56,6 s | 78,0 s |
| Caches vides, p50 / p95 | 13,5 s / 20,1 s | 13,6 s / 19,2 s |
| Caches chauds, p50 / p95 | 9,9 s / 16,9 s | 9,7 s / 16,0 s |
| Étape `dedup` (p50) | — | 3,8 ms (vides), 4,4 ms (chauds) |

Sur une réponse, le temps se répartit à peu près ainsi : 85 % pour la rédaction (environ 11 s), 1,75 s pour la traduction quand le cache est vide, 0,5 s pour le reranker, et moins de 0,1 s pour le reste.

Les caches chauds économisent la traduction et le reranking, soit 1,8 s de recherche contre 0,08 s, mais pas la rédaction. La déduplication coûte 4 ms.

L'écart sur la première question ne vient pas de la déduplication : c'est le temps de chargement du rédacteur par llama.cpp, qui varie d'un démarrage à l'autre.

Les latences par jeu du tableau apparié (`Wall p50 / p95`) varient aussi d'un run à l'autre sans lien avec la déduplication : legi_versions, aux contextes identiques, passe de 11,1 s à 13,8 s. Le débit du rédacteur est tombé de 22 à 19 jetons/s pendant le deuxième run, ce qui ressemble à un effet thermique. Pour la latence, c'est le profil ci-dessus qu'il faut lire.

### Mémoire GPU

| Étape | Pic | Avant le run |
|---|---|---|
| Bench complet, off (rédacteur + juge + reranker) | 7 871 Mio | — |
| Bench complet, on | 7 944 Mio | — |
| Profil de latence, off (rédacteur + reranker) | 7 302 Mio | 741 Mio |
| Profil de latence, on | 7 272 Mio | 746 Mio |

Le budget de 8 Go (8 192 Mio) tient dans les quatre cas. La déduplication ne charge aucun modèle.

## Effet de bord trouvé : l'ordre des passages épinglés

La déduplication n'est pas qu'un filtre. Quand elle est activée, le reranker renvoie ses 40 candidats au lieu de 5, pour la réserve. Or `merge_with_citation` ordonne les tranches d'un article cité selon leur position dans cette liste.

Avec 5 candidats, les tranches absentes du top gardent l'ordre de lecture de l'article. Avec 40, elles sont classées par le reranker. Pour un long article cité, le top 5 peut donc contenir d'autres tranches, même si aucun passage n'est retiré.

Questions où la déduplication n'a rien retiré mais où le top 5 diffère :

| Jeu | Autre ensemble de passages | Même ensemble, autre ordre |
|---|---|---|
| lexml_fulltext | 7 | 5 |
| eurlex_compliance | 9 | 8 |
| legi_versions | 0 | 0 |
| br_expat | 1 (brx-17, le repli de traduction) | 0 |

Aucune de ces questions ne change de recall@5. Une seule change de note : lexml-0053 passe de 1,0 à 0,0 en exactitude, avec un contexte qui diffère par une tranche de l'article cité. Avec le bruit mesuré plus haut, on ne peut pas dire si c'est la tranche ou le rédacteur.

## Recommandation sur la déduplication

**Garder la déduplication comme option, désactivée par défaut, et ne pas l'activer en production en l'état.**

- **Ce qu'elle apporte.**
  - Deux questions LexML retrouvées (+2 / −0), confirmées sur deux runs indépendants (lot 3 et lot 4). C'est un gain de recherche réel mais petit, non significatif à lui seul.
  - Aucun gain mesurable sur les réponses : tous les écarts sont dans le bruit du rédacteur et du juge.
  - Elle ne corrige pas brx-28, le cas qui l'avait motivée.
- **Ce qu'elle coûte.**
  - 4 ms et aucune mémoire GPU.
  - Elle n'a fait perdre aucune question sur les 715 des quatre jeux, alors que la v1 en perdait 6.
- **Ce qui empêchait de l'activer par défaut au moment de la mesure.** L'effet de bord sur l'ordre des passages épinglés : activer l'option change le top 5 de 16 questions qu'elle ne touche pas. Une option censée seulement retirer des doublons ne devrait rien changer quand elle ne retire rien.

**Corrigé depuis, dans #92.** Les tranches épinglées sont maintenant ordonnées à partir des `top_k` premiers passages du reranker, dans les deux modes. La réserve de 40 ne sert plus qu'à remplacer des passages retirés.

La recherche a été remesurée avec le correctif (runs `pinned-order-dedup-{off,on}`, voir [docs/deduplication.md](../../docs/deduplication.md)) :
- plus aucune question non touchée ne change de top 10 ;
- sans déduplication, les passages sont identiques à ceux de ce run sur les 715 questions ;
- les deux gains LexML restent.

Les réponses n'ont pas été rejugées après le correctif. La recommandation ne change pas : l'option reste désactivée par défaut, puisque son seul gain mesuré tient en deux questions.

Avant de pouvoir conclure sur les réponses, il faudrait aussi réduire le bruit de mesure, par exemple en fixant la graine du rédacteur ou en notant plusieurs tirages par question.

## Fichiers

- `paired-report.md` : sortie de `scripts/pipeline_report.py pipeline-2026-11-dedup-off pipeline-2026-11-dedup-on`.
- `latency-br_expat-dedup-off.json`, `latency-br_expat-dedup-on.json` : sorties de `scripts/latency_profile.py`.
- `../results/pipeline-2026-11-dedup-{off,on}.json` : résultats des deux runs. Les rapports détaillés qu'ils citent (`data/reports/recall-*-20261105-*.json`) restent locaux, comme les corpus.
