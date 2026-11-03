# Protocole de benchmark

Ce document décrit comment raglab mesure la qualité du retrieval, et pourquoi les jeux de données ont été refaits avant la baseline de la phase 9.1. Les chiffres eux-mêmes vivent dans [baseline.md](baseline.md) (phase 9.1b).

## Pourquoi refaire les jeux

Les deux jeux existants donnaient des scores flatteurs mais sans valeur :

- **PIAF** : le loader n'écrivait que les paragraphes des questions tirées. Avec `--limit 30`, le corpus contenait 6 paragraphes : trouver le bon parmi 6 est trivial (d'où un R@1 de 0,87).
- **LexML** : le corpus était fait de fiches de 600 caractères (titre + ementa) et chaque question recopiait le titre et l'ementa du document attendu. En plus, le fichier de vérité pointait vers `doc1.txt` / `doc2.txt`, absents du corpus.

Un benchmark sur lequel tout le monde a 100 % ne peut montrer ni un gain ni une régression.

## Règles communes

1. **Tout le corpus est indexé.** Le nombre de questions évaluées et la taille du corpus sont indépendants : on tire N questions, mais on cherche la réponse parmi *tous* les passages.
2. **Tirage figé.** Les questions sont triées par identifiant puis tirées avec une graine (`--seed`, 42 par défaut). Même graine = mêmes questions, quel que soit l'ordre des lignes à la source.
3. **Pertinence au niveau du passage.** Chaque cas porte des `expected_spans` : `{file_name, start, end, text}`, des positions dans le texte normalisé du document (le même texte que celui stocké en base). Un chunk est pertinent s'il **chevauche** le passage attendu. Conséquences :
   - la vérité terrain ne dépend pas de la stratégie de chunking : `traditional`, `slide` et `late` sont jugés sur le même passage ;
   - un chunk du bon document mais du mauvais endroit ne compte pas, ce qui compte pour les lois longues (une loi = des centaines de chunks).
   - Sans positions (store Neo4j), on vérifie que le texte attendu figure dans le chunk.
   - Les cas sans `expected_spans` gardent l'ancienne règle (bon fichier ou URN cité).
4. **Métriques par type.** Quand les cas portent un `question_type`, le rapport donne aussi Recall@k et MRR par type (`by_type` dans le rapport JSON et dans `experiment_run.config_json`).

## PIAF (français)

```bash
raglab bench download piaf --limit 500 --seed 42
```

