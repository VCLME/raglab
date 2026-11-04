# Corpus de conformité réglementaire UE : RGPD, AI Act, DORA, NIS 2

La thèse de raglab (voir [audit-2026-11.md](audit-2026-11.md)) est que le RAG classique échoue sur les documents structurés, référencés et versionnés : identifiants, renvois, versions, hors périmètre. Le droit européen de la conformité est le cas industriel où ces quatre modes d'échec se cumulent : un considérant explique un article, un règlement délégué précise un article du règlement de base (« conformément à l'article 15 du règlement (UE) 2022/2554 »), un article renvoie au RGPD depuis l'AI Act, un règlement « omnibus » réécrit l'AI Act deux ans après son adoption, et le tout existe en 24 langues. Sans graphe des renvois, la réponse à « que doit contenir la politique visée à l'article 28 de DORA ? » reste dans un autre acte.

Ce corpus réunit **15 actes**, en **français, anglais et portugais**, avec leurs **versions consolidées** quand EUR-Lex en publie.

## La source

| Source | Ce qu'elle donne | Compte | Verdict |
|---|---|---|---|
| Pages HTML d'EUR-Lex (`eur-lex.europa.eu/legal-content/…`) | le texte, toutes langues | non | **écartée** : derrière un défi anti-robot (réponse `202` vide) ; on ne le contourne pas |
| **CELLAR, API REST** (`publications.europa.eu/resource/celex/<CELEX>`) | le XHTML du Journal officiel et des versions consolidées, par langue (`Accept-Language: fra`), avec les identifiants ELI de chaque considérant, article et annexe | **non** | **retenue** |
| CELLAR, point SPARQL (`publications.europa.eu/webapi/rdf/sparql`) | les liens entre actes : « fondé sur » (actes délégués et d'exécution), « modifie », versions consolidées publiées | non | **retenue pour choisir les actes** et vérifier les consolidations (`raglab eurlex acts --check`) |
| Formex 4 (XML du Journal officiel, même API) | structure fine (ARTICLE, PARAG, ALINEA) ; 171 Ko zippés pour l'AI Act | non | écarté : pas de version consolidée en Formex, donc deux analyseurs pour un seul gain de structure |
| Service web EUR-Lex (SOAP) | recherche experte | **oui** | écarté (pas de compte fourni) |
| Jeux en vrac (MultiEURLEX sur Hugging Face, dumps de data.europa.eu) | textes de lois pour la classification | non | écartés : sans considérants séparés, sans consolidations, sans renvois, ou des Go pour quelques Mo utiles |

Licence : © Union européenne ; réutilisation autorisée par la décision 2011/833/UE de la Commission (mention de la source). Chaque document porte le CELEX de son texte et le lien EUR-Lex correspondant (`source_url`).

Le XHTML de CELLAR est du XML bien formé (lu avec la bibliothèque standard, sans nouvelle dépendance). Le Journal officiel et les versions consolidées marquent les unités avec les mêmes identifiants ELI (`rct_39`, `art_6`, `art_4a`, `anx_III`) ; les versions consolidées portent en plus les marqueurs de modification (`▼M1`, `►C1 … ◄`) dont le lien nomme l'acte modificatif (« 32026R1744: INSERTED ») ou le rectificatif (« 32016R0679R(02) »).

**Volume** : 60 fichiers, 25 Mo (plafond fixé : 300 Mo). Les requêtes sont séquentielles, espacées d'une seconde (`--delay`), avec un User-Agent qui nomme le projet ; une collecte suivante relit le cache `raw/` sans aucune requête.

## Les actes

Choisis à partir des liens « fondé sur » et « modifie » de CELLAR (SPARQL), en gardant les actes en vigueur qui ont un contenu normatif propre :

| Clé | CELEX | Acte | Pourquoi |
|---|---|---|---|
| `gdpr` | 32016R0679 | RGPD | acte de base ; version consolidée (rectificatifs) |
| `ai_act` | 32024R1689 | AI Act | acte de base ; **réécrit par l'omnibus de 2026** (version consolidée du 27 juillet 2026) |
| `dora` | 32022R2554 | DORA | acte de base ; version consolidée (rectificatifs) |
| `nis2` | 32022L2555 | NIS 2 | acte de base (directive) |
| `dora_rts_ict_risk` | 32024R1774 | RTS cadre de gestion du risque lié aux TIC | DORA, art. 15 et 16 |
| `dora_rts_incident_classification` | 32024R1772 | RTS classification des incidents | DORA, art. 18 |
| `dora_rts_ict_services_policy` | 32024R1773 | RTS politique d'utilisation des services TIC de tiers | DORA, art. 28 |
| `dora_rts_incident_reporting` | 32025R0301 | RTS contenu et délais de notification des incidents | DORA, art. 20 |
| `dora_rts_tlpt` | 32025R1190 | RTS tests de pénétration fondés sur la menace | DORA, art. 26 |
| `dora_rts_subcontracting` | 32025R0532 | RTS sous-traitance des services TIC | DORA, art. 30 |
| `dora_ctpp_criteria` | 32024R1502 | critères de désignation des prestataires TIC critiques | DORA, art. 31 |
| `nis2_risk_measures` | 32024R2690 | règlement d'exécution, mesures de gestion des risques | NIS 2, art. 21 et 23 |
| `ai_act_scientific_panel` | 32025R0454 | règlement d'exécution, groupe scientifique | AI Act, art. 68 |
| `ai_omnibus` | 32026R1744 | règlement (UE) 2026/1744, « omnibus numérique sur l'IA » | modifie l'AI Act : source des versions |
| `gdpr_scc` | 32021D0914 | clauses contractuelles types (transferts) | RGPD, art. 28 et 46 |

Laissés de côté : les formulaires et modèles (ITS 2024/2956 et 2025/302 de DORA : quelques articles autour de centaines de pages de tableaux), les décisions d'adéquation (une par pays, longues et répétitives), les actes de procédure (redevances de supervision, équipes d'examen conjointes, procédures de la Commission au titre de l'AI Act). La liste est dans `src/raglab/eurlex/acts.py` ; les règles n'en dépendent pas.

**Versions consolidées figées** : `02016R0679-20160504`, `02024R1689-20260727`, `02022R2554-20221227`, `02022L2555-20221227`, `02024R1774-20240625`. La consolidation `02024R1689-20240712` est le texte du Journal officiel lui-même (et n'existe pas en anglais dans CELLAR) : elle n'apporte rien. CELLAR n'a pas DORA consolidé en anglais ni NIS 2 consolidé en portugais : ces langues gardent le texte du Journal officiel (`downloads.missing` du manifeste).

## La collecte

```bash
raglab eurlex fetch                       # les 15 actes, fr + en + pt
raglab eurlex fetch --acts gdpr,ai_act,dora,nis2 --lang fr,en
raglab eurlex acts --check                # consolidations publiées depuis le gel
```

Sans la ligne de commande : l'onglet Corpus › « Légifrance et EUR-Lex » de l'Atelier (bouton « Collecter et ingérer ») lance la collecte des 15 actes en tâche de fond, puis ingère le corpus dans `bench_eurlex_compliance` sans l'indexer (`POST /api/sources/eurlex/fetch`, ou `raglab sources fetch eurlex` ; voir [api-production.md](api-production.md#collecte-des-sources-officielles--apisources)). L'espacement des requêtes vient alors de `RAGLAB_EURLEX_REQUEST_DELAY_SECONDS` (1 s par défaut).

Sortie dans `data/eurlex/compliance/` (hors git) :

- `raw/` : le XHTML téléchargé, un fichier par CELEX et par langue ;
- `corpus/` : un `.txt` et un `.json` par **considérant, article ou annexe, par langue et par version** ;
- `manifest.json` : l'empreinte SHA-256 de chaque texte et de chaque fichier téléchargé, la version des règles de renvoi (copie figée : [`benchmarks/eurlex_compliance/corpus_manifest.json`](../benchmarks/eurlex_compliance/corpus_manifest.json)) ;
- `stats.json` : les chiffres ci-dessous.

Deux collectes depuis le même cache donnent un manifeste identique. Durée : une minute de téléchargement la première fois, puis environ 30 secondes.

### Un document par unité, par langue et par version

- **L'unité est ce qu'on cite** : « article 32 du RGPD », « considérant 39 », « annexe III de l'AI Act ». Une citation se résout en un document par ses métadonnées, sans chercher où l'article commence dans un texte de 80 pages.
- **Les considérants sont des documents** : ils expliquent les articles et sont souvent la meilleure réponse à « pourquoi ».
- **Les trois langues partagent la même clé** (`unit_key` = CELEX + type + numéro) : une question en français peut être comparée à sa réponse en anglais, et le graphe relie les trois versions linguistiques (`SAME_AS`).
- **Chaque version porte son état** (`in_force`, `valid_from`, `valid_to`) sans bandeau dans le texte : au pipeline de s'en servir.
- **Les stratégies de découpage ne changent pas.**

Le texte d'un document : une ligne d'en-tête (« Règlement (UE) 2016/679 (RGPD) — Article 6 »), le titre de l'article, puis un paragraphe ou un point par ligne, le libellé du point devant son texte (« a) la personne concernée a consenti… »). Les appels de note et les marqueurs de consolidation sont retirés.

| Métadonnée | Exemple |
|---|---|
| `act`, `act_short`, `act_label`, `celex`, `act_type`, `act_role`, `base_celex`, `eli` | `gdpr`, `RGPD`, « Règlement (UE) 2016/679 (RGPD) », `32016R0679`, `regulation`, `base`, `null`, lien ELI |
| `unit`, `unit_number`, `unit_label`, `unit_title`, `unit_key` | `article`, `6`, « Article 6 », « Licéité du traitement », `32016R0679:article:6` |
| `paragraphs` | `[{"number": "1", "points": ["a", "b", …]}, …]` |
| `language` | `fr`, `en`, `pt` (le BM25 utilise la configuration de la langue du document) |
| `source_celex`, `version_kind`, `consolidation_date` | `32016R0679` (Journal officiel) ou `02024R1689-20260727` ; `original`, `corrigendum`, `amendment`, `inserted` |
| `valid_from`, `valid_to`, `in_force`, `version`, `version_count`, `versions` | dates de la version, rang, liste des versions de l'unité dans la langue |
| `amended_by` | `[{"celex": "32026R1744", "actions": ["replaced"]}]` (marqueurs de la version consolidée) |
| `references` | renvois lus par les règles : `{"unit", "number", "celex", "scope", "paragraph", "point", "text", "implicit"}` |
| `act_references` | actes nommés dans le texte (`celex`, `in_corpus`) |
| `legal_basis` | base juridique d'un acte délégué ou d'exécution : `[{"celex": "32022R2554", "articles": ["15", "16"], "citation": "vu le règlement…"}]` |
| `amends_celex` | l'acte qu'un article modificatif modifie |

## Les chiffres

| | |
|---|---|
| Documents | **4 236** (2 559 considérants, 1 581 articles, 96 annexes) |
| Unités distinctes | 1 359 ; 4 077 couples unité × langue |
| Par langue | 1 417 fr, 1 408 en, 1 411 pt (les rectificatifs ne touchent pas toutes les langues) |
| Versions | 4 056 du Journal officiel, 126 versions marquées par l'omnibus (`amendment`), 9 sans marqueur propre (`inserted` : articles 75b à 75d), 45 rectificatifs (`corrigendum`) |
| Unités avec plus d'une version | 63 : 38 de l'AI Act, 14 du RGPD, 7 de DORA, 3 de NIS 2, 1 du RTS 2024/1774 ; plus 7 unités de l'AI Act qui n'existent que dans la version consolidée |
| Taille | 7,9 millions de caractères (médiane 1 133 par document) ; LexML : 4,6 M, Code de la consommation : 5,6 M |

| Acte | Considérants | Articles | Annexes | Documents (3 langues) |
|---|---|---|---|---|
| RGPD | 173 | 99 | 0 | 848 |
| AI Act | 180 | 119 (dont 6 insérés) | 14 (dont 1 insérée) | 1 053 |
| DORA | 106 | 64 | 0 | 517 |
| NIS 2 | 144 | 46 | 3 | 582 |
| 7 actes de niveau 2 de DORA | 121 | 104 | 8 | 702 |
| règlement d'exécution NIS 2 | 43 | 16 | 1 | 180 |
| groupe scientifique de l'AI Act | 13 | 20 | 0 | 99 |
| omnibus IA (2026/1744) | 47 | 4 | 0 | 153 |
| clauses contractuelles types | 26 | 4 | 4 | 102 |

**Renvois** (versions en vigueur, règles v5) : 9 632 mentions, dont **7 873 vers une unité du corpus** (4 132 article → article dans le même acte, **1 395 article → article d'un autre acte**, 540 considérant → article d'un autre acte, 571 article → annexe), 1 529 vers des actes hors corpus (règlement (UE) nº 1093/2010 instituant l'ABE : 195 ; règlement (UE) 2019/1020 : 128 ; règlement (UE) 2018/1725 : 80…), 203 vers les traités, 27 vers une unité introuvable. Bases juridiques : les 10 actes délégués ou d'exécution retrouvent tous leurs articles de base (« DORA, art. 15 et 16 » pour le RTS 2024/1774).

## Ce que chaque mode d'échec y trouve

**1. Identifiants.** « Article 6 » existe dans 13 des 15 actes : 39 documents en vigueur portent ce numéro. « Article 6(1)(a) GDPR », « article 32, paragraphe 1, point b), du RGPD », « artigo 5.º do RGPD » doivent tomber sur le bon : c'est le terrain du résolveur de citations.

**2. Renvois.** 1 395 renvois article → article passent d'un acte à l'autre. Un RTS de DORA ne se comprend qu'avec l'article de DORA qu'il précise ; l'article 3, point 50, de l'AI Act définit les données à caractère personnel « au sens de l'article 4, point 1), du règlement (UE) 2016/679 ». C'est le cas où le graphe est indispensable.

**3. Versions.** L'omnibus numérique sur l'IA (règlement (UE) 2026/1744, juillet 2026) a réécrit 38 unités de l'AI Act et en a inséré 7 (articles 4a, 60a, 75a à 75d, annexe XIV) : l'obligation de maîtrise de l'IA de l'article 4 n'est plus la même, les dates d'application de l'article 113 ont changé. Les deux rédactions sont dans le corpus ; un RAG classique cite l'ancienne. Les rectificatifs du RGPD (« et » devenu « ou » à l'article 37 en français) donnent un cas plus fin.

**4. Hors périmètre.** 1 529 renvois pointent vers des actes absents (règlement ABE, directive Police-Justice, MiFID II) : une question sur ceux-là n'a pas de réponse dans le corpus. Le résolveur les reconnaît (« article 10 de la directive (UE) 2016/680 ») et, ne trouvant pas l'acte, laisse la recherche inchangée.

## Le résolveur de citations, profil UE

`src/raglab/retrieval/citations.py` lit les citations d'actes de l'UE (voir [citations.md](citations.md#profil-ue-actes-européens)) :

| Question | Citation lue |
|---|---|
| « Que dit l'article 32 du RGPD ? » | Article 32 — RGPD (`32016R0679`, article 32, fr) |
| « What does Article 6(1)(a) GDPR require? » | Article 6(1)(a) — GDPR |
| « O que prevê o artigo 5.º do Regulamento (UE) 2016/679? » | Artigo 5 — RGPD |
| « Que dit le considérant 39 du RGPD ? » | Considérant 39 — RGPD |
| « What does the GDPR say about consent? » | l'acte seul : recherche restreinte au RGPD |
| « What does Article 6 say about lawfulness? » | rien : un numéro sans acte nommé n'est pas une citation |

L'unité est retrouvée par ses métadonnées (`celex`, `unit`, `unit_number`) dans la langue de la question si le corpus l'a, sinon dans une autre ; la version en vigueur d'abord. Ses chunks sont épinglés en tête et la recherche est restreinte à l'acte (`metadata_equals` sur `celex`). Les profils brésilien et français sont lus avant, inchangés.

## Le graphe, profil `eu_acts`

Chaque document étant déjà une unité, le profil lit les renvois dans les métadonnées, sans relire le texte (voir [graphe.md](graphe.md#profil-actes-de-lue)) : `(:Act)`, `(:Article|:Recital|:Annex)`, `CITES`, `EXPLAINS`, `SUPPLEMENTS`, `AMENDS`, `SAME_AS`. Sur le corpus : 108 actes (15 collectés, 93 cités hors corpus), 5 034 `CITES` vers un article, 470 vers une annexe, 886 vers un acte hors corpus ou une unité introuvable, 5 `EXPLAINS`, 38 `SUPPLEMENTS`, 126 `AMENDS`, 4 221 `SAME_AS`. Construction : 0,8 s.

### Précision, vérifiée à la main

`raglab eurlex graph-sample` tire environ 40 arêtes avec une graine, sans PostgreSQL ni Neo4j (le graphe est construit à partir des fichiers du corpus) ; chaque arête a été lue avec la phrase qui porte le renvoi, et le verdict est versionné dans `benchmarks/eurlex_compliance/graph_precision_v*_seed*.json`. Chaque correction des règles a été mesurée sur une graine neuve, jamais sur l'échantillon qui l'avait motivée :

| Règles | Graine | CITES dans l'acte | CITES entre actes | EXPLAINS | SUPPLEMENTS | AMENDS | SAME_AS | Total |
|---|---|---|---|---|---|---|---|---|
| v1 | 42 | 10/10 | 10/10 | 0/6 | 6/6 | 4/4 | 4/4 | 34/40 |
| v2 | 43 | 10/10 | 10/10 | 3/6 | 6/6 | 4/4 | 4/4 | 37/40 |
| v3 | 44 | 10/10 | 10/10 | 3/6 | 6/6 | 4/4 | 4/4 | 37/40 |
| v4 | 45 | 9/10 | 10/10 | 3/6 (12/20 sur toutes) | 6/6 | 4/4 | 4/4 | 36/40 |
| **v5 (livrée)** | **46** | **10/10** | **10/10** | **5/5 (toutes)** | **6/6** | **4/4** | **4/4** | **39/39** |

Les erreurs trouvées, toutes transformées en règles testées : plages de points lues comme des plages d'articles (« points 4) à 23) »), recommandations non reconnues comme actes (« l'article 2 de l'annexe de la recommandation 2003/361/CE »), possessifs (« ses articles 12 à 15 », « son article 3 »), « respectivement » entre le renvoi et son acte, « thereof » des visas anglais rattaché au dernier acte du titre, « do referido Regulamento », « of that Annex », renvoi entre parenthèses juste après l'acte. **`EXPLAINS` ne garde que les renvois qui nomment leur propre acte** (« de l'article 26, paragraphe 10, du présent règlement ») : un considérant cite rarement un article de son propre acte, et un numéro sans acte y désigne trop souvent l'article d'un autre texte (12 bonnes sur 20 en v4). On perd du rappel (5 arêtes au lieu de 20, 23 renvois implicites écartés) pour une précision vérifiée.

Les arêtes sont aussi vérifiées dans Neo4j (`tests/test_graph_structured_store.py`, avec `RAGLAB_TEST_NEO4J_URI`) : écriture, comptes, et la requête de la branche graphe qui suit un renvoi d'un article de DORA à un autre.

## Le jeu de questions (à générer)

Le générateur suit le protocole LexML ([protocole.md](benchmarks/protocole.md#actes-de-lue-conformité)) : passages tirés dans les unités **en vigueur**, une unité (toutes langues confondues) à la fois, articles et annexes d'abord, dans une langue tirée avec la graine ; questions écrites par Qwen3.6-35B-A3B via llama.cpp (`LocalLLMServer`), réponse copiée mot pour mot et retrouvée dans le texte, filtres dans les trois langues, relecture, partie `dev` / `heldout` tirée avec la graine. Six types. Le type principal (au moins la moitié du jeu) est le **scénario** : une question qui cite l'article se résout par un Ctrl+F, une situation concrète demande de comprendre le texte.

| Type | La question… | Contrôle |
|---|---|---|
| `scenario` (≥ 50 %) | décrit une situation de conformité vue par une entreprise, un DPO ou une banque, en langage courant (« Nous avons subi hier une attaque par rançongiciel sur notre système de paiement : qui devons-nous prévenir, et dans quel délai ? », « Notre chatbot RH peut-il trier les CV automatiquement ? ») ; tirée des articles et annexes seulement | ne nomme aucun acte (ni numéro, ni nom court : RGPD, DORA…), aucun article, considérant ou annexe, et ne partage pas 5 mots consécutifs avec le passage |
| `paraphrase` | reformule, sans numéro d'unité (l'acte peut être nommé) | pas de citation d'unité lue par le résolveur |
| `reference` | cite l'unité comme un juriste (« article 33 du RGPD ») | le résolveur lit exactement cette unité |
| `entity` | s'appuie sur un sigle ou un nom propre (ENISA, CSIRT, Bureau de l'IA) | pas de numéro d'unité |
| `cross_reference` | cite l'unité A ; la réponse est dans l'unité B que A cite | A est lue par le résolveur, le numéro de B n'apparaît pas, la réponse n'est pas dans A ; pertinence sur B seule, la phrase de A dans `citing_spans` |
| `cross_language` | est posée dans une autre langue que le passage | langue de la question vérifiée |

Les questions `reference` et `cross_reference` restent minoritaires ; le rapport de benchmark donne Recall@k et MRR par type (`by_type`) et par partie (`by_split`), et `metadata.json` la part de scénarios (`scenario_share`). `context` note l'unité, les langues de la question et du passage, les fichiers de la même unité dans les autres langues, le nombre de versions et si la réponse figure aussi dans une version ancienne (`answer_in_other_version`, les articles réécrits par l'omnibus).

```bash
raglab eurlex fetch
raglab eurlex questions --count 300 --seed 42 --output-dir benchmarks/eurlex_compliance
raglab eurlex review-questions --ground-truth benchmarks/eurlex_compliance/ground_truth.jsonl
raglab bench all --suite eurlex_compliance --label eurlex-baseline-v1 --retrieval-mode dense --no-rerank --no-citations
raglab bench all --suite eurlex_compliance --label eurlex-full-v1
raglab bench all --suite eurlex_compliance --label eurlex-graph-v1 --graph
raglab bench compare eurlex-full-v1 eurlex-graph-v1
```

La suite `eurlex_compliance` (corpus `bench_eurlex_compliance`) ne tourne que si on la demande (`--suite`). Pour le graphe : `RAGLAB_GRAPH_PROFILES='{"bench_eurlex_compliance": "eu_acts"}'` (le profil est aussi détecté tout seul) ; la précision se redessine avec `raglab eurlex graph-sample --seed 47 --output …` puis `raglab eurlex graph-report --sample …`.

## Limites connues

- **Considérants des versions consolidées** : EUR-Lex ne consolide pas les préambules ; un considérant garde le texte du Journal officiel, même si un rectificatif l'a corrigé.
- **Rectificatifs** : seuls ceux que la version consolidée intègre sont vus (marqueurs `►C`). Ils ne touchent pas toutes les langues de la même façon : le nombre de versions d'une unité peut différer d'une langue à l'autre.
- **Dates de version** : la version du Journal officiel commence à sa date de publication, une version consolidée à la date de la consolidation (date d'application de la dernière modification), pas à l'entrée en vigueur de chaque disposition.
- **Renvois par règles** : 27 renvois en vigueur pointent vers une unité introuvable ; « l'article précédent », les sections et chapitres (« chapitre III, section 2 ») ne sont pas lus ; un renvoi sans acte nommé est rattaché à l'acte lu, ou à l'acte de base s'il n'existe que là (`scope: inferred`, 67 renvois).
- **Corpus multilingue, BM25** : chaque document est indexé avec la configuration de sa langue (anglais : configuration simple) ; la question, elle, est analysée avec la langue du corpus. À mesurer sur les questions `cross_language`.
- **Libellés de la page Graphe** : l'interface affiche les articles des actes de l'UE avec les libellés prévus pour les lois brésiliennes (« Art. 6º »). Le voisinage et la branche de recherche fonctionnent ; l'affichage est à reprendre.
