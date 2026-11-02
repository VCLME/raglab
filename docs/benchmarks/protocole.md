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
- Questions : 500 tirées avec la graine ; les 500 réponses ont été relocalisées dans le texte normalisé. La réponse annotée (`answer_start`) est relocalisée dans le texte normalisé : le passage attendu est la réponse elle-même.
- `--sample-corpus` restaure l'ancien comportement (corpus réduit aux paragraphes des questions tirées), utile seulement pour un test rapide.
- Licence : CC-BY-SA (Wikipédia). Le jeu dérivé n'est pas versionné dans le dépôt ; la commande le régénère.

## LexML texte intégral (portugais)

```bash
raglab lexml fulltext --from 1988 --to 2024 --per-year 7 --seed 42
raglab lexml questions --count 300 --seed 42
```

**Corpus.** Pour chaque année, la liste des lois fédérales vient de l'API Dados Abertos du Sénat (`legis.senado.leg.br/dadosabertos/legislacao/lista`). Les lois sont visitées dans un ordre aléatoire (graine) et on en garde 7 par année dont le texte fait entre 3 000 et 150 000 caractères : les lois d'une ligne (« dénomme tel viaduc ») n'ont rien à chercher, et quelques codes de 2 Mo écraseraient le reste. Le texte consolidé vient de planalto.gov.br ; les passages révoqués (texte barré) sont retirés, l'en-tête de page aussi, et chaque paragraphe tient sur une ligne. `manifest.json` liste chaque fichier avec son SHA-256 : deux runs comparent le même corpus si les manifestes sont identiques.

Run de référence (graine 42, 1988-2024) : **252 lois, 4,6 millions de caractères** (médiane 8 600 caractères par loi). En chemin, 383 lois ont été écartées car trop courtes, 6 car trop longues, et 532 n'ont pas de page Planalto au format attendu (anciennes conventions de nommage) ; ces dernières sont simplement remplacées par la loi suivante du tirage.

Le moteur de recherche LexML est derrière une vérification anti-robot : il n'est pas utilisé. La législation brésilienne est dans le domaine public (Lei 9.610/1998, art. 8º, IV).

**Questions.** Des passages d'environ 700 caractères sont tirés dans le corps des lois (un par loi d'abord, puis à tour de rôle). Pour chacun, qwen2.5:7b (température 0) écrit une question d'un des trois types :

| Type | Ce que la question contient | Ce qu'elle teste |
|---|---|---|
| `paraphrase` | aucun mot du passage, ni numéro d'article ou de loi | la recherche sémantique |
| `reference` | le numéro de l'article et de la loi (« art. 49 da Lei nº 8.078 ») | les identifiants exacts, que les embeddings brouillent |
| `entity` | un sigle ou un nom propre du passage (FGTS, INSS…) | les termes rares |

Le modèle doit aussi rendre une **réponse copiée mot pour mot** du passage. Une question est rejetée si :

- la réponse n'est pas du JSON valide ;
- la citation est introuvable dans le passage (c'est ce filtre qui écarte les questions inventées) ;
- une `paraphrase` cite un article ou une loi.

Chaque cas enregistre `lexical_overlap` : la part des mots de la question (plus de 3 lettres) présents dans le passage. Les questions générées par un LLM reprennent souvent les mots du texte, ce qui favorise la recherche lexicale ; ce chiffre permet de le vérifier au lieu de le supposer.

**Relecture.** Les cas sont écrits avec `review_status: "generated"`. Un échantillon est relu à la main ; un cas passé à `"rejected"` est ignoré par le benchmark, un cas relu passe à `"reviewed"`.

## Limites connues

- Les questions LexML sont écrites et, avec RAGAS, jugées par le même modèle (qwen2.5:7b) que celui qui génère les réponses. Le biais est documenté, pas corrigé.
- Une seule réponse attendue par question : un autre passage qui répond aussi bien compte comme non pertinent. Recall et MRR sont donc des bornes basses.
- PIAF a été écrit par des annotateurs qui lisaient le paragraphe : beaucoup de questions reprennent ses mots. Il favorise la recherche lexicale par construction.
