# Corpus juridique français : le Code de la consommation

La thèse de raglab (voir [audit-2026-11.md](audit-2026-11.md)) est que le RAG classique échoue sur les documents structurés, référencés et versionnés, de quatre façons : identifiants, renvois, versions, hors périmètre. Elle était mesurée en portugais sur LexML (252 lois fédérales brésiliennes). Ce corpus la rend mesurable en français, sur du droit qui parle aux clients français : le **Code de la consommation**, pendant du Código de Defesa do Consumidor (Lei 8.078/1990) déjà présent dans LexML.

## La source

| Source | Taille à télécharger | Historique des versions | Provenance | Verdict |
|---|---|---|---|---|
| Données ouvertes LEGI de la DILA (`echanges.dila.gouv.fr/OPENDATA/LEGI/`) | 1,1 Go (archive globale du 13 juillet 2025) + ~480 incréments quotidiens (0,8 à 9 Mo chacun) | complet (XML : `VERSIONS`, `LIENS`) | officielle, Licence Ouverte 2.0 | la référence, mais 1 Go pour quelques Mo utiles |
| tricoteuses, miroir git du dump LEGI (`git.tricoteuses.fr/dila/legi`) | dépôt de 6 Go ; il faudrait des milliers de requêtes fichier par fichier | complet (XML d'origine) | DILA, recopiée | trop de requêtes sur une infrastructure bénévole |
| **tricoteuses, un dépôt git par code** (`git.tricoteuses.fr/codes/code_de_la_consommation`) | **clone de 4,5 Mo** | **complet : un commit par texte modificatif, de 1993 à aujourd'hui** | DILA (Licence Ouverte 2.0), mise en Markdown par tricoteuses | **retenue** |
| Hugging Face `louisbrulenaudet/code-consommation` | 1,8 Mo (parquet) | non : versions en vigueur seulement, mise à jour du 20 septembre 2025 | reconditionnement tiers | pas de mode d'échec « versions » |
| SocialGouv `legi-data` | paquet npm | non | expérimental, « usage interne » | écartée |
| API Légifrance (PISTE) | — | oui | officielle | demande un compte OAuth |

Le dépôt tricoteuses retenu contient un fichier Markdown par article, dont l'en-tête reprend les métadonnées LEGI (identifiant `LEGIARTI`, état, dates de début et de fin), et un commit par texte modificatif, daté de son entrée en vigueur et nommé d'après lui (avec son identifiant `JORFTEXT`). Les versions anciennes gardent leur état final (« MODIFIE », date de fin). Tout l'historique du code tient dans un clone de 4,5 Mo.

La conversion n'est pas officielle (le projet prévient qu'elle « peut contenir des erreurs ») ; chaque version porte donc son identifiant LEGI et son lien Légifrance (`source_url`), ce qui permet de la vérifier. Le corpus est figé sur le commit `77f0381` (état du code au 10 octobre 2026, dernier texte : décret n° 2026-935 du 7 octobre 2026).

## La collecte

```bash
raglab legifrance fetch --code consommation
```

La commande clone le dépôt **sans le déployer** (`git clone --bare`) : une fois extraits, certains chemins d'articles dépassent la limite de 260 caractères de Windows. Elle lit ensuite l'historique jusqu'au commit figé (`--commit` pour un autre), puis écrit dans `data/legifrance/consommation/` :

- `corpus/` : un `.txt` et un `.json` par **version d'article** ;
- `manifest.json` : l'empreinte SHA-256 de chaque texte et le commit source (copie figée : [`benchmarks/legi_consommation/corpus_manifest.json`](../benchmarks/legi_consommation/corpus_manifest.json)) ;
- `stats.json` : les chiffres ci-dessous.

Deux collectes indépendantes donnent un manifeste identique. Durée : environ une minute.

### Un document par version d'article

- **L'article est l'unité que cite un juriste.** « Article L. 221-18 du code de la consommation » désigne un document, retrouvé par ses métadonnées, sans chercher où l'article commence dans un texte plus long (ce que le résolveur doit faire sur les lois brésiliennes).
- **Chaque chunk hérite de l'état de sa version** (en vigueur, modifiée, abrogée) sans analyse de texte. C'est ce qu'il faut au mode d'échec « versions » : filtrer ou signaler un chunk abrogé est un filtre sur les métadonnées (`etat`).
- **Les stratégies de découpage ne changent pas** : chaque article est un texte comme un autre ; `traditional`, `slide` et `late` restent comparables.

