# Résultats de novembre 2026 : nouveaux corpus et modes d'échec

Les runs de la nuit du 3 au 4 novembre 2026 mesurent les trois modes d'échec restants du fil rouge (renvois, versions, et les identifiants sur un second corpus), chacun sur son propre jeu figé. Chaque jeu compare trois runs sur les mêmes questions : le **RAG naïf** (recherche dense seule, sans BM25, re-ranking ni résolveur de citations), le **pipeline complet de raglab**, puis le pipeline complet **plus la brique** conçue pour ce mode d'échec. Les fichiers sont dans [`benchmarks/results/`](../../benchmarks/results/), les jeux dans [`benchmarks/`](../../benchmarks/), la méthode dans [protocole.md](protocole.md).

Le site et le README publient le même tableau, généré depuis les fichiers par `python scripts/build_site.py --readme` (lignes décrites dans [`site/corpora.json`](../../site/corpora.json)).

## Lecture

- **Recall@5** : part des questions dont le passage-réponse est dans les 5 premiers chunks.
- **Gagnées / perdues** : questions que le run trouve et que le run précédent manque, et l'inverse, sur les mêmes questions. **p** est le test exact de McNemar sur ces paires discordantes ([`compare.py`](../../src/raglab/benchmarks/compare.py), `raglab bench compare`) ; « n.s. » : non significatif (p ≥ 0,05).
- **Version périmée en tête** (`outdated_hit@5`) : part des questions où une version périmée de l'article est classée au-dessus de celle qui répond, dans le top 5. Plus bas est mieux.

## Tableau