- Corpus : tous les paragraphes du split `train` d'`etalab-ia/piaf`, soit 761 paragraphes (≈ 540 Ko de texte), un fichier par paragraphe, texte déjà normalisé.
- Questions : 500 tirées avec la graine. La réponse annotée (`answer_start`) est relocalisée dans le texte normalisé (les 500 l'ont été) : le passage attendu est la réponse elle-même.
- `--sample-corpus` restaure l'ancien comportement (corpus réduit aux paragraphes des questions tirées), utile seulement pour un test rapide.
- Licence : CC-BY-SA (Wikipédia). Les 500 questions sont figées dans `benchmarks/piaf/` (le corpus, lui, se régénère avec la commande).

## LexML texte intégral (portugais)

```bash
raglab lexml fulltext --from 1988 --to 2024 --per-year 7 --seed 42
raglab lexml questions --count 300 --seed 42
```

**Corpus.** Pour chaque année, la liste des lois fédérales vient de l'API Dados Abertos du Sénat (`legis.senado.leg.br/dadosabertos/legislacao/lista`). Les lois sont visitées dans un ordre aléatoire (graine) et on en garde 7 par année dont le texte fait entre 3 000 et 150 000 caractères : les lois d'une ligne (« dénomme tel viaduc ») n'ont rien à chercher, et quelques codes de 2 Mo écraseraient le reste. Le texte consolidé vient de planalto.gov.br ; les passages révoqués (texte barré) sont retirés, l'en-tête de page aussi, et chaque paragraphe tient sur une ligne. `manifest.json` liste chaque fichier avec son SHA-256 : deux runs comparent le même corpus si les manifestes sont identiques.

Run de référence (graine 42, 1988-2024) : **252 lois, 4,6 millions de caractères** (médiane 8 600 caractères par loi). En chemin, 383 lois ont été écartées car trop courtes, 6 car trop longues, et 532 n'ont pas de page Planalto au format attendu (anciennes conventions de nommage) ; ces dernières sont simplement remplacées par la loi suivante du tirage.

Le moteur de recherche LexML est derrière une vérification anti-robot : il n'est pas utilisé. La législation brésilienne est dans le domaine public (Lei 9.610/1998, art. 8º, IV).

**Questions.** Des passages d'environ 700 caractères sont tirés dans le corps des lois, à partir du premier article (l'en-tête, l'ementa et la formule de promulgation sont identiques d'une loi à l'autre), un par loi d'abord puis à tour de rôle. Les lois qui ouvrent des crédits budgétaires restent dans le corpus comme distracteurs, mais on n'y tire pas de passages : ce sont des tableaux de chiffres. Pour chaque passage, un modèle rédacteur reçoit l'ementa de la loi et écrit une question d'un des trois types :

| Type | Ce que la question contient | Ce qu'elle teste |
|---|---|---|
| `paraphrase` | les idées du passage avec d'autres mots, sans numéro d'article ni de loi | la recherche sémantique |
| `reference` | le numéro de l'article et de la loi (« art. 49 da Lei nº 8.078 ») | les identifiants exacts, que les embeddings brouillent |
| `entity` | un sigle ou un nom propre du passage (FGTS, INSS…) | les termes rares |

On demande à chaque fois le type le moins représenté, pour équilibrer le jeu. Un type que le modèle rate trop souvent n'est plus demandé, plutôt que de bloquer la génération.

**Modèle rédacteur.** Par défaut, Qwen3.6-35B-A3B (MoE, ~3 B paramètres actifs) servi par llama.cpp, en mode JSON contraint par grammaire, température 0. Un premier essai avec qwen2.5:7b a été abandonné : sur 30 questions relues, environ un tiers étaient vagues (« Qual lei é alterada por esta Lei? »), contenaient « neste trecho » malgré la consigne, ou ne citaient pas l'article demandé (187 rejets pour 147 questions gardées). `--backend ollama` reste disponible.

La commande gère le serveur elle-même : elle décharge les modèles Ollama (`keep_alive: 0`) pour libérer le GPU, lance `RAGLAB_LLAMACPP_START_COMMAND` si `/health` ne répond pas, puis `RAGLAB_LLAMACPP_STOP_COMMAND` à la fin, mais seulement si c'est elle qui l'a démarré (voir `.env.example`).

Le modèle doit aussi rendre une **réponse copiée mot pour mot** du passage. Une question est rejetée si :

- la citation est introuvable dans le passage (c'est ce filtre qui écarte les questions inventées) ;
- la réponse dépasse 40 mots, ou n'est que du remplissage (lignes de points) ou la formule de promulgation ;
- la question ne se comprend qu'à côté du passage (« neste trecho », « esta Lei », « em análise »…) : dans un corpus de 252 lois, elle n'a pas de réponse unique ;
- une `paraphrase` ou une `entity` cite un article ou une loi ;
- une `reference` ne cite pas à la fois l'article et le numéro de la loi.

Chaque cas enregistre `lexical_overlap` : la part des mots de la question (plus de 3 lettres) présents dans le passage. Les questions générées par un LLM reprennent souvent les mots du texte, ce qui favorise la recherche lexicale ; ce chiffre permet de le vérifier au lieu de le supposer.

**Relecture.** 40 questions ont été relues à la main. Les défauts trouvés (réponses sans contenu comme « (VETADO) » ou « Esta Lei entra em vigor… », renvois vagues comme « conforme o inciso VI ») sont devenus des règles automatiques, appliquées après coup par `raglab lexml review-questions` : 23 cas sur 300 sont marqués `review_status: "rejected"` avec leur `rejection_reason`. Ils restent dans le fichier pour l'audit, le benchmark les ignore. Résultat : **277 questions utilisables** (93 paraphrases, 97 références, 87 entités) sur 168 lois. Le jeu est figé dans `benchmarks/lexml_fulltext/`.

## Code de la consommation (français)

```bash
raglab legifrance fetch --code consommation
raglab legifrance questions --count 300 --seed 42 --output-dir benchmarks/legi_consommation
raglab legifrance review-questions --ground-truth benchmarks/legi_consommation/ground_truth.jsonl
```

**Corpus.** Le Code de la consommation avec tout son historique (1993 à octobre 2026), un document par version d'article : 5 998 versions de 3 391 articles, dont 2 106 en vigueur, 5,6 millions de caractères. Source : données LEGI de la DILA (Licence Ouverte 2.0) via le dépôt git du code publié par tricoteuses, figé sur un commit ; `benchmarks/legi_consommation/corpus_manifest.json` donne l'empreinte de chaque texte. Le choix de la source et le format sont détaillés dans [corpus-legi.md](../corpus-legi.md).

**Questions.** Même méthode que LexML, avec ces différences :

- les passages sont tirés dans les versions **en vigueur** des articles numérotés (L., R., D. ; pas les annexes, qui sont des formulaires), un par article d'abord ; un article plus court que 700 caractères est pris en entier s'il en fait au moins 200 ;
- le rédacteur reçoit la place de l'article dans le code (Partie > Livre > Titre…) au lieu de l'ementa ;
- une question `reference` doit citer l'article sous une forme que lit le résolveur de citations (« article L. 221-18 du code de la consommation ») ; une `paraphrase` ou une `entity` ne doit citer ni article ni numéro de loi, décret ou ordonnance ;
- les filtres de formulation sont en français : « cet article », « le présent code », « mentionné », « ci-dessus » rendent une question vague ; « (Abrogé) », « entrent en vigueur… » ou « par décret en Conseil d'État » seuls ne sont pas des réponses ;
- chaque cas porte une partie `split` tirée avec la graine, par type : un quart `dev` (qu'on peut regarder pendant la mise au point d'une méthode), trois quarts `heldout` (jamais regardés). Le rapport donne Recall@k et MRR par partie (`by_split`), pour vérifier qu'un gain tient sur les questions jamais vues, comme pour le résolveur de citations sur LexML ;
- `context` note l'article, le nombre de versions de même numéro et si la réponse figure aussi dans une autre version (`answer_in_other_version`) : retrouver une version ancienne compte comme un échec (mauvais fichier), et ce champ permet de mesurer ce piège à part.

La suite `legi_consommation` ne tourne que sur demande (`raglab bench all --suite legi_consommation`).

## Actes de l'UE (conformité)

```bash
raglab eurlex fetch
raglab eurlex questions --count 300 --seed 42 --output-dir benchmarks/eurlex_compliance
raglab eurlex review-questions --ground-truth benchmarks/eurlex_compliance/ground_truth.jsonl
```

**Corpus.** 15 actes (RGPD, AI Act, DORA, NIS 2, sept actes de niveau 2 de DORA, le règlement d'exécution de NIS 2, le règlement sur le groupe scientifique de l'AI Act, l'omnibus numérique sur l'IA, les clauses contractuelles types), en français, anglais et portugais, un document par considérant, article ou annexe, par langue et par version : 4 236 documents, 7,9 millions de caractères. Source : CELLAR (Office des publications, sans compte), versions consolidées figées ; `benchmarks/eurlex_compliance/corpus_manifest.json` donne l'empreinte de chaque texte et de chaque fichier téléchargé. Détails dans [corpus-eurlex.md](../corpus-eurlex.md).

**Questions.** Même méthode que LexML et le Code de la consommation, avec ces différences :

- les passages sont tirés dans les unités **en vigueur** (considérants, articles, annexes), une unité à la fois toutes langues confondues, dans une langue tirée avec la graine ;
- cinq types : `paraphrase`, `reference` (l'unité citée comme un juriste, lue par le résolveur), `entity`, `cross_reference` (la question cite l'unité A, la réponse est dans l'unité B que A cite ; pertinence sur B seule, la phrase de A dans `citing_spans`) et `cross_language` (question dans une autre langue que le passage) ;
- les filtres de formulation couvrent les trois langues (« this Article », « cet article », « este artigo », « mentioned », « ci-dessus ») ; la langue de la question est vérifiée ;
- `context` note l'unité, les langues, les fichiers de la même unité dans les autres langues, le nombre de versions et si la réponse figure aussi dans une version ancienne (`answer_in_other_version`) ; partie `split` tirée avec la graine (un quart `dev`, le reste `heldout`).

La pertinence reste au niveau du passage du fichier tiré : retrouver le même article dans une autre langue ne compte pas (les autres fichiers sont dans `context.same_unit_files`, pour une analyse à part). La suite `eurlex_compliance` ne tourne que sur demande (`raglab bench all --suite eurlex_compliance`).

## Changer de générateur

Par défaut, les réponses notées sont écrites par le générateur de production (Ollama, `qwen2.5:7b`) pendant la boucle de recherche. Pour mesurer un autre modèle sans changer la production :

```bash
raglab bench all --label gen-qwen36-v1 --generator-provider llamacpp --generator-profile qwen35b-moe
```

Avec un autre fournisseur qu'Ollama, la génération devient une passe à part : la recherche tourne d'abord sur toutes les questions, le cross-encoder est libéré, llama-server démarre avec le profil demandé, écrit les réponses (même prompt, mêmes 5 passages qu'en production), puis s'arrête avant que le juge démarre le sien. Les deux modèles ne sont jamais chargés ensemble. Le fichier de résultat note le générateur (`generator`) ; le juge reste Gemma 4, d'une autre famille.

## Limites connues

- Les questions LexML sont écrites par un modèle (Qwen3.6 MoE). Elles servent à évaluer le retrieval, pas les réponses : elles ne favorisent pas un générateur, mais elles héritent des tournures du rédacteur. Le juge RAGAS (phase 9.1b) sera un modèle d'une autre famille, Gemma 4, pour éviter qu'un modèle note ses propres réponses.
- Une seule réponse attendue par question : un autre passage qui répond aussi bien compte comme non pertinent. Recall et MRR sont donc des bornes basses.
- PIAF a été écrit par des annotateurs qui lisaient le paragraphe : beaucoup de questions reprennent ses mots. Il favorise la recherche lexicale par construction.
