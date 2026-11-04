# Versions des textes (phase 9.10)

Troisième mode d'échec de la thèse de raglab (voir [audit-2026-11.md](audit-2026-11.md)) : **un texte abrogé ou réécrit est cité comme s'il était en vigueur**. Cette page décrit le problème sur des exemples réels du Code de la consommation, la brique qui le corrige (l'option `versions`), le jeu de questions figé qui le mesure et ses limites.

## Le problème

Un corpus juridique garde ce qui ne s'applique plus. Le Code de la consommation collecté par `raglab legifrance fetch` contient **toutes** les versions de chaque article (un document par version, voir [corpus-legi.md](corpus-legi.md)) : 5 998 versions de 3 391 articles, dont 2 106 seulement sont en vigueur. Les lois brésiliennes de LexML sont des textes compilés : les dispositions abrogées y restent, marquées « (Revogado pela Lei nº … ) ».

Un RAG classique classe ces passages comme les autres : ils ressemblent à la question, souvent plus que la version en vigueur. Quatre pièges, tous présents dans le corpus :

| Piège | Exemple réel | Ce que répond un RAG classique |
|---|---|---|
| **Numéro réutilisé** | L'ancien article L. 121-21 donnait quatorze jours pour se rétracter d'un contrat conclu à distance (versions de 1993 à 2016). Depuis la recodification du 1er juillet 2016, le numéro L. 121-21 interdit certains frais de recouvrement ; la règle des quatorze jours est devenue l'article L. 221-18. | « l'article L. 121-21 donne quatorze jours » : vrai en 2015, faux aujourd'hui |
| **Article déplacé** | Le texte de l'ancien L. 121-21 vit sous le numéro L. 221-18, presque mot pour mot (seuls les renvois changent : « L. 121-21-3 à L. 121-21-5 » devient « L. 221-23 à L. 221-25 »). | la bonne règle, citée sous un numéro qui ne la porte plus |
| **Rédaction changée** | Article R. 631-1 : jusqu'en 2019, la saisine simplifiée valait « lorsque le montant de la demande n'excède pas le taux de compétence en dernier ressort du tribunal d'instance » ; depuis le 1er janvier 2020, « n'excède pas 5 000 euros ». | le seuil d'une juridiction supprimée |
| **Ajout récent** | Article L. 222-7 : depuis le 19 juin 2026, le délai de rétractation de quatorze jours « est porté à trente jours calendaires » pour certains plans et produits d'épargne du code monétaire et financier. La version précédente (2017-2026) n'en parle pas. | quatorze jours, sans l'exception |

Les chiffres du corpus : 1 352 articles réécrits au moins une fois, 1 586 versions abrogées, **321 numéros réutilisés** par la recodification de 2016. Sur LexML : 70 lois sur 252 ont des articles réécrits (863 « Redação dada pela »), 79 ont des dispositions abrogées (1 084 « (Revogado) »).

Le résolveur de citations choisissait déjà la version en vigueur d'un article cité, mais seulement pour l'article cité, et sans pouvoir répondre à « l'article L. 121-21 dans sa rédaction de 2014 ».

## La méthode

L'option `versions` dit quelles versions la recherche peut utiliser :

| Valeur | Effet |
|---|---|
| `in_force` (la brique, en cours de mesure) | les versions en vigueur **aujourd'hui** ; si la question porte sur le passé (« avant 2016 »), celles en vigueur à cette date |
| `as_of=AAAA-MM-JJ` | les versions en vigueur à la date donnée |
| `all` (**défaut livré**) | toutes les versions, comme un RAG classique et comme avant 9.10 (la référence de comparaison) |

### 1. La date de référence

Sous `in_force`, la date est aujourd'hui, sauf si la question en donne une. `src/raglab/domain/versions.py` (`parse_question_date`) lit dans la question une date **de référence**, en français, portugais et anglais :

| Question | Date retenue |
|---|---|
| « Que prévoyait l'article L. 121-21 **avant 2016** ? » | 31 décembre 2015 |
| « … **avant le 1er juillet 2016** ? » | 30 juin 2016 |
| « **Dans sa rédaction de 2014**, quel délai … ? » | 31 décembre 2014 (la dernière rédaction de l'année) |
| « Quelle règle était **en vigueur au 1er janvier 2015** ? » | 1er janvier 2015 |
| « **Antes de 2016**, qual era o prazo? », « … **na redação de 2010** ? » | 31 décembre 2015, 31 décembre 2010 |
| « What did it say **as of 2015-03-01**? », « … **before 2016** ? » | 1er mars 2015, 31 décembre 2015 |
| « **En 2015**, mon client a signé un contrat à distance : avait-il sept jours ? », « J'ai acheté un canapé **en mars 2015** … », « Contrat **signé le 3 mars 2015** », « **em março de 2015** », « **in March 2015** » | 31 décembre 2015, 31 mars 2015, 3 mars 2015 (un mois vaut son dernier jour) |

Seule une date précédée d'un mot qui en fait une date de référence compte (« avant », « dans sa rédaction de », « en vigueur au », « en », « signé le », « antes de », « na redação de », « em », « as of », « in »…), comme quand un utilisateur date sa situation ; « la loi n° 2014-344 du 17 mars 2014 » ou « Lei nº 8.078, de 1990 » **nomment un texte**, elles ne demandent pas le passé. Une date future est ignorée. Une option `as_of=` explicite l'emporte sur la question ; `all` ne lit aucune date.

### 2. Le filtre (métadonnées de Légifrance)

Chaque version d'article porte dans ses métadonnées son état (`etat` : VIGUEUR, MODIFIE, ABROGE, ABROGE_DIFF, TRANSFERE, ANNULE) et ses dates (`date_debut`, `date_fin`). Une version s'applique à une date si elle a commencé et n'a pas encore pris fin (`date_debut ≤ date < date_fin`) ; une version annulée ne s'applique jamais. Ce sont les **dates** qui décident, pas l'état : l'état est celui du jour où le corpus a été figé (une version ABROGE_DIFF reste en vigueur jusqu'à sa date de fin).

Le filtre est appliqué **dans la requête SQL, avant le classement** (`RetrievalFilters.valid_at`, `valid_at_condition` dans `src/raglab/stores/vector/postgres.py`), pour la recherche vectorielle comme pour BM25 : les versions périmées ne prennent pas de place dans le top-k. Les documents sans métadonnées de version (PIAF, LexML, documents déposés) passent toujours. Le filtre n'est ajouté que si le corpus interrogé a des versions (un `EXISTS` sur `etat`), aucune requête ne change ailleurs.

Le résolveur de citations suit la même date : « l'article L. 121-21 du code de la consommation avant 2016 » épingle la version de 2015 (quatorze jours), pas l'article de 2016 sur les frais de recouvrement.

### 3. Les marqueurs des lois compilées (LexML)

Une loi LexML est un seul document, sans historique : seule la rédaction en vigueur y figure, et les dispositions abrogées restent dans le texte avec leur marqueur. `marker_version` lit chaque chunk :

- un chunk dont **toutes** les dispositions sont marquées « (Revogado …) » ou « Vigência encerrada » ne dit rien qui soit en vigueur : sous `in_force`, il passe en fin de liste (`demoted`), sauf s'il s'agit de l'article cité, qui reste épinglé ;
- dans le prompt, une disposition abrogée est remplacée par une note (« § 2º [disposition abrogée : Revogado pela Lei nº 14.284, de 2021] ») : le modèle ne lit pas son ancienne rédaction ;
- « (Redação dada pela Lei nº … , de 2009) » marque la rédaction actuelle : le chunk le dit (« rédaction de 2009 »).

Une date passée ne peut pas être respectée sur ces textes (il n'y a pas d'ancienne rédaction) : la réponse le dit (`notice: "markers_no_history"`).

### 4. Ce que voit le modèle

Sous `in_force` ou `as_of`, chaque passage du contexte porte une ligne de statut ; les consignes du prompt (citer d'abord, puis répondre, mesurées en [prompt.md](benchmarks/prompt.md)) ne changent pas :

```text
[Source rank=1]
Fichier: consommation_L221-18_LEGIARTI000032226842.txt
Statut : version de l'article L221-18 en vigueur depuis le 1er juillet 2016.
Extrait: …

[Source rank=2]
Statut : ancienne version de l'article L121-21 (du 8 août 2015 au 1er juillet 2016), remplacée par Ordonnance n° 2016-301 du 14 mars 2016 — plus en vigueur.
```

Sous `all` (le défaut livré, la référence naïve), l'état est affiché dans l'interface mais pas donné au modèle : le prompt est identique, octet pour octet, à celui d'un corpus sans versions.

### 5. Ce que montre la réponse

Chaque chunk porte `version` (source `metadata` ou `markers`, état, en vigueur ou non à la date de référence, dates, texte qui l'a créée, texte qui l'a close, version suivante `replaced_by`, version en vigueur de l'article `in_force_version`, dispositions abrogées). La réponse porte `versions` : mode, date, d'où vient la date (`default`, `request`, `question`) et les mots de la question qui l'ont donnée, ce sur quoi la règle a pu agir (`scope` : `metadata`, `markers`, `none`), si le filtre a tourné, combien de chunks ont été déplacés, combien de passages périmés restent.

## Utilisation

| Où | Comment |
|---|---|
| CLI | `raglab query "Que prévoyait l'article L. 121-21 avant 2016 ?" --corpus bench_legi_consommation_fr` ; `--versions all`, `--versions as_of=2015-06-01` |
| API | `"versions": "in_force" \| "all" \| "as_of=AAAA-MM-JJ"` dans `POST /api/query`, `/api/query/stream`, `/api/experiments/recall` (422 sinon) ; défaut dans `/api/config` (`versions_default`) ; `features.version_history` dans `/api/corpora` |
| UI | Chat : « Options » → « Versions des articles » (corpus de lois seulement) ; page Interrogation (Atelier) : le même choix, un badge par passage (« en vigueur depuis le … », « ancienne version (… → …) », « abrogé le … », « dispositions abrogées ») et, en expert, ses dates, textes et successeur ; lancement des benchmarks |
| Mode pédagogique | une étape « Versions » après le re-ranking : la date utilisée, d'où elle vient, ce qui a été écarté, l'état des premiers passages, le code |
| Benchmark | `raglab bench all --suite legi_versions --versions all` (référence) contre `--versions in_force` |
| Par défaut | `RAGLAB_VERSIONS_DEFAULT=all` : la brique n'est pas encore mesurée, elle reste derrière l'option (règle du projet) ; `in_force` deviendra le défaut si la mesure montre un gain. Même sous `all`, chaque passage porte son état, affiché dans l'interface (pas donné au modèle) |

## La mesure

### Le jeu figé « versions »

`raglab legifrance version-questions` (`src/raglab/benchmarks/legi_versions.py`) construit environ 100 questions pièges, chacune avec la version qui répond (`expected_spans`) et celle qui tromperait (`trap`). Les questions sont des **situations**, posées comme le ferait un consommateur, une entreprise ou un avocat (« Mon client a sept jours pour se rétracter, c'est bien ça ? »), pas des « que dit l'article X ? » qu'un Ctrl+F résoudrait : aucun numéro d'article (sauf `reused_number`, où l'utilisateur cite le numéro qu'on lui a donné), aucun nom de code, aucune suite de 6 mots copiée de l'article ou du piège ; une date passée est dite comme un utilisateur date sa situation (« en 2021 », « en mai 2014 »). Les paires sont trouvées par des règles, sans modèle, dans l'historique du code :

| Type (`question_type`) | Part | La version qui répond | Le piège |
|---|---|---|---|
| `rewritten` | 40 % | la version en vigueur, sur une ligne réécrite ; la question peut avancer l'ancienne règle comme une croyance à vérifier | la version précédente, et son ancienne formulation (`trap.answer`) |
| `reused_number` | 20 % | la version en vigueur d'un numéro réutilisé ; la situation cite le numéro, comme on l'a cité à l'utilisateur | les anciens articles de même numéro (une autre règle) |
| `moved` | 20 % | l'article qui porte aujourd'hui la règle ; la question la reformule sans numéro | l'article abrogé dont le texte est passé sous un autre numéro (recouvrement de trigrammes ≥ 0,5) |
| `as_of` | 20 % | une ancienne version ; la situation est datée (« J'ai signé en 2021 … ») | la version en vigueur, et sa formulation |

Le modèle local (Qwen3.6 via llama.cpp, `LocalLLMServer`) écrit une question par paire, la réponse copiée de la version qui répond et, pour `rewritten` et `as_of`, la réponse périmée copiée du piège. Une question n'est gardée que si **les deux citations sont là où elles doivent être, et pas dans l'autre version** : chaque cas est un piège par construction. Autres contrôles : formulations vagues (« cet article »), formulation recopiée de l'article ou du piège (6 mots consécutifs), nom de code, citation d'article dans une question qui ne doit pas en avoir, numéro cité dans une question `reused_number` sous une forme que lit le résolveur, date lue par `parse_question_date` et couverte par l'ancienne version dans une question `as_of` (et aucune date dans les autres). Un article ne sert qu'une fois. Partie `dev` / `heldout` tirée avec la graine (un quart `dev` par type), comme pour les autres jeux.

Candidats trouvés dans le corpus figé (graine 42) : 353 `rewritten`, 297 `reused_number`, 586 `moved`, 344 `as_of`.

### La métrique

- **`outdated_hit@k`** : une version périmée est dans le top-k **au-dessus** de la version qui répond (ou celle-ci est absente du top-k). Sur le jeu « versions », « périmée » = un des fichiers du piège ; sur les autres jeux, une version qui ne s'applique pas à la date de référence (celle de la question, sinon aujourd'hui), ou un chunk entièrement abrogé. Plus bas = mieux. Comptée sur les questions où une version peut être périmée.
- **`outdated_answer_rate`** : parmi les réponses générées, celles qui reprennent la formulation périmée sans la bonne, ou citent le numéro du piège sans le bon (article déplacé).
- `raglab bench compare` compare `outdated_hit@k` question par question (corrigées / introduites, McNemar exact), en plus du Recall@k et du MRR, par type et par partie `dev` / `heldout`.

### Les commandes (GPU, à lancer)

```bash
raglab legifrance fetch --code consommation
raglab legifrance version-questions --count 100 --seed 42 --output-dir benchmarks/legi_versions
raglab legifrance review-questions --ground-truth benchmarks/legi_versions/ground_truth.jsonl

# RAG classique, puis pipeline complet sans la brique, puis avec
raglab bench all --suite legi_versions --label versions-naive-v1 --retrieval-mode dense --no-rerank --no-citations --versions all
raglab bench all --suite legi_versions --label versions-full-all-v1 --versions all
raglab bench all --suite legi_versions --label versions-full-v1 --versions in_force
raglab bench compare versions-naive-v1 versions-full-all-v1
raglab bench compare versions-full-all-v1 versions-full-v1

# Pas de régression sur les autres jeux
raglab bench all --suite legi_consommation --label legi-full-all-v1 --versions all
raglab bench all --suite legi_consommation --label legi-full-versions-v1 --versions in_force
raglab bench compare legi-full-all-v1 legi-full-versions-v1
raglab bench all --label versions-v1 --versions in_force
raglab bench compare full-v1 versions-v1
```

### Résultats

À mesurer. Le défaut livré est `all` ; `in_force` ne devient le défaut (`RAGLAB_VERSIONS_DEFAULT=in_force`) que si elle fait mieux que `all` sur le jeu figé sans coûter sur PIAF, LexML ni `legi_consommation`. Sinon elle reste une option, signalée comme telle.

## Limites

- **Dates de la source.** Les dates sont celles des données LEGI : 21 versions ont une date de fin antérieure à leur date de début ; elles ne s'appliquent à aucune date et sont donc toujours écartées sous `in_force`.
- **Une année vaut son dernier jour.** « Dans sa rédaction de 2014 » prend la version en vigueur le 31 décembre 2014, donc la dernière rédaction de l'année quand l'article a changé deux fois cette année-là (L. 121-21 : en juin puis en décembre 2014).
- **Dates lues par des règles.** Une formulation que les règles ne connaissent pas (« à l'époque de la loi Hamon », « il y a dix ans ») n'est pas lue ; la recherche reste alors sur les versions en vigueur. Les dates des textes ne sont jamais prises pour une date de référence, ce qui laisse de côté « dans sa rédaction issue de la loi du 17 mars 2014 ».
- **LexML n'a pas d'historique.** Seule la rédaction actuelle est dans le texte compilé ; une date passée n'y est pas respectée, et une disposition réécrite ne garde pas son ancienne formulation. Un chunk qui mêle dispositions en vigueur et abrogées reste à sa place ; seules les dispositions abrogées sont masquées au modèle.
- **BM25 compte toutes les versions.** Le filtre agit sur les candidats, pas sur les statistiques du corpus : la rareté d'un mot (idf) est calculée sur toutes les versions, abrogées comprises.
- **Filtrer, c'est exclure.** Sous `in_force`, une question qui ne dit pas qu'elle porte sur le passé ne voit pas les anciennes versions. C'est voulu (le défaut doit être le droit applicable) ; `all` ou `as_of` les rendent visibles.
- **Jeu généré par un modèle.** Les paires sont trouvées par des règles et les citations vérifiées mot pour mot, mais la question elle-même peut être ambiguë ; la relecture (`review-questions`) et la partie `heldout` sont là pour ça.