Le texte d'une version est ce que dit l'article : une ligne d'en-tête (« Code de la consommation — Article L221-18 »), puis un paragraphe par ligne, tableaux compris (cellules séparées par « | »). Il ne porte **aucun bandeau de version** : l'état est dans les métadonnées, comme dans une base documentaire réelle, et c'est au pipeline de s'en servir. La note (« Nota ») est aussi dans les métadonnées.

| Métadonnée | Exemple |
|---|---|
| `code`, `code_title`, `code_id` | `consommation`, « Code de la consommation », `LEGITEXT000006069565` |
| `article_number`, `article_label` | `L221-18` (forme normalisée, celle que lit le résolveur) |
| `legi_id`, `source_url` | `LEGIARTI000032226842`, lien Légifrance de la version |
| `etat`, `date_debut`, `date_fin` | `VIGUEUR`, `2016-07-01`, `null` (pas de fin) |
| `version`, `version_count`, `versions` | rang de la version, nombre de versions, liste des versions de l'article |
| `amended_by`, `ended_by` | texte qui a créé la version, texte qui l'a modifiée ou abrogée (titre, `JORFTEXT`, nature, date) |
| `partie`, `path`, `section_id` | `partie_legislative_nouvelle`, Partie > Livre > Titre > Chapitre > Section, `LEGISCTA…` |
| `references`, `external_references` | articles du même code cités par le texte ; articles d'autres codes (`{"article", "code"}`) |
| `nota`, `source_commit`, `language`, `tags` | |

## Les chiffres

| | |
|---|---|
| Documents (versions d'articles) | **5 998** |
| Articles distincts (numéros) | 3 391 |
| Articles en vigueur | **2 106** (1 292 L, 619 R, 174 D, 21 annexes et article liminaire) |
| Articles qui ne sont plus en vigueur | **1 285** |
| Versions par état | 2 239 modifiées, 1 928 en vigueur, 1 586 abrogées, 178 abrogées à date différée, 66 transférées, 1 annulée |
| Articles réécrits au moins une fois | **1 352** ; versions par article : médiane 1, moyenne 1,77, maximum 23 (L. 141-1) |
| Textes modificatifs | 573 |
| Taille | 5,6 millions de caractères (médiane 584 par version), contre 4,6 millions pour LexML |

## Ce que chaque mode d'échec y trouve

**1. Identifiants.** 2 085 articles en vigueur ont un numéro de la forme L. 221-18, R. 212-1, D. 312-8. Ces numéros se ressemblent tous, et les embeddings distinguent mal les identifiants (sur LexML, 9 % de bonnes réponses dans le top 5 sans le résolveur de citations, 72 % avec) : c'est son terrain.

**2. Renvois.** 1 212 articles en vigueur citent un autre article : **3 593 renvois internes**, dont 3 543 vers un article en vigueur, 28 vers un article qui ne l'est plus et 22 vers un numéro inconnu du code ; et 432 renvois vers d'autres codes (santé publique 81, monétaire et financier 61, rural 48, énergie 47…). Exemple : l'article L. 221-20 prolonge le délai « lorsque les informations […] n'ont pas été fournies […] dans les conditions prévues au 7° de l'article L. 221-5 » : la réponse est dans l'article cité. Les renvois sont dans les métadonnées (`references`), prêts pour le graphe des citations (9.9).

**3. Versions.** C'est là que ce corpus apporte le plus, car il contient l'historique complet :

- 1 352 articles ont été réécrits ; 826 des 2 106 articles en vigueur partagent leur numéro avec au moins une autre version du corpus (ancienne rédaction, souvent presque identique, ou ancien article de même numéro). Exemple : l'ancienne version de L. 221-20 renvoyait au « 2° de l'article L. 221-5 », la version de 2022 au « 7° » ;
- la recodification de 2016 (ordonnance n° 2016-301, décret n° 2016-884) a abrogé l'ancien code et **réutilisé 321 numéros pour d'autres règles**. L'ancien article L. 121-21 donnait au consommateur quatorze jours pour se rétracter (règle devenue l'article L. 221-18) ; l'actuel L. 121-21 interdit certains frais de recouvrement. Une question sur « le délai de rétractation de l'article L. 121-21 » est un piège parfait : un RAG classique répond avec un texte abrogé depuis 2016 ;
- 92 versions ont un texte identique à la précédente (seule la note ou la place dans le code a changé).

