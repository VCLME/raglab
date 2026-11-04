# Routage multilingue et abstention par langue

Suite de [langues-croisees.md](langues-croisees.md). Le routeur (phase 9.4, [routing.md](routing.md)) prend deux décisions sur l'embedding de la question : le corpus, avant la recherche, et l'abstention, après. Pour une question posée dans une autre langue que son corpus, les deux se trompaient. Le routage multilingue de #76 (`RAGLAB_ROUTING_CROSS_LANGUAGE`, activé par défaut) en corrige l'essentiel ; ce document compare d'autres corrections, toutes **sans LLM supplémentaire dans le routeur**, et recalibre l'abstention par langue.

Résultat en une phrase : des seuils d'abstention **par (langue, corpus)** gardent 58 refus justifiés sur 80 au lieu de 46 (+12, aucun perdu, p < 0,001), sans perte sur les questions françaises ni portugaises, avec 4,0 % de faux refus. Le choix du corpus sur des **questions exemples** route 96 questions françaises sur 100 vers LexML (84 aujourd'hui) mais fait perdre des questions PIAF : il reste désactivé. L'objectif de rappel 0,85 n'est pas atteint (0,725) : même un seuil réglé sur les questions évaluées plafonne vers 0,75.

## Le protocole

Mêmes jeux que #76 : les 100 questions françaises de `lexml_fr`, les mêmes 100 en portugais (`lexml_fr_pt`), 100 questions PIAF (graine 42, le même tirage), les 80 questions d'abstention ; le routeur choisit entre `bench_piaf_fr` et `bench_lexml_pt` ; pipeline de production (hybride, re-ranking, citations, traduction de la question).

**Une seule passe GPU, toutes les politiques rejouées hors ligne.** `raglab experiment routing-languages` ([`routing_languages.py`](../src/raglab/experiments/routing_languages.py)) ne route pas : il cherche chaque question **sur chaque corpus candidat** et enregistre tout ce que les politiques lisent : similarité aux centroïdes des passages et des questions exemples (question d'origine et traduite), meilleur cosinus dense (question d'origine et traduite), meilleur score du re-ranker, passage attendu trouvé ou non, temps de chaque étape. Chaque réglage est ensuite rejoué sur exactement les mêmes recherches. Le rejeu du réglage par défaut redonne au chiffre près la mesure en direct de #76 (75 / 85 / 94 répondues, 46 refus, 2,3 % de faux refus), ce qui valide la méthode.

```bash
raglab experiment routing-languages                       # collecte (GPU, ~1 h) puis tableau
raglab experiment routing-languages --replay rapport.json # rejeu seul, sans GPU
```

Rapport : [`router-languages-collect-v1.json`](../benchmarks/routing/router-languages-collect-v1.json) (4 novembre 2026).

