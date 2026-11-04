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

Option `query_translation` ([`translation.py`](../src/raglab/retrieval/translation.py)), **désactivée par défaut**. Quand la langue détectée de la question (détecteur du routeur, sans modèle) diffère de la langue du corpus, le rédacteur local (Qwen3.6-35B-A3B via llama.cpp, raisonnement désactivé, température 0) traduit la question dans la langue du corpus, « comme la formulerait un juriste de ce pays, avec ses termes juridiques et ses noms d'institutions ». La traduction ne sert **qu'au BM25** : la recherche dense, le re-ranking et la réponse gardent la question d'origine, et la réponse reste en français.

Une question dans la langue du corpus ne déclenche aucun appel. Si le rédacteur ne répond pas (arrêté, occupé par un autre modèle, délai `RAGLAB_QUERY_TRANSLATION_TIMEOUT_SECONDS` dépassé), le BM25 cherche la question d'origine et la réponse le dit (`query_translation.notice: "writer_unavailable"`) ; une requête n'échoue jamais à cause de la traduction. Les traductions sont gardées en cache en mémoire (512 questions).

| Option | Valeurs | Défaut | CLI | API | Variable |
|---|---|---|---|---|---|
| Traduction de la question | oui / non | non | `--query-translation/--no-query-translation` | `query_translation` | `RAGLAB_QUERY_TRANSLATION`, `RAGLAB_QUERY_TRANSLATION_TIMEOUT_SECONDS` |

Dans l'Atelier (page Interrogation, mode expert), le champ « Traduction de la question » l'active ; la réponse affiche la traduction envoyée au BM25 et son temps.

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

La brique comble l'écart, mais au prix de 2 à 4 s par question : elle reste **désactivée par défaut**, en option à activer pour un usage franco-brésilien. Le choix de l'activer par défaut (ou seulement quand le routeur détecte une langue différente du corpus, ce qu'elle fait déjà) revient au propriétaire du projet.

## Limites

- 100 questions : les écarts par type (48 et 52 questions) restent larges ; seul l'écart `entity` est significatif.
- Les questions françaises sont des traductions de questions écrites par un modèle en lisant le passage, pas des questions spontanées d'utilisateurs ; elles gardent les indices de la question d'origine.
- Seul le retrieval est mesuré ici. La passe de réponses jugées (Qwen3.6 rédacteur, Gemma 4 juge) n'a pas été lancée dans cette mesure ; la réponse attendue du jeu est en portugais, une réponse française serait donc jugée face à une référence portugaise.
- Le jeu UE (`eurlex_compliance`, questions `cross_language`) n'a pas été re-mesuré avec la brique.
