# Langues croisées : questions en français, lois brésiliennes

Un utilisateur francophone pose sa question en français ; la réponse est dans une loi fédérale brésilienne, en portugais. Ce document mesure ce que coûte ce changement de langue au pipeline par défaut, puis une brique qui le corrige : la traduction de la question pour le BM25.

## Le jeu figé

[`benchmarks/lexml_fr/`](../benchmarks/lexml_fr/README.md) : 100 questions naturelles du jeu LexML (52 `paraphrase`, 48 `entity`, tirées avec la graine 42, sans numéro d'article ni de loi), traduites en français naturel ; 20 relues à la main. Le même dossier garde la question portugaise d'origine de chaque cas (`ground_truth_pt.jsonl`) : les deux langues sont comparées sur exactement les mêmes passages attendus.

```bash
raglab bench all --label lexml-fr-v1 --suite lexml_fr_pt --suite lexml_fr --ragas-limit 0
raglab bench compare lexml-fr-v1 lexml-fr-v1 --suites lexml_fr_pt:lexml_fr
```

`--suites a:b` apparie deux suites de noms différents qui portent les mêmes identifiants (McNemar sur le Recall@5, bootstrap apparié sur le MRR).

## Ce que coûte le français

Pipeline par défaut (hybride BM25 + dense, fusion RRF, re-ranking bge-reranker-v2-m3, résolveur de citations, versions `in_force`), mêmes 100 questions :

| | Portugais | Français | Écart (apparié) |
|---|---|---|---|
| Recall@5 | 0,870 | 0,790 | −0,080 (3 gagnées, 11 perdues, p = 0,057) |
| MRR | 0,787 | 0,712 | −0,076, IC 95 % [−0,147 ; −0,012] ✱ |
| Recall@5, questions `entity` (48) | 0,938 | 0,792 | −0,146 (0 gagnée, 7 perdues, p = 0,016) ✱ |
| Recall@5, questions `paraphrase` (52) | 0,808 | 0,788 | −0,019 (n.s.) |

Run `lexml-fr-v1`. Le RAG naïf (recherche dense seule, `lexml-fr-naive-v1`) perd de la même façon : 0,670 → 0,600, et −0,125 sur les questions `entity` (p = 0,03).

**Où est la perte.** Elle porte presque entièrement sur les questions qui nomment une institution ou un sigle : « ministère des Finances » ne partage aucun mot avec « Ministério da Fazenda », « Tribunal des comptes » aucun avec « Tribunal de Contas ». Le BM25 ne voit plus les termes rares qui faisaient sa force sur ces questions ; l'embedding multilingue (e5-small) rapproche les deux langues, mais moins bien sur les noms propres. Les paraphrases, déjà portées par le sens, ne bougent presque pas.

Les 11 questions perdues en français (Recall@5) :

| Id | Type | Question française |
|---|---|---|
| lexml-0009 | entity | Quelle commission a été créée au sein du ministère de l'Éducation par la loi qui institue le ProJovem ? |
| lexml-0051 | entity | Quel tribunal examine les dossiers présentant des irrégularités relevées dans l'exécution budgétaire des sous-projets et sous-activités ? |
| lexml-0060 | entity | Comment s'appelle le programme consacré à la participation du Brésil aux organismes financiers internationaux ? |
| lexml-0118 | paraphrase | Quelles sont les attributions du juge de l'application des peines dans le District fédéral ? |
| lexml-0141 | entity | Quel organe fixe les attributions des ministres et des chambres pour l'examen de la répercussion générale, selon le règlement intérieur ? |
| lexml-0150 | entity | Quelles entités peuvent demander les montants déclarés par le demandeur pour le calcul des revenus nets ? |
| lexml-0177 | entity | Dans la loi qui crée le programme Empresa Cidadã, quel sigle désigne le régime général de sécurité sociale ? |
| lexml-0222 | entity | Quel organisme public a vu son patrimoine transféré au ministère des Finances et aux organes du Système national de défense du consommateur ? |
| lexml-0244 | paraphrase | Quelles compétences ont les conseils régionaux de service social en matière de déontologie et de cotisations professionnelles ? |
| lexml-0280 | paraphrase | Qui a droit à la prime de performance de l'activité d'inspection au ministère de l'Agriculture et de l'Approvisionnement ? |
| lexml-0295 | paraphrase | Selon le texte qui crée le programme d'hydrogène propre, sur quelle période les ventes doivent-elles avoir lieu pour bénéficier de l'avantage ? |

Gagnées en français : lexml-0091, lexml-0148, lexml-0274 (trois paraphrases).

## La brique : traduire la question pour le BM25

Option `query_translation` ([`translation.py`](../src/raglab/retrieval/translation.py)), **activée par défaut** depuis la décision du propriétaire du 4 novembre 2026 (voir « Décision »). Quand la langue détectée de la question (détecteur du routeur, sans modèle) diffère de la langue du corpus, le rédacteur local (Qwen3.6-35B-A3B via llama.cpp, raisonnement désactivé, température 0) traduit la question dans la langue du corpus, « comme la formulerait un juriste de ce pays, avec ses termes juridiques et ses noms d'institutions ». La traduction ne sert **qu'au BM25** : la recherche dense, le re-ranking et la réponse gardent la question d'origine, et la réponse reste en français.

Une question dans la langue du corpus ne déclenche aucun appel. Si le rédacteur ne répond pas (arrêté, occupé par un autre modèle, délai `RAGLAB_QUERY_TRANSLATION_TIMEOUT_SECONDS` dépassé), le BM25 cherche la question d'origine et la réponse le dit (`query_translation.notice: "writer_unavailable"`) ; une requête n'échoue jamais à cause de la traduction. La recherche dense seule (`--retrieval-mode dense`) n'a pas de BM25 et ne traduit rien.

**Cache.** L'API construit un `QueryService` par requête : un cache porté par le service serait perdu après chaque question. Les traductions réussies sont donc gardées dans un cache du processus (512 entrées, LRU, protégé par un verrou), partagé par toutes les requêtes et indexé par (question, langue cible, modèle du rédacteur). Une question déjà traduite ne rappelle pas le rédacteur (`query_translation.cached: true`, durée 0) ; les échecs ne sont pas mis en cache, pour retenter quand le rédacteur revient.

**Corpus multilingue.** Le corpus UE (`bench_eurlex_compliance`) déclare la langue `multi` : chaque acte y existe en anglais, français et portugais, il n'y a pas une langue cible unique, et la question n'est pas traduite. Le BM25 y trouve déjà la version de l'acte dans la langue de la question.

| Option | Valeurs | Défaut | CLI | API | Variable |
|---|---|---|---|---|---|
| Traduction de la question | oui / non | **oui** (seulement si la langue de la question diffère de celle du corpus) | `--query-translation/--no-query-translation` | `query_translation` | `RAGLAB_QUERY_TRANSLATION`, `RAGLAB_QUERY_TRANSLATION_TIMEOUT_SECONDS` |

Dans l'Atelier (page Interrogation, mode expert), le champ « Traduction de la question » permet de la forcer ou de la couper pour comparer ; la réponse affiche la traduction envoyée au BM25 et son temps. Dans le Chat, une réponse dont la question a été traduite porte une mention discrète (« mots-clés cherchés en pt », la traduction en info-bulle).

### Mesure

Run `lexml-fr-qt-v1`, mêmes 100 questions, rédacteur et re-ranker chargés ensemble sur le GPU de 8 Go (le profil `qwen35b-moe-rag` laisse environ 1 Go au cross-encoder) ; les 100 questions ont été traduites.

| | Français, défaut | Français + traduction | Écart (apparié) |
|---|---|---|---|
| Recall@5 | 0,790 | **0,890** | +0,100 (11 gagnées, 1 perdue, p = 0,006) ✱ |
| MRR | 0,712 | **0,793** | +0,082, IC 95 % [+0,035 ; +0,138] ✱ |
| Recall@5, `entity` | 0,792 | 0,938 | +0,146 (7 gagnées, 0 perdue, p = 0,016) ✱ |
| Recall@5, `paraphrase` | 0,788 | 0,846 | +0,058 (n.s.) |
| Latence requête p50 / p95 | 490 ms / 933 ms | 3 202 ms / 4 527 ms | dont traduction 2 375 ms / 3 664 ms |

Face aux questions portugaises d'origine (0,870), le français traduit fait jeu égal : 0,890 (4 gagnées, 2 perdues, p = 0,69), MRR 0,787 → 0,793. **L'écart dû à la langue est comblé.**

### Le coût

Environ 2,4 s de plus par question au p50 (3,7 s au p95), le temps que Qwen3.6, dont les experts tournent en partie sur le CPU, écrive une phrase. C'est moins que la génération de la réponse (7 à 9 s avec le même rédacteur), mais c'est six fois la recherche. Le coût ne touche que les questions dans une autre langue que le corpus. Il suppose aussi que le rédacteur llama.cpp soit chargé : avec le repli Ollama, ou sans GPU, la question n'est pas traduite.

Une première mesure, faite pendant que d'autres calculs tournaient sur la machine, avait donné le même Recall@5 mais 8 traductions abandonnées au délai de 20 s : la brique dépend d'un rédacteur disponible, et elle le signale quand il ne l'est pas.

### Décision

**Activée par défaut** (décision du propriétaire, 4 novembre 2026) : c'est la meilleure configuration mesurée, et elle reste conditionnelle. Le surcoût de 2 à 4 s ne touche que les questions dont la langue diffère de celle du corpus ; sur les jeux figés dans une seule langue (PIAF, LexML, Code de la consommation, jeu « versions »), le détecteur de langue ne se trompe sur aucune question (PIAF : 498 en français, 2 sans marqueur ; les autres : 100 %), donc aucun appel au rédacteur et aucun chiffre publié ne change. Le p95 et la disponibilité du rédacteur sont à surveiller en production ; `RAGLAB_QUERY_TRANSLATION=false` la coupe sans toucher au code, `query_translation: false` (API) ou `--no-query-translation` (CLI) pour une requête.

Dans `raglab bench all`, le rédacteur n'est démarré que si une question du jeu est dans une autre langue que le corpus : les suites monolingues ne chargent pas Qwen3.6, et l'étiquette « + query translation » n'apparaît que si une question a été traduite.

## Avec le routeur

Avec `routing=true`, l'ordre est : le routeur détecte la langue et l'intention et choisit le corpus (sans LLM) ; la question est traduite dans la langue **du corpus choisi** si elle diffère ; puis recherche hybride, fusion, re-ranking (question d'origine), abstention, génération. L'abstention lit le score **dense** (cosinus de la question d'origine) des passages retenus : la traduction ne change pas l'échelle sur laquelle les seuils par corpus ont été calibrés, elle peut seulement changer quels passages arrivent dans le top 5. Les seuils ne sont pas modifiés.

### Mesure avec le routeur

```bash
raglab experiment routing --in-scope lexml_fr --in-scope lexml_fr_pt --sample-size 200 --corpus bench_piaf_fr --corpus bench_lexml_pt --query-translation
raglab experiment routing --in-scope lexml_fr --in-scope lexml_fr_pt --sample-size 200 --corpus bench_piaf_fr --corpus bench_lexml_pt --no-query-translation
```

Les 100 questions françaises **et** les mêmes 100 en portugais (`--in-scope lexml_fr_pt`), face aux 80 questions d'abstention ; le routeur choisit entre PIAF et LexML ; seuils de production inchangés (score dense, LexML 0,8485, PIAF 0,7929). Rapports : [`router-lexml-fr-v1.json`](../benchmarks/routing/router-lexml-fr-v1.json) (sans traduction), [`router-lexml-fr-qt-v1.json`](../benchmarks/routing/router-lexml-fr-qt-v1.json) (avec), 4 novembre 2026.

| Sur 100 questions | Portugais | Français, sans traduction | Français, avec traduction |
|---|---|---|---|
| Routées vers LexML (bon corpus) | 100 | 62 | 62 |
| Passage-réponse dans le top 5 (corpus routé) | 87 | 49 | 57 |
| Refusées à tort (abstention) | 0 | 31 (26 parmi les 62 bien routées) | 33 (28) |
| **Répondues depuis le bon passage** (bien routées, non refusées, passage trouvé) | **87** | **32** | **33** |
| Latence routeur + recherche p50 / p95 | 653 / 794 ms | 457 / 624 ms | 2 910 / 4 064 ms |

Questions d'abstention (80) : décisions identiques avec et sans traduction (50 refusées : 30/30 conversationnelles, 14/27 hors périmètre, 6/23 « presque dans le sujet ») ; 11 d'entre elles, routées vers LexML, ont été traduites pour rien. Traductions : 62 questions françaises (celles routées vers LexML ; les 38 routées vers PIAF, corpus français, ne le sont pas), aucun repli sur la question d'origine. Détection de langue : 99,3 %.

**Ce que ça montre.** Avec le routeur, la langue coûte bien plus que les 8 points de Recall@5 mesurés sans lui : 32 questions françaises sur 100 aboutissent, contre 87 en portugais. La traduction pour le BM25 n'y change presque rien (+1), parce que le goulot n'est pas le BM25 mais deux décisions prises sur l'embedding de la question d'origine :

- **choix du corpus** : 38 questions françaises sont envoyées vers PIAF, le corpus français. Avec e5-small, une question française est plus proche du centroïde d'un corpus français que du corpus portugais qui contient la réponse (par exemple 0,857 contre 0,850 ; la même question en portugais : LexML 0,896, PIAF 0,866) ;
- **abstention** : sur les questions bien routées, le meilleur cosinus d'une question française est inférieur d'environ 0,03 à celui de la même question en portugais (médianes 0,852 et 0,886). Le seuil de LexML, calibré sur des questions portugaises, refuse donc 27 questions françaises sur 61, aucune portugaise.

Les seuils n'ont pas été modifiés. La correction est la brique suivante.

## Routage multilingue

Option `RAGLAB_ROUTING_CROSS_LANGUAGE` ([`router.py`](../src/raglab/routing/router.py), [`step.py`](../src/raglab/routing/step.py)), **activée par défaut** (décision du propriétaire, 4 novembre 2026, au vu de la mesure ci-dessous). Elle s'appuie sur la traduction de la question (activée) et ne change que le routeur :

- **choix du corpus** : un corpus dans une autre langue que la question, dont le score de centroïde est à moins de `RAGLAB_ROUTING_TRANSLATION_MARGIN` (0,02) du meilleur, est re-noté sur la question traduite dans sa langue (un appel au rédacteur par langue, mis en cache et réutilisé ensuite par le BM25). Chaque corpus est ainsi comparé dans sa propre langue. Le score gardé est le meilleur des deux ; les deux restent dans la décision (`original_score`, `translated_score`) ;
- **abstention** : quand la question a été traduite pour le corpus choisi, la question traduite est cherchée (dense) dans le même index ; son meilleur cosinus parmi les passages **effectivement retenus** est l'échelle sur laquelle le seuil du corpus a été calibré. Le score comparé au seuil est le meilleur des deux (`abstention.translated_score`). Les seuils ne changent pas.

Un corpus nommé par l'appelant n'est jamais re-noté ; le corpus UE (`multi`) non plus.

### Mesure

Même protocole que ci-dessus, avec en plus 100 questions PIAF (françaises, corpus français) pour vérifier qu'elles ne partent pas vers LexML ; traduction de la question activée dans les trois runs ; 4 novembre 2026. Rapports : [`router-crosslang-off-v1.json`](../benchmarks/routing/router-crosslang-off-v1.json), [`router-crosslang-m05-v1.json`](../benchmarks/routing/router-crosslang-m05-v1.json), [`router-crosslang-m02-v1.json`](../benchmarks/routing/router-crosslang-m02-v1.json).

| Répondues depuis le bon passage (sur 100) | Sans | Marge 0,05 | **Marge 0,02 (défaut)** |
|---|---|---|---|
| Français → LexML | 33 | 85 (52 gagnées, 0 perdue, p < 0,001) | **75** (42 gagnées, 0 perdue, p < 0,001) |
| Mêmes questions en portugais | 87 | 85 (0 / 2, n.s.) | 85 (0 / 2, n.s.) |
| PIAF (français) | 94 | 87 (0 / 7, p = 0,016) | **94** (0 / 0) |
| Questions à refuser bien refusées (sur 80) | 50 | 47 (3 / 6, n.s.) | 46 (0 / 4, p = 0,125, n.s.) |
| Latence routeur + recherche p50 / p95, portugais | 725 / 885 ms | 3 167 / 4 086 ms | 719 / 1 842 ms |
| Latence p50 / p95, PIAF | 554 / 659 ms | 620 / 2 198 ms | 524 / 584 ms |

Détail à la marge 0,02 : 84 questions françaises routées vers LexML (62 sans), 5 refusées à tort (33 sans) ; 2 questions portugaises partent vers PIAF ; aucune question PIAF ne part vers LexML. Latence des questions françaises inchangée (environ 2,7 s p50) : la traduction qui sert au routeur est celle que le BM25 aurait faite.

**Pourquoi 0,02 et pas 0,05.** À 0,05, presque toutes les questions sont traduites pour comparer l'autre corpus : chaque question portugaise paie 2,4 s pour une comparaison avec PIAF, et 7 questions PIAF partent vers LexML, une fois traduites en portugais. Les enregistrements gardent les deux scores de chaque corpus candidat, ce qui permet de rejouer le choix du corpus hors ligne pour d'autres marges : 0,01 donne 77 questions françaises bien routées, 0,02 en donne 84, 0,03 en donne 95 mais traduit 36 questions portugaises sur 100. La marge 0,02 garde PIAF et le portugais intacts.

**Le coût : l'abstention.** 4 questions hors périmètre de plus ne sont plus refusées (n.s.). Une question hors sujet traduite peut changer de corpus, et les deux seuils n'ont pas la même hauteur (PIAF 0,79, LexML 0,85) : une question portugaise hors sujet (« Qual é a receita tradicional de feijoada? ») qui part vers PIAF passe sous un seuil plus bas. Les 4 refus perdus sont tous de ce type (deux hors périmètre, deux « presque dans le sujet », toutes en portugais). À la marge 0,05, trois questions françaises hors sujet faisaient aussi le chemin inverse et étaient désormais refusées.

**Décision.** Le gain sur le mode d'échec visé est net (+42 questions sur 100, aucune perdue) et aucun autre jeu ne régresse de façon significative. Le propriétaire l'a **activée par défaut** en connaissant le coût sur l'abstention (4 refus perdus sur 80, n.s.), à surveiller. `RAGLAB_ROUTING_CROSS_LANGUAGE=false` la coupe sans toucher au code ; elle ne joue de toute façon que si la traduction de la question est active et que le score d'abstention est le score dense (le défaut).

Le surcoût de latence vient de la traduction (2,4 s p50) ; la recherche des questions portugaises est aussi un peu plus lente pendant le run avec traduction (794 contre 653 ms p50), le rédacteur occupant le GPU à côté du re-ranker.

## Limites

- 100 questions : les écarts par type (48 et 52 questions) restent larges ; seul l'écart `entity` est significatif.
- Les questions françaises sont des traductions de questions écrites par un modèle en lisant le passage, pas des questions spontanées d'utilisateurs ; elles gardent les indices de la question d'origine.
- Seul le retrieval est mesuré ici. La passe de réponses jugées (Qwen3.6 rédacteur, Gemma 4 juge) n'a pas été lancée dans cette mesure ; la réponse attendue du jeu est en portugais, une réponse française serait donc jugée face à une référence portugaise.
- Le jeu UE (`eurlex_compliance`, questions `cross_language`) n'a pas été re-mesuré avec la brique.
