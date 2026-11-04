# Intention et abstention : voisins proches, règle jointe et généralisation

> **Mise à jour (deuxième partie, plus bas).** L'option de #80 ne généralise pas aux questions réelles. Une régression logistique entraînée avec des questions documentaires à la première personne, seule, améliore les quatre jeux mesurés (+6 à +10 refus justifiés, aucune réponse perdue, faux refus 1,9 % à 4,0 %), confirmée en direct sur un jeu de validation indépendant écrit après son choix ; le rappel reste entre 0,66 et 0,80. **Activée par défaut** (`RAGLAB_ROUTING_INTENT_METHOD=logistic`, décision du propriétaire du 4 novembre 2026). Voir [Deuxième partie : généralisation](#deuxième-partie--généralisation-questions-réelles).

Suite de [routage-multilingue.md](routage-multilingue.md) et de [routing.md](routing.md) (phase 9.4, mode d'échec « hors périmètre »). Avec les seuils par langue, le routeur garde 55 refus justifiés sur 80 : le rappel d'abstention plafonne vers 0,7, même avec des seuils réglés sur les questions évaluées. Les questions manquées ne sont plus un problème de langue ni de seuil : ce sont des demandes de tâche, des questions personnelles ou de culture générale, dont le score de passage ressemble à celui d'une question du corpus. Ce document compare des façons de mieux lire **l'intention**, toutes **sans LLM dans le routeur**, et retient la meilleure derrière une option.

Résultat en une phrase : lire l'intention sur les **questions voisines** (kNN) et sur une **petite régression logistique**, puis lire l'intention et le score **ensemble** (règle jointe) plutôt que par deux seuils indépendants, garde **70 refus justifiés sur 80** au lieu de 55 (+15, aucun perdu, p < 0,001), rappel 0,875, avec 4,7 % de faux refus (sous le plafond de 5 %), hors ligne comme en direct. Aucune perte significative sur les questions in-scope de ces jeux. **Mais la régression logistique ne généralise pas** : sur les 38 questions réelles de BR Expat (un Français qui s'installe au Brésil, à la première personne), elle refuse 15 questions au lieu de 3, et les faux refus du routeur à quatre corpus passent de 2,9 % à 15,2 %. Sans elle, le kNN et la règle jointe gardent 65 refus sur 80 (rappel 0,81, 3,7 % de faux refus) et 5,8 % de faux refus à quatre corpus. L'objectif de 0,85 n'est donc atteint que par un signal qui refuse les vraies questions d'utilisateurs : **l'option reste désactivée, et le passage par défaut n'est pas proposé.**

## Le protocole

Mêmes jeux que #76 et #78 : 100 questions françaises de `lexml_fr`, les mêmes 100 en portugais (`lexml_fr_pt`), 100 questions PIAF (graine 42), les 80 questions d'abstention (30 conversationnelles, 27 hors périmètre, 23 « presque dans le sujet »). Le routeur choisit entre `bench_piaf_fr` et `bench_lexml_pt`, pipeline de production (hybride, re-ranking, citations, traduction de la question).

**Référence** : le routeur avec ses deux défauts actuels, routage multilingue de #76 (marge 0,02) et seuils par langue de #78 (quantile 3 %), un couple (corpus, langue) sans seuil propre gardant le seuil du corpus sur le score traduit (#79). Rejouée hors ligne, elle redonne la mesure en direct de #79 (55 refus, 3,3 % de faux refus, 75 / 85 / 91 répondues).

**Hors ligne d'abord.** Chaque option est rejouée sur la collecte de #78 ([`router-languages-collect-v1.json`](../benchmarks/routing/router-languages-collect-v1.json)) : chaque question a déjà été cherchée sur chaque corpus, seule la décision du routeur change. Il faut seulement l'embedding de chaque question (e5-small, sur CPU, une minute) :

```bash
raglab experiment routing-languages --replay benchmarks/routing/router-languages-collect-v1.json --intent \
  --intent-calibration benchmarks/routing/intent_calibration.json
```

La commande affiche le tableau ci-dessous et écrit la calibration de la règle retenue.

**Ce qui apprend, et sur quoi.** Rien n'est appris sur les questions évaluées :

- les **exemples d'intention** : ceux de [`examples.py`](../src/raglab/routing/examples.py), plus 113 nouveaux (`MORE_EXAMPLES`, fr / pt / en : tâches, données personnelles, informations en temps réel, conseils, affaires internes, conversation). Ils ont été écrits avant de lire le jeu d'abstention ; à la vérification, 4 phrases génériques se sont révélées identiques à des questions figées (« D'accord. », « Beleza. »…) et 4 autres presque identiques (cosinus ≥ 0,95) : les 8 ont été retirées. Un test vérifie qu'aucun exemple n'est une question évaluée ;
- les **questions de calibration** de #78 (75 LexML en français, les mêmes en portugais, 100 PIAF de la graine 43), disjointes des questions évaluées, servent de voisins « documentaires » et calibrent les seuils. Une question de calibration n'est jamais sa propre voisine ni dans son propre pli d'apprentissage (5 plis pour la régression logistique).

**Règle de choix** (propriétaire) : marge d'intention 0,02, seuils calibrés par (corpus, langue) sur la source mesurée, le meilleur réglage garde le plus de refus justifiés avec **strictement moins de 5 %** de faux refus. Dans chaque famille, le niveau (quantile) est choisi par cette règle, comme pour #78.

## Les options comparées

| | Idée |
|---|---|
| exemples étendus | les mêmes centroïdes par (intention, langue), avec les nouveaux exemples |
| kNN seul | l'intention lue sur les k questions étiquetées les plus proches (exemples + questions de calibration comme voisins documentaires) : écart documentaire = similarité moyenne des k voisins documentaires moins celle des k autres ; refus sous −0,02 |
| régression logistique | sur l'embedding e5 de la question, entraînée sur les mêmes questions étiquetées (numpy, 384 poids) ; refus au-dessus du quantile 95 à 99 % de la probabilité « non documentaire » des questions de calibration |
| densité | similarité moyenne aux 5 questions de calibration les plus proches du corpus routé ; refus sous le quantile de calibration du couple (corpus, langue), en plus du seuil |
| **règle jointe** | les deux signaux d'un couple (corpus, langue) calibré, l'écart documentaire kNN et le score dense, deviennent leur rang parmi les questions de calibration de ce couple ; la somme des log-rangs est comparée à sa valeur au quantile q des questions de calibration. Une question un peu faible **sur les deux** est refusée, là où deux seuils indépendants la laissent passer |
| **kNN ou logistique + règle jointe** | refus sur l'intention si le kNN ou la régression logistique le demande, puis la règle jointe |

## Résultats hors ligne

McNemar apparié face à la référence. Répondues = bien routées, non refusées, passage attendu dans le top 5 (sur 100). Refus gardés sur 80, faux refus sur 300. Le seul coût de latence est quelques produits scalaires (moins d'une milliseconde) : les p50 / p95 ne bougent pas en rejeu (2 777 / 3 955 ms sur les questions françaises).

| Réglage | Intention | Répondues FR | Répondues PT | Répondues PIAF | Refus gardés | Faux refus |
|---|---|---|---|---|---|---|
| **référence** (#76 + #78 + #79) | centroïdes, marge 0,02 | 75 | 85 | 91 | 55 | 3,3 % |
| sans #76 | centroïdes, seuils par corpus | 33 (−42, p < 0,001) | 87 (+2, n.s.) | 94 (+3, n.s.) | 50 (+4 / −9, n.s.) | 11,7 % |
| exemples étendus | centroïdes | 75 | 85 | 91 | 57 (+3 / −1, n.s.) | 3,3 % |
| kNN seul | k = 10 | 75 | 85 | 91 | 55 (+2 / −2) | 3,0 % |
| régression logistique | q 97 % | 75 | 85 | 87 (−4, n.s.) | 67 (+12, p = 0,001) | 4,7 % |
| densité | q 1 % | 75 | 85 | 90 (−1, n.s.) | 56 (+1, n.s.) | 4,3 % |
| règle jointe, kNN k = 10 | q 3 % | 74 (−1, n.s.) | 80 (−5, p = 0,06) | 91 (+2 / −2) | 67 (+13 / −1, p = 0,002) | 4,7 % |
| règle jointe, kNN k = 20 | q 3 % | 74 (−1, n.s.) | 82 (−3, n.s.) | 92 (+2 / −1) | 65 (+11 / −1, p = 0,006) | 3,7 % |
| **kNN k = 20 ou logistique q 97 % + règle jointe q 3 %** | | 74 (−1, n.s.) | 82 (−3, n.s.) | 89 (+2 / −4, n.s.) | **70 (+15 / −0, p < 0,001)** | **4,7 %** |
| même chose, logistique q 98 % | | 74 (−1, n.s.) | 82 (−3, n.s.) | 91 (+2 / −2) | 68 (+13 / −0, p < 0,001) | 4,0 % |

Tous les niveaux balayés sont dans la sortie de la commande. Les deux familles combinées dépassent 5 % au quantile joint 3 % avec k = 10 (5,0 à 6,3 %), et restent entre 60 et 67 refus aux quantiles 1 et 2 %.

### Ce que montrent ces chiffres

**Plus d'exemples ne suffit pas.** Avec des centroïdes, les nouveaux exemples ne déplacent que 2 refus : une moyenne par intention et par langue écrase la variété des demandes (« Calcule 17 % de… », « Traduis… », « Qui est le responsable de… chez nous ? »). Une question de tâche se retrouve entre le centroïde « hors périmètre » et le centroïde « documentaire », dans la marge de 0,02.

**Les voisins et la régression logistique lisent mieux la même information.** La régression logistique seule rattrape 12 refus, dont presque toutes les tâches et questions personnelles (hors périmètre : 15 → 26 sur 27 avec la règle retenue). Le kNN seul, avec la même marge de 0,02, ne fait pas mieux que les centroïdes : son écart est petit pour les mêmes raisons. Il devient utile **lu avec le score**.

**La règle jointe sépare ce que deux seuils ne séparent pas.** Une question hors sujet a souvent un score dense juste au-dessus du seuil et un écart documentaire juste au-dessus de −0,02 : chaque test pris seul la laisse passer. Le rang d'une question in-scope est rarement bas sur les deux à la fois ; additionner les log-rangs refuse ces cas sans toucher aux questions in-scope fortes sur l'un des deux signaux.

**La densité ne marche pas.** La proximité aux questions de calibration mélange la langue et le sujet comme le centroïde des passages : sous 5 % de faux refus, elle ne rattrape qu'un refus.

**Ce qui reste manqué (10 sur 80).** Des questions de culture générale bien formées, routées vers PIAF (« Quelle est la capitale de la Mongolie ? », « Quel architecte a conçu la pyramide du Louvre ? », « En quelle année le télescope James-Webb a-t-il été lancé ? »), deux questions d'actualité brésilienne routées vers LexML (« Quantos deputados federais tem o Estado de Minas Gerais? ») et une question médicale. Leur intention est documentaire : seul le contenu du corpus dit qu'elles n'y ont pas de réponse. C'est hors de portée d'un classifieur d'intention.

**Le prix.** 14 faux refus sur 300 (4,7 %) contre 10. Les nouveaux : 4 questions PIAF à la formulation de sport ou d'actualité (« Contre quelle équipe le Canada joue-t-il en demi-finale ? », « quand démarre la guerre atomique? »), 5 questions portugaises LexML et 1 française, toutes courtes et peu spécifiques. Aucune perte n'est significative par jeu, mais 8 de ces 10 questions avaient leur passage dans le top 5 : ce sont de vraies réponses perdues.

## Confirmation en direct

Même commande que #79, les deux défauts actuels posés explicitement, le 4 novembre 2026 : [`router-intent-knn-v1.json`](../benchmarks/routing/router-intent-knn-v1.json).

```bash
RAGLAB_ROUTING_CROSS_LANGUAGE=true RAGLAB_ROUTING_LANGUAGE_THRESHOLDS=true RAGLAB_ROUTING_INTENT_KNN=true \
  raglab experiment routing --in-scope lexml_fr --in-scope lexml_fr_pt --in-scope piaf --sample-size 300 \
  --corpus bench_piaf_fr --corpus bench_lexml_pt --query-translation
```

L'expérience enregistre maintenant la décision du routeur lui-même (`router_abstain`, `router_abstention`) : la règle jointe ne se rejoue pas à partir des seuils. La comparaison appariée se fait avec `raglab experiment routing-compare AVANT.json APRÈS.json`, qui redonne aussi la comparaison publiée de #78 (46 → 58). La mesure en direct **redonne exactement le rejeu**. McNemar apparié face à la mesure en direct du défaut actuel ([`router-language-thresholds-v2.json`](../benchmarks/routing/router-language-thresholds-v2.json), #79) :

| | Défaut actuel | kNN + règle jointe | Écart apparié |
|---|---|---|---|
| Répondues depuis le bon passage, français (sur 100) | 75 | 74 | 0 gagnée, 1 perdue (n.s.) |
| Répondues, mêmes questions en portugais | 85 | 82 | 0 / 3, p = 0,25 (n.s.) |
| Répondues, PIAF | 91 | 89 | 2 / 4, p = 0,69 (n.s.) |
| Refus gardés (sur 80) | 55 | **70** | **15 gagnés, 0 perdu, p < 0,001** |
| Rappel / précision de l'abstention | 0,688 / 0,846 | **0,875** / 0,833 | objectif de rappel 0,85 atteint |
| Faux refus (sur 300) | 10 (3,3 %) | 14 (4,7 %) | sous le plafond de 5 % |
| Par catégorie : conversation / hors périmètre / presque dans le sujet | 30 / 15 / 10 | 30 / 26 / 14 | |
| Étape « intention » du routeur, p95 | 0,2 ms | 4,6 ms | |
| p50 / p95 routeur + recherche : français / portugais / PIAF | 3 143 / 4 302 · 819 / 1 130 · 589 / 666 ms | 2 643 / 3 541 · 647 / 877 · 476 / 515 ms | écart dû à la machine (l'option n'ajoute aucune recherche) |

Motifs des refus : intention (36 hors périmètre, 26 conversationnelles), règle jointe 21, aucun passage 1. Face à la mesure sans #76 ([`router-crosslang-off-v1.json`](../benchmarks/routing/router-crosslang-off-v1.json)) : 50 → 70 refus (22 gagnés, 2 perdus, p < 0,001), français 33 → 74, portugais 87 → 82 et PIAF 94 → 89 (5 perdues chacun, p = 0,06).

### Généralisation à quatre corpus

Même mesure que #79 ([routage-multilingue.md](routage-multilingue.md#généralisation-à-quatre-corpus)) : routeur à quatre candidats (`bench_piaf_fr`, `bench_lexml_pt`, `bench_br_expat_pt`, `bench_eurlex_compliance`), les 38 questions BR Expat, 100 questions EUR-Lex (anglais, français, portugais) et les 80 questions d'abstention : [`router-generalization-intent-knn-v1.json`](../benchmarks/routing/router-generalization-intent-knn-v1.json), face à [`router-generalization-language-v1.json`](../benchmarks/routing/router-generalization-language-v1.json) (#79).

```bash
RAGLAB_ROUTING_CROSS_LANGUAGE=true RAGLAB_ROUTING_LANGUAGE_THRESHOLDS=true RAGLAB_ROUTING_INTENT_KNN=true   raglab experiment routing --corpus bench_piaf_fr --corpus bench_lexml_pt --corpus bench_br_expat_pt   --corpus bench_eurlex_compliance --in-scope br_expat --in-scope eurlex_compliance --sample-size 200 --calibration-size 20
```

| | Défaut actuel | kNN ou logistique + règle jointe | Écart apparié |
|---|---|---|---|
| BR Expat : bien routées / répondues depuis le bon passage (sur 38) | 28 / 16 | 28 / 13 | 1 gagnée, 4 perdues (n.s.) |
| BR Expat : faux refus | 3 | **15** | |
| EUR-Lex : bien routées / répondues (sur 100) | 92 / 63 | 92 / 61 | 0 / 2 (n.s.) |
| EUR-Lex : faux refus | 1 | 6 | |
| Refus gardés (sur 80) | 50 | 67 | 17 gagnés, 0 perdu, p < 0,001 |
| Faux refus (sur 138) | 4 (2,9 %) | **21 (15,2 %)** | trois fois le plafond |
| p50 / p95 routeur + recherche, BR Expat / EUR-Lex | 2 501 / 3 786 · 899 / 1 114 ms | 1 947 / 2 841 · 729 / 931 ms | machine |

**Ce qui refuse.** 15 des 21 faux refus sont des refus **sur l'intention**, et tous viennent de la régression logistique : « si je me verse des dividendes de ma boîte, je paie de l'impôt dessus ? », « Comment prouver mon adresse si le bail n'est pas à mon nom ? », « Mes années de travail en France comptent-elles pour la retraite brésilienne ? », et trois questions EUR-Lex en anglais écrites comme des cas pratiques (« We are a small company with 100 employees… »). Ses exemples « hors périmètre » parlent à la première personne (mon compte, ma commande, mon chef) ; ses exemples documentaires et les questions de calibration sont impersonnels. Elle a appris la **forme** (« je », « mon ») plus que le besoin. Les questions évaluées de `lexml_fr` et PIAF sont impersonnelles elles aussi : le jeu figé ne pouvait pas le voir.

Les signaux étant enregistrés pour chaque question, on peut recalculer la décision sans la régression logistique sur les mêmes recherches (`RAGLAB_ROUTING_INTENT_LOGISTIC=false`) :

| Variante (recalculée sur les mesures en direct) | Jeu figé : refus gardés, faux refus | Quatre corpus : refus gardés, faux refus |
|---|---|---|
| défaut actuel | 55, 3,3 % | 50, 2,9 % |
| kNN ou logistique + règle jointe | **70, 4,7 %** | 67, **15,2 %** |
| **kNN + règle jointe, sans logistique** | 65, 3,7 % | 59, 5,8 % (BR Expat 5, EUR-Lex 3) |
| règle jointe seule (intention des centroïdes) | 59, 3,7 % | 51, 5,8 % |

Sans la régression logistique, le kNN ne refuse plus de question réelle sur l'intention ; il reste 4 faux refus de plus que le défaut à quatre corpus, dus pour l'essentiel à la règle jointe : des questions françaises de BR Expat et portugaises d'EUR-Lex routées vers LexML, notées sur la calibration (LexML, français) ou (LexML, portugais) alors que leur corpus attendu est un autre.

## L'option

| Variable | Défaut | Effet |
|---|---|---|
| `RAGLAB_ROUTING_INTENT_KNN` | `false` | intention lue sur les k plus proches questions étiquetées et sur la régression logistique ; pour un couple (corpus, langue) calibré, la règle jointe remplace le seuil seul |
| `RAGLAB_ROUTING_INTENT_LOGISTIC` | `true` | avec l'option kNN : lire aussi la régression logistique du fichier de calibration ; `false` garde le kNN et la règle jointe seuls (la variante qui généralise le mieux, voir ci-dessus) |
| `RAGLAB_ROUTING_INTENT_CALIBRATION_PATH` | `benchmarks/routing/intent_calibration.json` | k, quantile, rangs de calibration par couple, poids et seuil de la régression logistique ; écrit par `--intent-calibration` |

Les voisins documentaires viennent de `RAGLAB_ROUTING_CORPUS_EXAMPLES_PATH` (les questions de calibration de #78), qu'ils servent ou non au choix du corpus. Sans fichier de calibration, l'intention kNN reste active et l'abstention garde les seuils seuls. Un couple sans calibration (un corpus sans questions de calibration, une question en anglais) garde aussi le seuil seul : la règle jointe ne s'applique qu'où elle a été calibrée. Les questions qui citent un texte présent dans l'index ne sont jamais refusées, comme avant.

Comme les autres réglages du routeur, l'option s'applique à toute requête routée : CLI `--routing`, API `routing: true`, interrupteur « Routage » de l'interface. En mode expert, le panneau du routeur affiche les scores kNN par intention, l'écart documentaire, la probabilité « non documentaire » de la régression logistique et, quand elle s'applique, la valeur de la règle jointe et son seuil ; le motif de refus `low_joint_score` s'affiche « intention + score trop faibles ».

## Décision proposée au propriétaire

**Ne pas activer l'option par défaut.** Sur le jeu figé, elle atteint l'objectif (rappel 0,875, 4,7 % de faux refus, 15 refus gagnés sans perte, confirmé en direct). Mais le gain vient pour l'essentiel de la régression logistique, qui refuse 15 des 38 questions réelles de BR Expat : un routeur qui refuse les questions à la première personne échoue précisément sur les utilisateurs du mode Démo. La variante sans régression logistique (65 refus, 3,7 %) est un gain net sur le jeu figé (+10 refus) mais dépasse aussi le plafond à quatre corpus (5,8 %). Les deux restent derrière l'option, mesurées et documentées.

Pistes pour la suite, à valider avant toute mesure : des questions documentaires **à la première personne** dans les exemples et la calibration (écrites pour le routeur, hors des jeux évalués), pour que l'intention n'apprenne plus la forme ; des questions de calibration pour les couples (BR Expat, français) et (EUR-Lex, langue) ; un jeu d'abstention « réel » tiré des usages, à côté du jeu figé.

## Limites

- **Les niveaux sont choisis sur les questions évaluées**, comme pour #78 : k, le quantile de la régression logistique et celui de la règle jointe sont pris dans une grille de 42 réglages par la règle du propriétaire. Les seuils eux-mêmes ne viennent que des questions de calibration, mais une grille plus large rend le meilleur point plus optimiste qu'une seule mesure. Le réglage voisin plus prudent (logistique q 98 %) garde 68 refus à 4,0 %.
- **Les voisins documentaires ressemblent aux questions évaluées** : les questions de calibration viennent des mêmes jeux (même style, même rédacteur pour LexML). Sur des questions réelles d'utilisateurs, le kNN aurait moins de voisins aussi proches, et refuserait plus.
- **Trois couples calibrés seulement** : (LexML, français), (LexML, portugais), (PIAF, français). Ailleurs, la règle jointe ne joue pas ; seule l'intention change.
- Les nouveaux exemples ont été écrits par la même personne qui a lu les catégories du jeu d'abstention (tâches, données personnelles, temps réel) : ils couvrent ces catégories, pas leurs questions.

## Deuxième partie : généralisation (questions réelles)

La première partie s'arrête sur un constat : la régression logistique de #80 a appris la **forme** des exemples hors périmètre (la première personne) plus que le besoin, et refuse les vraies questions d'utilisateurs. Cette partie corrige les données d'apprentissage, complète la calibration, mesure sur **deux jeux de validation indépendants** et compare les approches sans LLM. Résultat en une phrase : **la régression logistique entraînée avec des questions documentaires à la première personne, seule, sans kNN ni règle jointe**, garde 6 à 10 refus justifiés de plus que le défaut sur chacun des quatre jeux mesurés, avec des faux refus au niveau du défaut (1,9 % à 4,0 %) et **aucune réponse documentaire perdue** ; le rappel reste entre 0,66 et 0,80 : **l'objectif de 0,85 n'est atteint sur aucun jeu**, et ne peut pas l'être par l'intention seule.

### Données, et qui a vu quoi

Trois rôles séparés, écrits par des agents distincts qui n'avaient pas accès aux fichiers des autres ni aux jeux figés :

| Rôle | Contenu | Fichier |
|---|---|---|
| apprentissage | 242 exemples : 150 questions documentaires **à la première personne** ou en situation (fr 60, pt 50, en 40 : droit de la consommation, travail, droit fédéral brésilien, conformité UE vue d'une entreprise, culture générale « je prépare un exposé… »), 77 hors périmètre dont deux tiers **impersonnels** (pour casser le raccourci « je = hors sujet »), 15 conversationnelles | [`intent_training.jsonl`](../benchmarks/routing/intent_training.jsonl) |
| calibration BR Expat | 58 questions françaises d'expatrié, écrites sur les documents d'indice **pair** du corpus | [`br_expat/calibration.jsonl`](../benchmarks/br_expat/calibration.jsonl) |
| calibration EUR-Lex | 120 questions (40 par langue) tirées (graine 43) de la vérité terrain, **hors des 100 évaluées** | [`eurlex_compliance/calibration.jsonl`](../benchmarks/eurlex_compliance/calibration.jsonl) |
| validation 1 | 160 questions in-scope au style utilisateur (moitié à la première personne) sur les quatre corpus, ancrées dans un passage relu (documents BR Expat d'indice **impair**) ; 80 à refuser (40 hors périmètre, 30 « presque dans le sujet » dont l'absence des corpus est vérifiée en SQL, 10 conversationnelles) | [`routing_validation/`](../benchmarks/routing_validation/README.md) |
| validation 2 | même cahier des charges, autre graine (2027), écrit **après** la lecture de la validation 1, pour tester la variante choisie entre-temps ; 9 questions trop proches (cosinus ≥ 0,95) d'un texte d'apprentissage retirées avant la mesure : 159 + 72 | [`routing_validation_2/`](../benchmarks/routing_validation_2/README.md) |

Contrôles : un test vérifie qu'aucun texte d'apprentissage ou de calibration n'apparaît dans un jeu évalué ; avant chaque mesure, les quasi-doublons (cosinus ≥ 0,95) ont été retirés, côté apprentissage (13 exemples, 2 questions de calibration) puis côté validation 2 (9 questions) une fois le modèle figé.

### Protocole

Le routage et la recherche ne dépendent pas de l'intention : chaque variante est **rejouée sur des mesures en direct** (mêmes corpus, mêmes passages, mêmes scores), seule la décision change ([`intent_generalization.py`](../src/raglab/experiments/intent_generalization.py)). Le rejeu redonne à la décision près les quatre mesures en direct déjà publiées (défaut et option de #80, deux corpus et quatre corpus : 0 écart sur 1 196 décisions), puis la mesure en direct de la validation 2 (0 écart sur 231).

```bash
raglab experiment intent-generalization \
  --dev benchmarks/routing/router-intent-knn-v1.json --dev benchmarks/routing/router-generalization-intent-knn-v1.json \
  --test benchmarks/routing/router-validation-v1.json --test benchmarks/routing/router-validation2-logistic-v1.json \
  --output benchmarks/routing/intent-generalization-v1.json
```

1. **Choix sur les jeux de développement** (les jeux figés, à deux et à quatre corpus) : 42 variantes (centroïdes, kNN, kNN + règle jointe, régression logistique, kNN + logistique + règle jointe ; exemples de #80 ou étendus ; calibration des seuls couples de #78 ou de tous) ; règle du propriétaire sur **chacun** des deux jeux (faux refus strictement sous 5 %, aucune perte significative de réponses), puis le plus de refus sur le pire des deux.
2. **Validation 1, lue une fois** pour la variante choisie et la meilleure de chaque famille.
3. La variante choisie échoue sur la validation 1 (voir plus bas) ; une variante est alors **pré-enregistrée** (commit 946fab7, avant que la validation 2 n'existe) : la meilleure, par la même règle, des familles sans règle jointe, soit la régression logistique (exemples étendus, positifs des couples de #78, coupure au quantile 97 % de la calibration hors pli).
4. **Validation 2, mesurée en direct** avec le code du routeur (`RAGLAB_ROUTING_INTENT_METHOD=logistic`) : [`router-validation2-logistic-v1.json`](../benchmarks/routing/router-validation2-logistic-v1.json).

### Résultats

Refus gardés (rappel), faux refus, réponses depuis le bon passage ; entre parenthèses, McNemar apparié face au défaut actuel sur les mêmes questions.

| Variante | Jeu figé, 2 corpus (80 / 300) | Jeu figé, 4 corpus (80 / 138) | **Validation 1** (80 / 160) | **Validation 2, en direct** (72 / 159) |
|---|---|---|---|---|
| **défaut** (centroïdes + seuils) | 55 (0,69), 3,3 %, 251 rép. | 50 (0,63), 2,9 %, 79 | 47 (0,59), 3,1 %, 109 | 43 (0,60), 3,1 %, 108 |
| option de #80 (kNN + logistique + règle jointe) | 70, 4,7 %, 245 | 67, **15,2 %**, 74 | 60, **24,4 %**, 88 (LexML −11, p = 0,001) | 51, **22,0 %**, 91 (LexML −9, p = 0,004) |
| choisie sur le développement : kNN k = 10 + logistique + règle jointe, exemples à la 1re personne | 69, 3,3 %, 248 | 65, 2,9 %, 80 | 58, **11,3 %**, 104 | 52, **7,5 %**, 105 |
| kNN + règle jointe, exemples à la 1re personne | 65, 2,7 %, 250 | 58, 2,9 %, 80 | 53, **10,6 %**, 105 | 47, **7,5 %**, 105 |
| kNN seul, exemples à la 1re personne | 53, 3,0 %, 251 | 49, 2,2 %, 80 | 43 (−4 net), 2,5 %, 110 | 35 (**−8, p = 0,04**), 1,9 %, 108 |
| seuils calibrés pour BR Expat et EUR-Lex (intention inchangée) | 55, 3,3 %, 251 | 51, **6,5 %**, 77 | non lu (écarté au développement) | non lu |
| centroïdes, exemples à la 1re personne | 46, 3,0 %, 251 | 42, 2,2 %, 80 | 36 (**−11, p = 0,001**), 2,5 %, 110 | 29 (**−14, p < 0,001**), 1,9 %, 108 |
| **régression logistique seule, exemples à la 1re personne** (pré-enregistrée) | **64 (0,80)** (+9 / −0, p = 0,004), 4,0 %, 249 | **60 (0,75)** (+10 / −0, p = 0,002), 2,2 %, 80 | **53 (0,66)** (+7 / −1, p = 0,07), 3,7 %, 109 | **49 (0,68)** (+7 / −1, p = 0,07), **1,9 %**, 108 |

Réponses perdues par la variante pré-enregistrée, par jeu et par corpus (McNemar) : jeu figé 2 corpus, français 75 = 75, portugais 85 = 85, PIAF 91 → 89 (−2, p = 0,5) ; 4 corpus, BR Expat 16 → 17, EUR-Lex 63 = 63 ; validation 1, BR Expat 20 → 21, PIAF 37 → 36, LexML et EUR-Lex inchangés ; validation 2, aucune différence sur aucun corpus. Aucune perte significative nulle part.

**Faux refus par corpus et par langue** (pré-enregistrée / défaut) :

| | PIAF | LexML | BR Expat | EUR-Lex | fr | pt | en |
|---|---|---|---|---|---|---|---|
| validation 1 | 1 / 0 (sur 40) | 3 / 3 | 2 / 2 | 0 / 0 | 5 / 4 (sur 113) | 1 / 1 (33) | 0 / 0 (14) |
| validation 2 | 0 / 0 | 2 / 3 | 0 / 1 | 1 / 1 (39) | 1 / 3 (112) | 2 / 2 (33) | 0 / 0 (14) |

**Par catégorie** (pré-enregistrée, défaut entre parenthèses) : hors périmètre 23 / 27 (15) sur le jeu figé, 38 / 40 (31) en validation 1, **34 / 34** (27) en validation 2 ; conversationnelles toutes refusées partout ; « presque dans le sujet » 11 / 23 (10), 5 / 30 (6), 7 / 30 (8).

**Latence** : l'étape « intention » du routeur passe de 0,2 ms à 2,4 ms au p95 en direct (embedding déjà calculé ; un produit scalaire de 384 poids plus les centroïdes pour nommer le refus) ; le p95 routeur + recherche ne bouge pas (3 543 ms en validation 1 avec l'option kNN, 3 457 ms en validation 2). Le kNN coûte 4,7 ms au p95.

### Ce que montrent ces chiffres

**La règle jointe ne généralise pas.** Elle classe une question parmi les questions de calibration de son couple (corpus, langue). Ces questions ont été écrites dans le style des jeux figés ; des questions au style utilisateur, surtout sur LexML et EUR-Lex, ont un écart documentaire et un score dense plus bas, et tombent sous le seuil : 17 à 18 faux refus sur 160 en validation 1, 12 sur 159 en validation 2, alors que le jeu de développement ne montrait rien (2,9 %). C'est ce qui a fait échouer la variante choisie sur le développement ; le choix des niveaux sur des questions du même style que la calibration était le point faible signalé dans la première partie, et il s'est vérifié.

**Les exemples à la première personne corrigent la régression logistique.** Avec eux, elle ne refuse plus les questions d'expatriés (BR Expat : 15 faux refus avec #80, 2 avec la nouvelle, 3 avec le défaut) et refuse presque toutes les demandes hors périmètre (34 sur 34 en validation 2, 38 sur 40 en validation 1), à la première personne comme à l'impersonnel.

**Les centroïdes et le kNN « durcis » perdent des refus** : avec les exemples à la première personne, les questions personnelles hors sujet ressemblent davantage aux documentaires, et la marge de 0,02 les laisse passer (−11 à −14 refus en validation). Le classifieur linéaire apprend la frontière là où une distance moyenne ne la voit pas.

**Pourquoi 0,85 est hors de portée de l'intention.** En validation 2, la régression logistique refuse toutes les demandes hors périmètre et toutes les conversations ; il reste 23 questions « presque dans le sujet » (loi d'un autre pays, événement de 2026, numéro de loi inventé, entité absente de PIAF) dont l'intention est documentaire : seul le contenu des corpus dit qu'elles n'ont pas de réponse. Même un classifieur d'intention parfait plafonnerait à (34 + 8 + 8) / 72 = 0,69 sur ce jeu, 0,70 en validation 1. Les gagner demande un autre signal (couverture du sujet par le corpus, vérification de la réponse), hors du périmètre « intention sans LLM ».

### L'option livrée

| Variable | Défaut | Effet |
|---|---|---|
| `RAGLAB_ROUTING_INTENT_METHOD` | `logistic` | `logistic` : la régression logistique de `RAGLAB_ROUTING_INTENT_LOGISTIC_PATH` décide seule de l'intention (au-dessus de sa coupure, refus nommé d'après les centroïdes : conversationnelle ou hors périmètre) ; l'abstention garde les seuils seuls ; `centroids` = l'intention d'avant ; `knn` = l'option de #80 |
| `RAGLAB_ROUTING_INTENT_LOGISTIC_PATH` | `benchmarks/routing/intent_logistic.json` | poids, biais, coupure (0,4912, quantile 97 % des questions de calibration hors pli) ; écrit par `raglab experiment intent-generalization ... --export lr_fp_first_c0.97` |
| `RAGLAB_ROUTING_INTENT_TRAINING_PATH` | `benchmarks/routing/intent_training.jsonl` | exemples à la première personne, lus par l'option kNN quand sa calibration le demande |

Mêmes surfaces que les autres réglages du routeur (CLI `--routing`, API `routing: true`, interrupteur « Routage ») ; en mode expert, le panneau du routeur affiche la probabilité « non documentaire » à côté des scores des centroïdes.

### Décision

**`RAGLAB_ROUTING_INTENT_METHOD=logistic` est activé par défaut** (proposé avec la mesure, accepté par le propriétaire le 4 novembre 2026). Les raisons :

- c'est la seule variante qui améliore les quatre jeux à la fois : +6 à +10 refus justifiés, sans perte de réponse documentaire sur aucun corpus, avec des faux refus entre 1,9 % et 4,0 % (le défaut : 2,9 % à 3,3 %) ;
- elle a été choisie avant la validation 2 et confirmée en direct sur celle-ci, avec le code du routeur ;
- coût : 2 ms au p95, aucun modèle de plus d'1 Go, aucun appel LLM.

Ce qu'elle ne fait pas : atteindre 0,85 (0,66 à 0,80 selon le jeu). L'option kNN et la règle jointe de #80 restent désactivées, et devraient le rester : elles échouent sur les deux jeux indépendants.

Prochaine étape pour le rappel : un signal de **couverture** pour les questions « presque dans le sujet » (par exemple la présence des entités nommées de la question dans le corpus, ou une vérification de la réponse par le juge local), mesuré sur ces mêmes jeux de validation.

### Limites

- Les deux jeux de validation et les exemples d'apprentissage sont **écrits par un LLM** au style utilisateur, pas tirés de vrais journaux ; les agents étaient séparés, mais un style d'écriture commun reste possible. Un jeu tiré d'usages réels reste la vraie validation.
- Une validation lue, puis une variante choisie, puis une seconde validation : la variante pré-enregistrée n'a été testée qu'**une fois** à l'aveugle (validation 2). Ses gains sur chaque validation, pris seuls, sont à p = 0,07.
- **Seuils des nouveaux couples non retenus.** Les couples (BR Expat, français) et (EUR-Lex, anglais / français / portugais) sont maintenant calibrés (quantile 2 ou 3 % de leurs questions de calibration, score dense de la question d'origine) ; ces seuils gagnent un refus à quatre corpus (51 au lieu de 50) mais montent les faux refus de 2,9 % à 6,5 % : la calibration BR Expat vient des documents pairs, les questions BR Expat évaluées de textes en partie différents, et un seuil par couple réglé sur une centaine de questions ne transfère pas. Aucune variante qui s'en sert (seuils ou règle jointe sur « tous les couples ») ne passe le développement ; le défaut garde le seuil du corpus sur le score traduit pour ces couples (#79).
- Les questions LexML de la validation 1 portent souvent sur des tableaux budgétaires (ce qu'est une bonne part du corpus) ; la validation 2 les a évités.
