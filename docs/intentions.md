# Intention et abstention : voisins proches et règle jointe

Suite de [routage-multilingue.md](routage-multilingue.md) et de [routing.md](routing.md) (phase 9.4, mode d'échec « hors périmètre »). Avec les seuils par langue, le routeur garde 55 refus justifiés sur 80 : le rappel d'abstention plafonne vers 0,7, même avec des seuils réglés sur les questions évaluées. Les questions manquées ne sont plus un problème de langue ni de seuil : ce sont des demandes de tâche, des questions personnelles ou de culture générale, dont le score de passage ressemble à celui d'une question du corpus. Ce document compare des façons de mieux lire **l'intention**, toutes **sans LLM dans le routeur**, et retient la meilleure derrière une option.

Résultat en une phrase : lire l'intention sur les **questions voisines** (kNN) et sur une **petite régression logistique**, puis lire l'intention et le score **ensemble** (règle jointe) plutôt que par deux seuils indépendants, garde **70 refus justifiés sur 80** au lieu de 55 (+15, aucun perdu, p < 0,001), rappel 0,875, avec 4,7 % de faux refus (sous le plafond de 5 %). Aucune perte significative sur les questions in-scope. L'option `RAGLAB_ROUTING_INTENT_KNN` reste désactivée en attendant la décision du propriétaire.

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

À compléter après la mesure en direct (`raglab experiment routing` avec `RAGLAB_ROUTING_INTENT_KNN=true`).

## L'option

| Variable | Défaut | Effet |
|---|---|---|
| `RAGLAB_ROUTING_INTENT_KNN` | `false` | intention lue sur les k plus proches questions étiquetées et sur la régression logistique ; pour un couple (corpus, langue) calibré, la règle jointe remplace le seuil seul |
| `RAGLAB_ROUTING_INTENT_CALIBRATION_PATH` | `benchmarks/routing/intent_calibration.json` | k, quantile, rangs de calibration par couple, poids et seuil de la régression logistique ; écrit par `--intent-calibration` |

Les voisins documentaires viennent de `RAGLAB_ROUTING_CORPUS_EXAMPLES_PATH` (les questions de calibration de #78), qu'ils servent ou non au choix du corpus. Sans fichier de calibration, l'intention kNN reste active et l'abstention garde les seuils seuls. Un couple sans calibration (un corpus sans questions de calibration, une question en anglais) garde aussi le seuil seul : la règle jointe ne s'applique qu'où elle a été calibrée. Les questions qui citent un texte présent dans l'index ne sont jamais refusées, comme avant.

Comme les autres réglages du routeur, l'option s'applique à toute requête routée : CLI `--routing`, API `routing: true`, interrupteur « Routage » de l'interface. En mode expert, le panneau du routeur affiche les scores kNN par intention, l'écart documentaire, la probabilité « non documentaire » de la régression logistique et, quand elle s'applique, la valeur de la règle jointe et son seuil ; le motif de refus `low_joint_score` s'affiche « intention + score trop faibles ».

## Décision proposée au propriétaire

À compléter après la mesure en direct.

## Limites

- **Les niveaux sont choisis sur les questions évaluées**, comme pour #78 : k, le quantile de la régression logistique et celui de la règle jointe sont pris dans une grille de 42 réglages par la règle du propriétaire. Les seuils eux-mêmes ne viennent que des questions de calibration, mais une grille plus large rend le meilleur point plus optimiste qu'une seule mesure. Le réglage voisin plus prudent (logistique q 98 %) garde 68 refus à 4,0 %.
- **Les voisins documentaires ressemblent aux questions évaluées** : les questions de calibration viennent des mêmes jeux (même style, même rédacteur pour LexML). Sur des questions réelles d'utilisateurs, le kNN aurait moins de voisins aussi proches, et refuserait plus.
- **Trois couples calibrés seulement** : (LexML, français), (LexML, portugais), (PIAF, français). Ailleurs, la règle jointe ne joue pas ; seule l'intention change.
- Les nouveaux exemples ont été écrits par la même personne qui a lu les catégories du jeu d'abstention (tâches, données personnelles, temps réel) : ils couvrent ces catégories, pas leurs questions.