**4. Hors périmètre.** Le corpus ne contient qu'un code : les questions sur le code civil, le code du travail ou la jurisprudence n'y ont pas de réponse. Le résolveur reconnaît ces codes (« l'article 1240 du code civil ») et, ne trouvant pas l'article, laisse la recherche inchangée.

## Le résolveur de citations, profil français

`src/raglab/retrieval/citations.py` lit désormais aussi les citations d'articles de codes français (voir [citations.md](citations.md#profil-français-codes)) :

| Question | Citation lue |
|---|---|
| « Que prévoit l'article L. 221-18 du Code de la consommation ? » | art. L. 221-18, Code de la consommation |
| « Que dit l'art. R. 212-1 ? » | art. R. 212-1, code non précisé |
| « Que dispose l'article 1240 du code civil ? » | art. 1240, Code civil |
| « Que dit l'article 4 de la loi n° 89-462 ? » | rien : un numéro sans lettre n'est un article de code que si un code est nommé juste après |

L'article est retrouvé par ses métadonnées (`article_number`, `code`) dans le corpus interrogé : la version en vigueur, sinon la plus récente. Ses chunks sont épinglés en tête, et la recherche est restreinte au code cité, comme elle l'est à la loi citée sur LexML. Les citations brésiliennes sont lues en premier, inchangées.

## Le jeu de questions (à générer)

Le générateur suit le protocole LexML ([protocole.md](benchmarks/protocole.md#code-de-la-consommation-français)) : passages tirés dans les articles **en vigueur** (un par article d'abord), questions `scenario` (le type principal : une situation concrète, sans numéro d'article, sans nom de code ni formulation recopiée), `paraphrase`, `reference` et `entity` écrites par Qwen3.6-35B-A3B via llama.cpp, réponse copiée mot pour mot et retrouvée dans le texte, filtres en français, relecture, partie `dev` / `heldout` tirée avec la graine. Chaque cas note dans `context` le nombre de versions de son article et si la réponse figure aussi dans une version ancienne (`answer_in_other_version`) : on pourra mesurer à part le piège des versions.

```bash
raglab legifrance fetch --code consommation
raglab legifrance questions --count 300 --seed 42 --output-dir benchmarks/legi_consommation
raglab legifrance review-questions --ground-truth benchmarks/legi_consommation/ground_truth.jsonl
raglab bench all --suite legi_consommation --label legi-baseline-v1 --retrieval-mode dense --no-rerank --no-citations --versions all
raglab bench all --suite legi_consommation --label legi-full-v1
```

La suite `legi_consommation` (corpus `bench_legi_consommation_fr`) n'est lancée que si on la demande (`--suite`) : `raglab bench all` seul mesure toujours PIAF et LexML.

## Limites connues

- **Conversion tierce.** Le Markdown de tricoteuses n'est pas la source officielle ; les liens explicites du XML LEGI (`CITATION`, `MODIFIE_PAR`) n'y sont pas, d'où les renvois lus par des règles. Passer au dump officiel ne changerait que la collecte : le format du corpus resterait le même.
- **Renvois par règles.** Seuls les numéros avec une lettre (L., R., D.) sont lus dans les textes ; « l'article 4 de la loi du 6 juillet 1989 » ne l'est pas. Un renvoi « du même code » reprend le dernier code nommé.
- **Hiérarchie.** Les titres de Partie, Livre, Titre… sont ceux du jour où la version est entrée en vigueur.
- **Dates LEGI.** 21 versions ont une date de fin antérieure à leur date de début dans les données d'origine ; elles sont gardées telles quelles.
- **Numéros réutilisés.** Le résolveur choisit la version en vigueur, ou, avec l'option `versions` (9.10), celle de la date que demande la question : « l'article L. 121-21 dans sa rédaction de 2014 » est résolu vers la version de 2014. Voir [versions.md](versions.md).