| Jeu (mode d'échec) | RAG naïf | Pipeline complet | Avec la brique | Version périmée en tête | Par type, juge |
|---|---|---|---|---|---|
| **Code de la consommation** (versions), 300 questions dont 88 scénarios | 0,360 | 0,660 (96 gagnées, 6 perdues, p < 0,001) | + versions : 0,820 (49 gagnées, 1 perdue, p < 0,001) | 78 % → 57 % → 0 % | questions à numéro d'article 0,458 → 1,000 → 1,000 |
| **Jeu piège « versions »** (versions), 100 questions | 0,480 | 0,750 (29 gagnées, 2 perdues, p < 0,001) | + versions : 0,930 (18 gagnées, 0 perdue, p < 0,001) | 27 % → 30 % → 0 % | exactitude 0,577 → 0,738 → 0,815 ; fidélité 0,875 → 0,935 → 0,895 |
| **Conformité UE** (renvois), 300 questions dont 116 scénarios, en / fr / pt | 0,490 | 0,717 (80 gagnées, 12 perdues, p < 0,001) | + graphe : 0,693 (2 gagnées, 9 perdues, p = 0,07, n.s.) | — | renvois 0,409 → 0,273 → 0,227 ; autre langue 0,100 → 0,175 → 0,150 |
| **Renvois LexML** (renvois), 46 questions dont 14 scénarios | pas de run | 0,870 | + graphe : 0,935 (3 gagnées, 0 perdue, p = 0,25, n.s.) | — | — |
| **Questions françaises, lois brésiliennes** (langues croisées), 100 questions | 0,600 | 0,790 (20 gagnées, 1 perdue, p < 0,001) | + traduction de la question : 0,890 (11 gagnées, 1 perdue, p = 0,01) | — | sigles et entités 0,667 → 0,792 → 0,938 ; mêmes questions en portugais, pipeline complet 0,870 |

Runs : `legi-baseline-v1` → `legi-full-v1` → `legi-full-versions-v1` ; `versions-naive-v1` → `versions-full-all-v1` → `versions-full-v1` ; `eurlex-baseline-v1` → `eurlex-full-v1` → `eurlex-graph-v1` ; `refs-full-v1` → `refs-graph-v1` ; `lexml-fr-naive-v1` → `lexml-fr-v1` → `lexml-fr-qt-v1` (mesure du 4 novembre). Exactitude et fidélité : 100 réponses jugées par Gemma 4 26B-A4B (voir [juges.md](juges.md)).

Sur PIAF et LexML, `graph-v1` et `versions-v1` servent de contrôle de non-régression : Recall@5 inchangé sur PIAF (0,966), 0,812 et 0,816 sur LexML contre 0,816 pour le pipeline complet. Ils figurent dans le tableau principal du README comme lignes de comparaison.

## Ce que disent ces chiffres

**Versions (9.10).** Le pipeline complet améliore déjà le Recall@5 du Code de la consommation (0,360 → 0,660), mais classe encore une version périmée au-dessus de la bonne dans 57 % des cas. Le filtre de versions ramène ce taux à 0 % et monte le Recall@5 à 0,820. Sur le jeu piège, le pipeline complet sans filtre fait même un peu pire que le RAG naïf sur les versions périmées (27 % → 30 %) : un meilleur classement remonte aussi les anciennes versions. Le filtre les élimine (0 %), l'exactitude jugée passe de 0,738 à 0,815, la fidélité baisse un peu (0,935 → 0,895). Le filtre (`in_force`) est actif par défaut depuis la PR #69.

**Identifiants.** Sur les questions qui citent un numéro d'article du Code de la consommation, le Recall@5 passe de 0,458 à 1,000 avec le pipeline complet : le résolveur de citations fonctionne aussi sur un code français.

**Renvois (9.9).** Le graphe des citations ne donne pas de gain significatif. Sur les 46 questions de renvois LexML, il gagne 3 questions sans en perdre (+6,5 points, p = 0,25), ce qui est trop peu pour conclure. Sur les textes de l'UE, il perd 2,3 points (2 gagnées, 9 perdues, n.s.). Il reste désactivé par défaut.

**Hors périmètre (9.4).** Le routeur, re-mesuré sur le pipeline actuel avec le score dense ([`router-dense-v1.json`](../../benchmarks/routing/router-dense-v1.json), 80 questions dans le périmètre, 80 hors périmètre ou conversationnelles), trouve au mieux un rappel de 0,850 pour une précision de 0,958 en refusant 3,8 % des questions auxquelles il faudrait répondre (seuil par corpus, plafond de 5 % de fausses abstentions). Le score du re-ranker fait moins bien à ce plafond (rappel 0,838, 5,0 % de fausses abstentions). Le point de fonctionnement reste à choisir ; le point dense ci-dessus est le candidat.

**Points faibles sur les textes de l'UE.** Le pipeline complet gagne sur presque tous les types de questions, sauf deux : les renvois (la réponse est dans l'article cité), qui baissent de 0,409 à 0,273, et les questions posées dans une autre langue que le texte, qui restent très bas (0,100 → 0,175). Ce sont les deux chantiers suivants.

**Langues croisées.** Sur 100 questions LexML posées en français, le pipeline complet perd 8 points de Recall@5 face aux mêmes questions en portugais (0,870 → 0,790, p = 0,057 ; MRR −0,076, significatif), presque tout sur les questions qui nomment une institution ou un sigle (−0,146, p = 0,016) : « ministère des Finances » ne partage aucun mot avec « Ministério da Fazenda ». Traduire la question en portugais pour le BM25 seulement, avec le rédacteur local, comble l'écart (0,890) mais ajoute environ 2,4 s par question : option désactivée par défaut. Détail, liste des questions perdues et coût : [langues-croisees.md](../langues-croisees.md).

## Précautions

- Les questions de ces quatre jeux ont été écrites par un modèle, filtrées par des règles et relues à la main sur un échantillon, pas une par une.
- Le jeu de renvois LexML est petit (46 questions après filtrage) : quelques questions décident du verdict. Un jeu plus grand est nécessaire avant toute conclusion sur le graphe.
- Les écarts non significatifs (« n.s. ») ne sont pas des résultats : ils sont publiés pour ne pas cacher les briques qui n'ont pas encore fait leurs preuves.
- Les chiffres de ce document sont recopiés du tableau généré ; en cas de doute, le tableau du README fait foi.
