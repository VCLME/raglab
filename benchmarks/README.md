# Jeux d'évaluation figés

Ces fichiers sont la référence des mesures de la phase 9 : toutes les comparaisons avant / après sont faites sur ces questions-là. On ne les régénère pas entre deux mesures. Le protocole est décrit dans [docs/benchmarks/protocole.md](../docs/benchmarks/protocole.md).

| Dossier | Langue | Questions utilisables | Corpus (non versionné) | Licence |
|---|---|---|---|---|
| `piaf/` | français | 500 | 761 paragraphes de Wikipédia, `raglab bench download piaf --limit 500 --seed 42` | CC-BY-SA 3.0 (Etalab, d'après Wikipédia) |
| `lexml_fulltext/` | portugais | 277 sur 300 (23 marquées `rejected`) | 252 lois fédérales, `raglab lexml fulltext` ; empreintes dans `corpus_manifest.json` | domaine public (Lei 9.610/1998, art. 8º, IV) |
| `lexml_references/` (à générer) | portugais | environ 100 (`dev` 30 %, `heldout` 70 %) : l'article A renvoie à l'article B, la réponse est dans B ; moitié `via_topic`, 30 % `scenario` (situation concrète, ni loi ni article nommés), 20 % `via_article` | le corpus LexML ci-dessus ; `raglab lexml reference-questions` | domaine public |
| `legi_consommation/` | français | à générer (`raglab legifrance questions`) | Code de la consommation avec son historique : 5 998 versions de 3 391 articles, `raglab legifrance fetch` ; empreintes dans `corpus_manifest.json` | Licence Ouverte 2.0 (DILA, via tricoteuses) |
| `abstention/` | fr + pt | 80 questions sans réponse dans les corpus (phase 9.4) | — | rédigées pour raglab |

Chaque ligne de `ground_truth.jsonl` porte `expected_spans` (fichier + positions de la réponse dans le texte normalisé) : la pertinence est jugée au niveau du passage, quelle que soit la stratégie de chunking.

**LexML.** Les questions ont été écrites par Qwen3.6-35B-A3B (llama.cpp), puis filtrées automatiquement (citation retrouvée dans le texte, formulations vagues, réponses sans contenu). 40 questions ont été relues à la main ; les défauts trouvés ont été transformés en règles (`raglab lexml review-questions`), qui ont marqué 23 cas `rejected` avec leur `rejection_reason`. Ces cas restent dans le fichier pour l'audit et sont ignorés par le benchmark.

**Vérifier le corpus LexML.** Une collecte faite plus tard peut différer, car Planalto met ses textes consolidés à jour. Comparez les `sha256` de `corpus_manifest.json` avec ceux de `data/lexml/fulltext/manifest.json` : si un texte diffère, ses spans peuvent ne plus tomber au bon endroit.

**Code de la consommation.** Le corpus est figé sur un commit du dépôt git du code publié par tricoteuses (données LEGI de la DILA) : deux collectes donnent les mêmes empreintes. Voir [docs/corpus-legi.md](../docs/corpus-legi.md).

**Abstention (phase 9.4).** `abstention/questions.jsonl` contient des questions auxquelles les corpus ne répondent pas. Elles servent à mesurer si le système sait dire « je ne trouve pas cela dans les documents » au lieu d'inventer :

- `out_of_scope` (27) : demandes personnelles, internes à une entreprise, en temps réel, tâches (code, calcul, rédaction) ou culture générale sans rapport ;
- `near_miss` (23) : les plus difficiles, proches des sujets des corpus mais sans réponse dedans. Par exemple, « Ballon d'or 2023 » quand PIAF parle de l'Inter Milan, une loi fédérale inexistante, une loi d'État ou municipale, une loi étrangère, la jurisprudence. Les termes clés ont été cherchés dans les deux corpus pour vérifier l'absence de réponse ;
- `conversational` (30) : salutations, remerciements, questions sur l'assistant, relances, qui doivent recevoir une réponse conversationnelle sans recherche documentaire.

Pour la précision et le rappel de l'abstention, les questions des jeux PIAF et LexML servent d'exemples positifs (le système doit répondre).
