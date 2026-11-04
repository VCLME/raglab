# Jeu de validation n° 2 du routeur (`routing_validation_2`)

## Objet

Second jeu de validation **indépendant** du routeur de requêtes. Il a été
écrit **après** la lecture des résultats du premier jeu de validation, pour
tester la variante de routeur retenue entre-temps sur des questions qu'aucune
étape de conception n'a vues. Le premier jeu ayant servi à choisir cette
variante, il n'est plus un témoin neutre : celui-ci le remplace comme mesure
finale.

Il mesure, sur des questions rédigées comme celles de vrais utilisateurs :

- les **refus à tort** de questions légitimes (`in_scope.jsonl`, 160 questions
  auxquelles un passage précis des corpus répond) ;
- le **rappel des refus** (`abstention.jsonl`, 80 questions auxquelles le
  routeur doit refuser de répondre).

## Indépendance

Règles appliquées pendant la rédaction :

- aucune lecture de `docs/`, `src/raglab/routing/`, `src/raglab/experiments/`,
  `benchmarks/routing/`, `benchmarks/routing_validation/`,
  `benchmarks/abstention/`, ni d'aucun fichier `ground_truth*.jsonl`,
  `calibration*.jsonl` ou `intent_training*.jsonl` ;
- aucune recherche des questions existantes dans le dépôt ;
- questions écrites uniquement à partir des documents bruts des corpus
  (table `documents` de Postgres) et de connaissances générales.

## Construction

### Questions dans le périmètre (`in_scope.jsonl`)

Passages tirés avec `random.Random(2027)` (graine différente de 2026, utilisée
ailleurs) :

| Corpus | Tirage | Questions |
|---|---|---|
| `bench_piaf_fr` | documents mélangés, une fenêtre aléatoire par document | 40 fr |
| `bench_lexml_pt` | position aléatoire proportionnelle à la longueur du texte | 20 pt + 20 fr |
| `bench_br_expat_pt` | uniquement les documents d'**indice impair** dans la liste triée par `file_name` (`decreto_8300_2014`, `ec_103_2019`, `in_srf_208_2002`, `lc_123_2006`, `lei_10637_2002`, `lei_10833_2003`, `lei_14754_2023`, `lei_7115_1983`, `lei_9249_1995`), position proportionnelle à la longueur | 40 fr (Français qui s'installe au Brésil) |
| `bench_eurlex_compliance` | fichiers mélangés par langue (`_en_`, `_fr_`, `_pt_`), passage dans la langue de la question | 14 en + 13 fr + 13 pt |

Le passage est une suite de lignes entières de 100 à 800 caractères
(coupée à une fin de phrase au besoin). On a tiré plus de candidats que
nécessaire et pris les premiers utilisables **dans l'ordre du tirage** ; ont
été écartés les tableaux budgétaires, formules de promulgation, listes de
communes, crédits supplémentaires, fragments de liste sans tête et un passage
au contexte ambigu.

Rédaction : environ la moitié des questions à la première personne ou en
situation (`first_person`, `informal`), le reste impersonnel ; 8 à 27 mots ;
quelques fautes, minuscules ou points d'interrogation manquants ; paraphrase
systématique, rares numéros de loi ou d'article. Profils pour EUR-Lex : DPO,
responsable conformité, RSSI, DRH, développeur, dirigeant de PME.

Chaque ligne porte un `expected_spans` dont le `text` est vérifié par
programme égal à `content[start:end]` dans la base.

### Questions à refuser (`abstention.jsonl`)

| Catégorie | fr | pt | en | Total |
|---|---|---|---|---|
| `out_of_scope` (données personnelles, info en direct, tâches : rédiger, traduire, calculer, coder ; conseil, opinion, affaires internes d'entreprise, santé, produit) | 16 | 12 | 12 | 40 |
| `near_miss` (lois d'autres pays, événements après 2025, numéros de loi ou d'article inventés, entités absentes de PIAF, actes UE hors RGPD/AI Act/DORA/NIS2 non cités) | 12 | 9 | 9 | 30 |
| `conversational` (salutation, remerciement, identité, capacités) | 4 | 3 | 3 | 10 |

**Contrôle d'absence** pour chaque `near_miss` : chaque clé (entité, numéro,
acte) est cherchée dans les quatre corpus, en `ILIKE '%clé%'` pour les clés
multi-mots ou chiffrées, en regex insensible à la casse à frontières de mot
(`~* '\mclé\M'`) pour les acronymes courts. Seules les questions à **zéro
occurrence** sont conservées. Candidats rejetés car présents : Digital
Services Act (2022/2065 cité), Data Act (2023/2854), MiCA (2023/1114), Pix,
Espace européen des données de santé, LGPD (13.709 cité), Ouro Preto,
batteries, Cyber Resilience Act (2024/2847), Maria da Penha (11.340 cité),
Santos Dumont, Bolsa Família.

## Effectifs

- `in_scope.jsonl` : 160 lignes ; styles : 87 `impersonal`, 54
  `first_person`, 19 `informal`.
- `abstention.jsonl` : 80 lignes (40 / 30 / 10).
- Identifiants uniques (`val2-in-001`… et `val2-abs-001`…), questions
  uniques, JSONL validé.

## Limites

- Un seul rédacteur (modèle), sans double annotation : le style « réel » est
  imité, pas collecté auprès d'utilisateurs.
- Une seule référence par question : un autre passage peut aussi répondre,
  ce qui ne gêne pas la mesure de routage mais peut sous-estimer le rappel
  passage.
- Les passages lexml et BR Expat sont souvent très techniques (fiscalité,
  marchés publics) ; certaines questions restent proches du vocabulaire
  juridique faute d'équivalent courant.
- Le contrôle d'absence est lexical : une paraphrase du sujet pourrait
  exister dans les corpus sans la clé exacte. Les `near_miss` « numéro
  inventé » supposent que le numéro n'existe pas, ce qui n'est vérifié que
  dans les corpus.
- Certaines `out_of_scope` (conseil d'investissement, santé) touchent des
  thèmes voisins des corpus (fiscalité, données de santé) : c'est voulu, mais
  leur refus peut dépendre de la politique d'abstention plus que du routage.

## Questions retirées avant la mesure

Avant toute mesure, chaque question a été comparée aux textes d'apprentissage et de calibration du routeur (exemples d'intention, `intent_training.jsonl`, questions de calibration) : 9 questions à moins de 0,95 de cosinus d'un de ces textes ont été retirées, pour que le jeu reste indépendant. Le modèle évalué étant déjà figé, c'est le jeu qui perd ces questions, pas l'apprentissage : `val2-in-142` (in-scope) et `val2-abs-011`, `-012`, `-013`, `-020`, `-026`, `-033`, `-076`, `-078` (formulations génériques : congés, ordre du jour, lettre de motivation, salutations). Restent 159 questions in-scope et 72 à refuser.
