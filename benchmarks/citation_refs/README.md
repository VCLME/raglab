# Jeu de références citées (`citation_refs`, v1)

Ce jeu figé vérifie ce que le routeur fait d'une question qui cite un texte juridique. Il répond au lot 1 de l'audit technique du 4 novembre 2026 (commit audité `8711e3c`). Le constat de l'audit : la présence d'un acte (RGPD, DORA) suffisait à exempter du refus une question sur un article qui n'existe pas.

## Contenu

`cases.jsonl` : 45 questions, une ligne par cas. Chaque cas porte le corpus interrogé, la catégorie, le statut attendu, l'unité attendue (numéro lu), la version attendue et la règle attendue du routeur.

| Catégorie | Cas | Exemple |
|---|---|---|
| valid | 15 | « O que diz o art. 1.723 da Lei nº 10.406? », « What does Annex IV of the AI Act list? » |
| nonexistent | 11 | « Que dit l'article 412 du RGPD ? », « O que diz o art. 999 da Lei nº 13.445? » |
| malformed | 7 | « artigo 31 lei 13445 … », « que dit l'art 32 du rgpd » |
| historical | 4 | « O que dizia o art. 194 da Lei nº 10.406? » (« Revogado »), « l'article L112-12 » (versions abrogées seules) |
| act_only | 3 | « Que prévoit le RGPD pour les sous-traitants ? » |
| unrecognized | 3 | « O que diz o art. 20 do Decreto 9.199? » (décret non lu) |
| act_not_indexed | 2 | « l'article 1240 du code civil » (code absent du corpus), loi inventée |

Corpus : `bench_eurlex_compliance`, `bench_legi_consommation_fr`, `bench_br_expat_pt`, `bench_lexml_pt`.

**Vérifications.** Chaque unité attendue a été vérifiée avant l'évaluation, dans le texte ou dans la base :
- unités inexistantes : nombre d'articles, de considérants et d'annexes par acte ;
- articles brésiliens : ligne « Art. N » du texte compilé ;
- articles abrogés : mention « (Revogado … ) » ou états Légifrance.

**Règle attendue :**
- `exempt` (jamais refusée) pour `found` et `act_only` ;
- `decline` (refus explicite) pour `unit_not_found` ;
- `normal` (intention puis score) pour `act_not_found` et pour une référence non reconnue.

**Deux cas ajoutés après la première évaluation** : `eu-malformed-04` et `eu-none-06` (« art 32 / art 999 du RGPD », abréviation sans point). Ils sont signalés dans `note`. La première évaluation a révélé que « art 999 du RGPD » était lu comme l'acte seul, donc exempté. Ces deux cas couvrent la correction ; ils ne sont pas aveugles.

## Mesure

Elle est déterministe, sans GPU : le lecteur de citations et la base seulement. Le même script note le code d'avant (`8711e3c`, contrôle au niveau de l'acte) et celui d'après :

```bash
PYTHONPATH=<arbre 8711e3c>/src python scripts/citation_refs_eval.py --out benchmarks/citation_refs/report-8711e3c.json
PYTHONPATH=src python scripts/citation_refs_eval.py --out benchmarks/citation_refs/report-v1.json
python scripts/citation_refs_eval.py --compare benchmarks/citation_refs/report-8711e3c.json benchmarks/citation_refs/report-v1.json
```

| | Avant (`8711e3c`) | Après (v1) | Gagnés / perdus | p (McNemar exact) |
|---|---|---|---|---|
| Règle du routeur correcte (sur 45) | 33 | **44** | +11 / −0 | 0,001 |
| Unité lue correctement (sur 45) | 38 | **44** | +6 / −0 | 0,031 |
| Statut correct (sur 45) | — | 44 | | |

Par catégorie, règle correcte avant → après :
- inexistantes : 0 → 11 sur 11 ;
- valides : 15 → 15 ;
- historiques : 4 → 4 ;
- acte seul : 3 → 3 ;
- non reconnues : 3 → 3 ;
- acte non indexé : 2 → 2 ;
- mal formées : 6 → 6 sur 7.

Les versions historiques sont bien signalées (`version: historical`) pour les 4 cas.

**Le cas raté** (`eu-malformed-03`, « que dit l'art 32 du rgpd ») : les sigles d'actes européens sont lus en respectant la casse. Ce choix est voulu dans `raglab.eurlex.references`, qui sert aussi à construire le graphe. La question reste non reconnue et suit la règle normale, avant comme après : aucune exemption accordée, et aucun refus explicite.

### Non-régression sur les jeux figés existants

Toutes les questions des jeux figés qui contiennent une citation reconnue ont été passées à la même règle, avant et après. Il y en a 253, dans `lexml_fulltext`, `lexml_references`, `legi_consommation`, `legi_versions`, `eurlex_compliance`, `br_expat` et `lexml_fr`. Ce sont des questions dont la réponse est dans le corpus, donc aucune ne doit être refusée.

- **Après correction, aucune question ne change de règle** : 249 exemptées, 4 en règle normale, 0 refusée.
- **La première version en refusait 3 à tort** (`lexml-0062`, `lexml-0257`, `lexml-ref-0027`). Le découpage tombait entre « Art. » et le numéro : un morceau finit par « Art. », le suivant commence par « 5º A lei… », et l'article n'était pas repéré. Il l'est maintenant (`_split_article_start`). Ces trois questions étaient déjà exemptées avant, mais sans que leur article soit épinglé.

Cette absence de changement vaut pour la règle déterministe sur ces 253 questions. La conséquence sur le passage retrouvé (articles désormais épinglés) se mesure à part, sur GPU : voir `docs/citations.md`.

## Limites

- 45 cas écrits à la main : ils couvrent les formes connues, pas toutes les écritures possibles.
- Une unité « introuvable » dépend du lecteur. Pour une loi brésilienne, l'article est repéré dans le texte (« Art. N ») : une mise en forme inattendue donnerait un faux `unit_not_found`, donc un refus à tort sous routeur. La non-régression ci-dessus en a trouvé 3 (corrigés) ; il peut en rester sur d'autres textes.
- Une référence valide ne garantit pas que la question entière trouve sa réponse : le statut ne dit rien du reste de la question.
- Les décrets, la CLT et les sigles en minuscules ne sont pas reconnus. Ils suivent la règle normale.
