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
| Par défaut | activé (`RAGLAB_CITATION_RESOLVER=true`) depuis la mesure `citations-v1` |

## Honnêteté de la mesure

La méthode a été mise au point en regardant les échecs des **25 premières** questions `reference` (élargissement de l'article épinglé de 2 chunks à l'article entier : 18 → 21 bonnes réponses sur 25). Pour vérifier qu'elle ne sur-apprend pas ces 25 questions, le résultat est aussi donné sur les **72 autres**, jamais regardées pendant la mise au point.

Limites connues :

- une étiquette de question imprécise (question sur l'art. 7, réponse sous l'art. 8) reste ratée ;
- les lois qui en modifient d'autres recopient des articles entiers : un « Art. 2º » cité à l'intérieur d'un article modificatif peut être pris pour le début de l'article 2 ;
- seules les lois fédérales numérotées sont reconnues ; décrets, portarias et lois d'État ne le sont pas.

## Profil français (codes)

Les codes français collectés par `raglab legifrance fetch` sont rangés à raison d'un document par version d'article, avec le code et le numéro d'article dans les métadonnées (voir [corpus-legi.md](corpus-legi.md)). Quand la question ne cite pas de loi brésilienne, le résolveur cherche une citation d'article de code :

| Question | Citation lue |
|---|---|
| « Que prévoit l'article L. 221-18 du Code de la consommation ? » | art. L. 221-18, Code de la consommation |
| « Que dit l'art. R. 212-1 ? » | art. R. 212-1, code non précisé |
| « Que dispose l'article 1240 du code civil ? » | art. 1240, Code civil |
| « Que dit l'article 4 de la loi n° 89-462 ? » | rien |

Un numéro avec une lettre de partie (L, R, D, A, LO) suffit ; un numéro sans lettre n'est retenu que si un code est nommé juste après, car lois et décrets numérotent leurs articles de la même façon. Une trentaine de codes sont reconnus par leur nom ou leur abréviation (« C. consom. », « C. civ. »). L'article est retrouvé par `article_number` (et `code` s'il est nommé) : la version en vigueur, sinon la plus récente ; ses chunks sont épinglés en tête et la recherche est restreinte au code (`metadata_equals` sur `code`). La réponse de l'API porte `law_number: null` et `code`. Les citations brésiliennes sont lues en premier, inchangées.

## Résultats

Recall@5 sur les 97 questions `reference` de LexML (comparaison appariée, McNemar exact) :

| Run | Configuration | 25 de mise au point | 72 jamais regardées | Total |
|---|---|---|---|---|
| `baseline-v1` | dense | 0,120 | 0,083 | 0,093 |
| `citations-v1` | dense + citations | 0,840 | 0,722 | 0,753 (+64 / −0, p < 0,001) |
| `full-v1` | hybride + re-ranking + citations | 0,720 | 0,722 | 0,722 (+61 / −0 contre `baseline-v1`) |

Sur l'ensemble de LexML (277 questions), la configuration complète `full-v1` passe de **0,466 à 0,816** en Recall@5 et de 0,379 à 0,694 en MRR par rapport à `baseline-v1`. Côté génération, la justesse des réponses passe de 0,451 à 0,598 et la pertinence de 0,725 à 0,865, pour une fidélité stable (0,903 → 0,895). Le juge est Gemma 4, sur les 100 premières questions.

Ce qu'il faut en retenir honnêtement :

- sur les 72 questions jamais regardées, le gain est le même avec ou sans re-ranking (0,722) : la méthode ne sur-apprend pas les 25 questions de mise au point ;
- le re-ranking fait perdre 3 des 25 questions de mise au point (0,840 → 0,720, écart non significatif : +1 / −4, p = 0,375). Il réordonne les chunks à l'intérieur de l'article épinglé, et un article long peut repousser le bon passage au-delà du top 5 ;
- seul, le résolveur de citations coûte de la fidélité (0,903 → 0,842 sur LexML, `citations-v1`). Combiné au re-ranking (`full-v1`), on retrouve 0,895.
