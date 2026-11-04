# Jeu de validation indépendant du routeur

Ce dossier contient un jeu de questions **indépendant** de tout ce qui a servi à
entraîner ou calibrer le routeur de requêtes (intention, kNN, seuils
d'abstention). Il mesure, sur des questions rédigées comme le feraient de vrais
utilisateurs :

- **les faux refus** : questions légitimes, dont la réponse figure dans un
  passage d'un des quatre corpus indexés, que le routeur ne devrait jamais
  refuser (`in_scope.jsonl`) ;
- **le rappel de l'abstention** : questions auxquelles les corpus ne permettent
  pas de répondre et que le routeur doit refuser (`abstention.jsonl`).

## Fichiers

| Fichier | Lignes | Contenu |
|---|---:|---|
| `in_scope.jsonl` | 160 | questions dans le périmètre, avec le passage de réponse (`expected_spans`) |
| `abstention.jsonl` | 80 | questions à refuser : `out_of_scope`, `near_miss`, `conversational` |

Format d'une ligne `in_scope.jsonl` :

```json
{"id": "val-in-001", "question": "...", "language": "fr|pt|en",
 "expected_corpus": "<corpus>", "expected_spans": [{"file_name": "...", "start": 0, "end": 0, "text": "..."}],
 "style": "first_person|impersonal|informal", "review_status": "accepted"}
```

`text` vaut exactement `documents.content[start:end]` (vérifié par script pour
chaque ligne) et fait entre 100 et 800 caractères.

Format d'une ligne `abstention.jsonl` :

```json
{"id": "val-abs-001", "language": "fr|pt|en", "category": "out_of_scope|near_miss|conversational",
 "subtype": "<étiquette courte>", "question": "..."}
```

## Construction

### Règles d'indépendance

La personne (un LLM) qui a rédigé le jeu n'a ouvert **aucun** des fichiers
suivants : `docs/`, `src/raglab/routing/`, `benchmarks/routing/`,
`benchmarks/abstention/`, ni aucun fichier `ground_truth*.jsonl`,
`calibration*.jsonl` ou `intent_training*.jsonl`. Aucune recherche des
questions existantes n'a été faite dans le dépôt. Les questions ont été écrites
uniquement à partir des documents bruts des corpus (table `documents` de
Postgres) et de connaissances générales.

### Échantillonnage des passages (`in_scope.jsonl`)

Tous les tirages utilisent `random.Random(2026)`. Documents triés par
`file_name`.

- `bench_piaf_fr` (761 documents) : 44 documents tirés sans remise, fenêtre de
  900 caractères à position aléatoire ; 40 retenus.
- `bench_lexml_pt` (252 lois) : 44 documents tirés sans remise, même fenêtre ;
  40 retenus (les fenêtres trop pauvres, faites uniquement de renvois ou de
  points de suspension, ont été écartées). Une partie des passages sont des
  tableaux budgétaires (crédits spéciaux, suppléments) : les questions portent
  alors sur un montant ou une ligne du tableau.
- `bench_br_expat_pt` (19 textes) : **seuls les documents d'indice impair**
  (1, 3, 5, … dans la liste triée) sont utilisés, soit 9 textes
  (`decreto_8300_2014`, `ec_103_2019`, `in_srf_208_2002`, `lc_123_2006`,
  `lei_10637_2002`, `lei_10833_2003`, `lei_14754_2023`, `lei_7115_1983`,
  `lei_9249_1995`). Les positions sont tirées proportionnellement à la longueur
  des textes (un premier tirage uniforme par document sur-représentait la très
  courte `lei_7115_1983`) ; 52 fenêtres, 40 retenues. Les 40 questions
  touchent finalement 8 textes.
- `bench_eurlex_compliance` : fichiers par article ou considérant de 300
  caractères ou plus, filtrés par langue via `_en_`, `_fr_`, `_pt_` ; 16 / 15 /
  15 tirés, 14 / 13 / 13 retenus. Le passage est toujours dans la langue de la
  question.

Pour chaque question, le span de réponse a été délimité à la main (phrase de
début, phrase de fin), puis ses positions calculées et contrôlées par script
contre `documents.content`.

### Style des questions

Rédaction volontairement « utilisateur » : environ la moitié à la première
personne ou en situation (« je viens de m'installer à Rio… », « I run a small
online shop… »), le reste impersonnel ou familier ; longueur de 5 à 44 mots ;
quelques fautes, minuscules ou points d'interrogation manquants ; reformulation
plutôt que reprise du texte ; quasiment aucun numéro de loi ou d'article.
Profils : grand public curieux (PIAF), francophone qui interroge le droit
brésilien (LexML), Français qui s'installe au Brésil (expat), praticiens de la
conformité (DPO, responsable conformité, développeur, petit patron) pour
EUR-Lex.

### Questions à refuser (`abstention.jsonl`)

- `out_of_scope` : données personnelles, informations en temps réel (météo,
  cours, scores, actualités), tâches (rédiger, traduire, calculer, coder),
  conseils et opinions, affaires internes d'une entreprise.
- `near_miss` : questions d'allure documentaire, proches des corpus, mais sans
  réponse dedans : lois d'autres pays (Portugal, Québec, Californie, Canada,
  Royaume-Uni, ville de New York, France), événements de 2026, lois ou
  articles inventés (loi 15.987, article 412-B, article 147 du RGPD, « NIS3 »),
  entités encyclopédiques absentes de PIAF, actes européens hors RGPD / AI Act
  / DORA / NIS2 (Digital Markets Act).
