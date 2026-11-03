# Reconnaissance des citations juridiques

## Le problème

Un juriste demande « que dit l'art. 49 de la Lei nº 8.078 ? ». Sur le jeu LexML, la bonne réponse n'arrivait dans le top 5 que pour **9 % des 97 questions qui citent un article** (`baseline-v1`, recherche dense). La recherche hybride n'y change rien (9 % aussi, `hybrid-v1`) :

- **les embeddings brouillent les identifiants** : « art. 49 » et « art. 94 » ont des vecteurs presque identiques ;
- **BM25 trouve la bonne loi, pas le bon article** : dans 91 cas sur 97, la loi citée est dans le top 5, mais son numéro n'apparaît que dans le chunk du titre, et « art. 2 » figure dans toutes les lois du corpus.

Une citation n'est pas du langage naturel : c'est une donnée structurée. On la traite donc comme telle, avant toute recherche.

## La méthode

`src/raglab/retrieval/citations.py`, appelé par `QueryService.retrieve` quand l'option est active :

1. **Lire la citation** dans la question : numéro de loi (« Lei nº 8.078 », « Lei 8078/90 », « Lei Complementar nº 101 »), article (« art. 49 », « artigo 11-A ») et année quand elle est donnée.
2. **Trouver la loi** dans le corpus interrogé par son numéro, enregistré dans les métadonnées du document (`number`, écrit par `raglab lexml fulltext`). L'année départage deux lois de même numéro.
3. **Restreindre la recherche à cette loi** : la recherche dense, lexicale ou hybride tourne normalement, mais filtrée sur ce document.
4. **Épingler l'article** : les chunks de l'article cité (du chunk où il commence jusqu'à celui où commence l'article suivant, 6 au plus) passent en tête, ordonnés par la recherche à l'intérieur de l'article, puis le reste de la loi.

Si la question ne cite pas de loi, ou cite une loi absente de l'index, rien ne change. Les stratégies de découpage ne sont pas modifiées : la méthode lit seulement le texte et l'ordre des chunks.

## Utilisation

| Où | Comment |
|---|---|
| CLI | `raglab query "O que dispõe o art. 49 da Lei nº 8.078?" --corpus bench_lexml_pt --citations` |
| API | `"citations": true` dans `POST /api/query`, `/api/query/stream`, `/api/experiments/recall` |
| UI | case « Citations juridiques » de la page Retrieval (et du lancement des benchmarks) ; le passage épinglé porte le badge « article cité », et la page indique quelle citation a été reconnue |
| Benchmark | `raglab bench all --label citations-v1 --citations` |
| Par défaut | `RAGLAB_CITATION_RESOLVER=false` tant que la mesure n'a pas tranché |

## Honnêteté de la mesure

La méthode a été mise au point en regardant les échecs des **25 premières** questions `reference` (élargissement de l'article épinglé de 2 chunks à l'article entier : 18 → 21 bonnes réponses sur 25). Pour vérifier qu'elle ne sur-apprend pas ces 25 questions, le résultat est aussi donné sur les **72 autres**, jamais regardées pendant la mise au point.

Limites connues :

- une étiquette de question imprécise (question sur l'art. 7, réponse sous l'art. 8) reste ratée ;
- les lois qui en modifient d'autres recopient des articles entiers : un « Art. 2º » cité à l'intérieur d'un article modificatif peut être pris pour le début de l'article 2 ;
- seules les lois fédérales numérotées sont reconnues ; décrets, portarias et lois d'État ne le sont pas.

## Résultats

*(mesure en attente : elle passe après le re-ranking sur le GPU)*