**Questions de calibration, disjointes des questions évaluées.** Les 175 questions LexML candidates de `lexml_fr` (naturelles, sans numéro d'article ni de loi) n'avaient servi qu'à 100 tirages ; les **75 restantes** forment le jeu de calibration, traduites en français avec les mêmes règles que le jeu figé ([`benchmarks/lexml_fr/`](../benchmarks/lexml_fr/README.md), `calibration.jsonl` et `calibration_pt.jsonl`, `python scripts/build_lexml_fr.py --calibration`). Disjoint par construction : aucun découpage dev/test des 100 questions figées n'a été nécessaire, et les chiffres ci-dessous portent sur les 100 complètes, comparables à #76. Pour PIAF, 100 questions tirées (graine 43) hors des 100 évaluées. Groupes de calibration : (fr, LexML) 75, (pt, LexML) 75, (fr, PIAF) 100. Les mêmes questions servent d'exemples pour l'approche (c), dans [`benchmarks/routing/corpus_examples.jsonl`](../benchmarks/routing/corpus_examples.jsonl).

**Règle de choix** (propriétaire) : marge d'intention 0,02 ; seuils par corpus calibrés sur la source de score mesurée, jamais empruntés à l'autre ; pas de seuil global ; le meilleur réglage refuse le plus de questions à refuser avec **moins de 5 %** de faux refus ; objectif de rappel 0,85. Dans chaque famille, le quantile (ou le z) est choisi par cette règle parmi 1, 2, 3, 5, 10 % (z : 1,5 à 3).

## Les approches

| | Idée | Retenue ? |
|---|---|---|
| (a) | seuils par (langue, corpus), calibrés sur des questions de chaque langue | **oui, derrière une option** |
| (b) | score normalisé par (langue, corpus) : z-score | non, équivalent à (a) en moins bien |
| (c) | corpus choisi sur les centroïdes de questions exemples par langue | non, derrière une option |
| (d) | score du re-ranker pour l'abstention, calibré par langue | non |
| (e) | re-notation de #76 combinée avec les précédentes | gardée telle quelle avec (a) ; abandonnée avec (c) |

- **(b)** Un seuil au même quantile de chaque distribution (langue, corpus) **est déjà** une normalisation par quantile : (a) et la normalisation par quantile prennent exactement les mêmes décisions. Reste le z-score, qui suppose des scores à peu près gaussiens : mesuré, il fait un peu moins bien que (a) (55 refus, 3,0 %).
- **(d)** Le cross-encoder ne sépare pas mieux que le cosinus sur ces questions : 56 refus mais 3 perdus face au défaut (refus gagnés ailleurs), à 4,3 % de faux refus. Ses seuils par langue sont calibrés et livrés pour la source `rerank`, sans gain à signaler.
- **br_expat** n'est pas mesuré ici : son corpus (`bench_br_expat`) n'est pas un des deux corpus candidats du jeu de #76, et 38 questions n'ajouteraient pas de puissance.

## Résultats

Rejeu hors ligne ; McNemar apparié face au **défaut actuel** (routage multilingue de #76, marge 0,02, seuils du point A). Répondues = bien routées, non refusées, passage attendu dans le top 5 (sur 100). Refus gardés : questions à refuser effectivement refusées (sur 80). Faux refus : questions in-scope refusées (sur 300). Latence : routeur + recherche, questions françaises sur LexML.

| Réglage | Corpus | Abstention | FR bien routées | Répondues FR | Répondues PT | Répondues PIAF | Refus gardés | Faux refus | p50 / p95 FR |
|---|---|---|---|---|---|---|---|---|---|
| **défaut** (#76) | passages + re-notation 0,02 | dense max(orig., trad.), seuils point A | 84 | 75 | 85 | 94 | 46 | 2,3 % | 2 835 / 4 066 ms |
| sans #76 | passages | dense, seuils point A | 62 | 33 (−42, p < 0,001) | 87 (+2, n.s.) | 94 | 50 (+4, n.s.) | 11,7 % | 2 662 / 3 955 ms |
| **(a)** | passages + re-notation 0,02 | **dense (question d'origine), par (langue, corpus), q 3 %** | 84 | 75 | 85 | 91 (−3, n.s.) | **58 (+12 / −0, p < 0,001)** | 4,0 % | 2 777 / 3 955 ms |
| (a) sur le score traduit | passages + re-notation 0,02 | dense max(orig., trad.), par (langue, corpus), q 3 % | 84 | 75 | 85 | 91 (−3, n.s.) | 56 (+10, p = 0,002) | 4,0 % | 2 835 / 4 066 ms |
| recalibration par corpus seule | passages + re-notation 0,02 | dense max(orig., trad.), par corpus, q 3 % | 84 | 75 | 85 | 91 (−3, n.s.) | 56 (+10, p = 0,002) | 4,0 % | 2 835 / 4 066 ms |
| (b) z-score | passages + re-notation 0,02 | dense max(orig., trad.), z = 2 par (langue, corpus) | 84 | 75 | 85 | 93 (−1, n.s.) | 55 (+9, p = 0,004) | 3,0 % | 2 835 / 4 066 ms |
| (d) re-ranker par corpus | passages + re-notation 0,02 | re-ranker, par corpus, q 2 % | 84 | 76 (+1, n.s.) | 85 | 93 (−1, n.s.) | 56 (+13 / −3, p = 0,021) | 4,7 % | 2 777 / 3 955 ms |
| (d) re-ranker par langue | passages + re-notation 0,02 | re-ranker, par (langue, corpus), q 1 % | 84 | 76 (+1, n.s.) | 85 | 93 (−1, n.s.) | 56 (+13 / −3, p = 0,021) | 4,3 % | 2 777 / 3 955 ms |
| (c) | questions exemples | dense max(orig., trad.), seuils point A | **96** | **84 (+9, p = 0,004)** | 87 (+2, n.s.) | 91 (−3, n.s.) | 50 (+4, n.s.) | 2,7 % | 2 912 / 4 066 ms |
| (c) + (a) | questions exemples | dense, par (langue, corpus), q 5 % | 96 | 83 (+8, p = 0,008) | 84 (+1 / −2, n.s.) | 87 (**−7, p = 0,016**) | 64 (+18, p < 0,001) | 4,7 % | 2 855 / 3 955 ms |
| (c) + (e) | questions exemples + re-notation 0,02 | dense max(orig., trad.), seuils point A | 99 | 86 (+11, p < 0,001) | 87 (+2, n.s.) | 86 (**−8, p = 0,008**) | 52 (+6, p = 0,031) | 3,3 % | 2 912 / 4 066 ms |
| (c) + (e) + (d) | questions exemples + re-notation 0,02 | re-ranker, par (langue, corpus), q 3 % | 99 | 88 (+13, p < 0,001) | 87 (+2, n.s.) | 84 (**−10, p = 0,002**) | 62 (+19 / −3, p < 0,001) | 4,3 % | 2 855 / 3 955 ms |

(c) + (e) + (a) : aucun quantile ne reste sous 5 % de faux refus.

Seuils de (a), quantile 3 % de chaque groupe de calibration (cosinus dense de la question d'origine) :

| Corpus | Français | Portugais | Autre langue |
|---|---|---|---|
| `bench_lexml_pt` | 0,8095 | 0,8611 | 0,8485 (seuil du corpus) |
| `bench_piaf_fr` | 0,797 | 0,7929 (seuil du corpus) | 0,7929 (seuil du corpus) |

### Ce que montrent ces chiffres

**L'écart de langue sur l'abstention est réel et mesurable.** Le cosinus d'une question française sur les passages portugais de LexML est bien plus bas : quantile 3 % à 0,8095 pour les questions françaises contre 0,8611 pour les mêmes en portugais. Un seuil unique par corpus calibré sur la langue du corpus (0,8611), appliqué au score de la question d'origine, refuse 72 des 100 questions françaises et n'en laisse que 14 répondues ; #76 le contournait en relisant le score sur la question traduite (une recherche dense de plus, et seulement si le rédacteur répond). Un seuil par langue fait aussi bien sur le français (75 répondues dans les deux cas), **sans question traduite** : il n'a besoin ni du rédacteur ni d'une seconde recherche, et reste juste quand la traduction échoue.

**D'où viennent les 12 refus gagnés.** De la calibration, pour l'essentiel : sur les 75 questions portugaises naturelles du jeu de calibration, le quantile 3 % est à 0,8611, plus haut que l'ancien seuil 0,8485 (calibré sur un tirage de `lexml_fulltext` qui mélangeait des questions à numéro de loi, au cosinus plus bas, alors qu'elles ne sont jamais refusées quand le texte cité est dans l'index). Le seuil plus haut rattrape des questions portugaises hors sujet. Recalibrer par corpus sur le score traduit donne déjà +10 ; le seuil par langue sur la question d'origine en ajoute 2 (58). Le prix : 3 questions PIAF refusées à tort (n.s.) et 4,0 % de faux refus au total, sous le plafond.

**Le choix du corpus sur questions exemples corrige le français, pas gratuitement.** Le centroïde des passages mêle le sujet et la langue ; comparer la question à des questions de chaque langue sur chaque corpus enlève la langue de l'équation : 96 questions françaises sur 100 vont vers LexML (84 avec #76), sans appel au rédacteur, et les questions portugaises hors sujet restent sur LexML et son seuil plus haut (les 4 refus perdus par #76 reviennent). Mais 3 questions PIAF partent vers LexML (marges de 0,002 à 0,006), et la perte grandit dès qu'on resserre les seuils (−7, p = 0,016) ou qu'on ajoute la re-notation de #76 (−8, p = 0,008). Les questions exemples ont aussi un biais favorable : elles viennent des mêmes jeux que les questions évaluées (même style, même rédacteur pour LexML) ; sur des questions réelles d'utilisateurs, l'écart serait plus petit. L'option reste désactivée.

**Pourquoi l'objectif de rappel 0,85 n'est pas atteint.** 30 des 80 questions sont conversationnelles et toutes refusées par l'intention ; il reste 50 questions hors sujet ou « presque dans le sujet ». Même en réglant les seuils par corpus directement sur les questions évaluées (un plafond optimiste), le rappel ne dépasse pas 0,75 à moins de 5 % de faux refus, sur le score dense comme sur le re-ranker. Les questions manquées ont des scores dans la zone des questions in-scope : questions de culture générale françaises routées vers PIAF (« Quel joueur a remporté le Ballon d'or en 2023 ? », re-ranker −3,3), demandes de tâche ou personnelles en portugais routées vers LexML (« Calcule os juros compostos… », cosinus 0,894). Ce n'est plus un problème de langue ni de seuil : c'est l'intention (9.4) ou le contenu, hors du périmètre de ce travail.

### Confirmation en direct

Le réglage (a) a été mesuré en direct avec `raglab experiment routing` (même commande que #76, `RAGLAB_ROUTING_LANGUAGE_THRESHOLDS=true`), 4 novembre 2026 : [`router-language-thresholds-v1.json`](../benchmarks/routing/router-language-thresholds-v1.json). Il redonne exactement le rejeu. McNemar apparié face à la mesure en direct du défaut ([`router-crosslang-m02-v1.json`](../benchmarks/routing/router-crosslang-m02-v1.json)) :

| | Défaut (#76) | Seuils par langue | Écart apparié |
|---|---|---|---|
| Français → LexML, bien routées | 84 | 84 | |
| Répondues depuis le bon passage, français | 75 | 75 | 0 / 0 |
| Répondues, mêmes questions en portugais | 85 | 85 | 0 / 0 |
| Répondues, PIAF | 94 | 91 | 0 gagnée, 3 perdues, p = 0,25 (n.s.) |
| Refus gardés (sur 80) | 46 | **58** | 12 gagnés, 0 perdu, p < 0,001 |
| Faux refus (sur 300) | 7 (2,3 %) | 12 (4,0 %) | sous le plafond de 5 % |
| Précision / rappel de l'abstention | 0,868 / 0,575 | 0,829 / 0,725 | |
| Latence routeur + recherche p50 / p95, français | 2 696 / 3 710 ms | 2 698 / 3 626 ms | |
| p50 / p95, portugais | 719 / 947 ms | 645 / 873 ms | |
| p50 / p95, PIAF | 524 / 583 ms | 479 / 509 ms | |

Face à la mesure sans #76 ([`router-crosslang-off-v1.json`](../benchmarks/routing/router-crosslang-off-v1.json)) : 50 → 58 refus (9 gagnés, 1 perdu, p = 0,021), faux refus 35 → 12. Les 4 refus que #76 avait perdus sont donc plus que rattrapés. Par catégorie : conversationnelles 30/30, hors périmètre 16/27, « presque dans le sujet » 12/23.

## Options

| Option | Défaut | Variable | Effet |
|---|---|---|---|
| Seuils par langue | non | `RAGLAB_ROUTING_LANGUAGE_THRESHOLDS`, tables `RAGLAB_ROUTING_LANGUAGE_ABSTENTION_THRESHOLDS` (dense) et `RAGLAB_ROUTING_RERANK_LANGUAGE_ABSTENTION_THRESHOLDS` (re-ranker), JSON corpus → langue → seuil | le seuil de la langue de la question passe avant celui du corpus ; une langue sans valeur garde le seuil du corpus ; l'abstention lit alors le score de la question d'origine (la recherche dense sur la question traduite de #76 n'est plus faite) |
| Corpus sur questions exemples | non | `RAGLAB_ROUTING_CORPUS_EXAMPLES`, `RAGLAB_ROUTING_CORPUS_EXAMPLES_PATH` (JSONL `corpus`, `language`, `question`) | chaque corpus est noté sur le centroïde de ses questions exemples dans la langue la plus proche ; seulement si tous les corpus candidats ont des exemples |

Ce sont des réglages du routeur, comme `RAGLAB_ROUTING_CROSS_LANGUAGE` : la requête (CLI `--routing`, API `routing: true`, interface : interrupteur « Routage ») les applique. En mode expert, le panneau du routeur affiche la base de notation des corpus (passages ou questions exemples), les scores d'origine et traduit d'un corpus re-noté, et le score dense de la question traduite quand il est lu.

## Décision proposée au propriétaire

Activer les **seuils par langue** par défaut : +12 refus justifiés sur 80 (p < 0,001, aucun perdu), français et portugais inchangés, PIAF −3 (n.s.), faux refus 2,3 % → 4,0 %, une recherche dense de moins par question traduite. L'option reste désactivée tant que le propriétaire n'a pas tranché. Le choix du corpus sur questions exemples reste désactivé : gain net sur le français, perte significative sur PIAF dès qu'on le combine.

## Limites

- Le quantile est choisi sur les questions évaluées, comme pour le point A ; les seuils eux-mêmes viennent de la calibration disjointe.
- 75 questions de calibration par langue sur LexML : le quantile 3 % est la deuxième plus basse ; un point de quantile déplace le seuil de quelques millièmes.
- Les questions françaises sont des traductions (écrites par un LLM, relues sur échantillon pour le jeu figé, pas pour la calibration) : une question spontanée peut s'en écarter.
- Deux corpus seulement : un corpus sans questions de calibration garde son seuil par corpus, et l'option (c) ne s'applique que si tous les candidats ont des exemples.