- `conversational` : salutations, remerciements, questions sur l'assistant.

**Contrôle d'absence des near_miss.** Pour chaque candidat, une ou plusieurs
expressions clés ont été cherchées dans `documents.content` sur les quatre
corpus : `ILIKE '%clé%'` pour les expressions, et pour les sigles courts une
regex insensible à la casse avec bornes de mot (`~* '\mclé\M'`), sinon `MiCA`
correspondrait à « química ». Seuls les candidats sans aucune occurrence ont
été gardés. Candidats **rejetés** parce que le sujet est présent dans les
corpus :

- MiCA / crypto-actifs (fr, pt, en) : DORA cite le règlement sur les marchés
  de crypto-actifs ;
- Data Act (fr, en) : le considérant 141 de l'AI Act cite le règlement
  2023/2854 ;
- Cyber Resilience Act : cité par l'AI Act, DORA et NIS2 ;
- LGPD (pt) : la loi 13.709 est citée par plusieurs lois de LexML ;
- Colorado AI Act : « Colorado » apparaît dans PIAF et LexML.

Quatre candidats absents ont été écartés seulement pour respecter les quotas
(Ballon d'or 2026, Tromsø, résident non habituel en pt, TRAIGA).

## Effectifs

`in_scope.jsonl` (160) :

| Corpus | fr | pt | en | Total |
|---|---:|---:|---:|---:|
| `bench_piaf_fr` | 40 | | | 40 |
| `bench_lexml_pt` | 20 | 20 | | 40 |
| `bench_br_expat_pt` | 40 | | | 40 |
| `bench_eurlex_compliance` | 13 | 13 | 14 | 40 |

| Style | PIAF | LexML | Expat | EUR-Lex | Total |
|---|---:|---:|---:|---:|---:|
| `first_person` | 20 | 19 | 24 | 16 | 79 |
| `impersonal` | 13 | 19 | 14 | 19 | 65 |
| `informal` | 7 | 2 | 2 | 5 | 16 |

`abstention.jsonl` (80) :

| Catégorie | fr | pt | en | Total |
|---|---:|---:|---:|---:|
| `out_of_scope` | 16 | 12 | 12 | 40 |
| `near_miss` | 12 | 9 | 9 | 30 |
| `conversational` | 4 | 3 | 3 | 10 |

## Limites

- **Pas de vrais logs.** Toutes les questions ont été écrites par un LLM qui
  imite un style d'utilisateur. Elles restent plus propres, plus complètes et
  plus homogènes que des requêtes réelles (peu de fautes, pas de copier-coller,
  pas de questions en plusieurs messages).
- **Un seul rédacteur, une seule passe.** Pas de double annotation ni d'accord
  inter-annotateurs ; `review_status: accepted` signifie seulement que le span
  a été vérifié par script et relu par le rédacteur.
- **Ancrage sur un passage.** Chaque question in-scope a été écrite *depuis* un
  passage : la formulation peut en garder des indices lexicaux, ce qui avantage
  les signaux lexicaux par rapport à des questions spontanées.
- **Questions budgétaires.** Huit questions LexML portent sur des tableaux
  budgétaires (montant d'une ligne de crédit) ; elles sont réalistes pour un
  analyste, moins pour le grand public.
- **Absence vérifiée par mots-clés.** Le contrôle des near_miss est lexical :
  une paraphrase du même sujet dans une autre langue ou sous un autre nom
  pourrait exister dans les corpus sans être détectée.
- **Effectifs modestes.** 160 + 80 questions : un écart de 1 à 2 points de
  taux entre deux configurations du routeur n'est pas significatif.
- **Corpus expat partiel.** Seuls les textes d'indice impair sont couverts, et
  8 d'entre eux seulement apparaissent dans les réponses (`lc_123_2006` : 13
  questions, `lei_10833_2003` : 9 ; `lei_7115_1983` : aucune).
