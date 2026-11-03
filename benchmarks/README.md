# Jeux d'évaluation figés

Ces fichiers sont la référence des mesures de la phase 9 : toutes les comparaisons avant / après sont faites sur ces questions-là. On ne les régénère pas entre deux mesures. Le protocole est décrit dans [docs/benchmarks/protocole.md](../docs/benchmarks/protocole.md).

| Dossier | Langue | Questions utilisables | Corpus (non versionné) | Licence |
|---|---|---|---|---|
| `piaf/` | français | 500 | 761 paragraphes de Wikipédia, `raglab bench download piaf --limit 500 --seed 42` | CC-BY-SA 3.0 (Etalab, d'après Wikipédia) |
| `lexml_fulltext/` | portugais | 277 sur 300 (23 marquées `rejected`) | 252 lois fédérales, `raglab lexml fulltext` ; empreintes dans `corpus_manifest.json` | domaine public (Lei 9.610/1998, art. 8º, IV) |

Chaque ligne de `ground_truth.jsonl` porte `expected_spans` (fichier + positions de la réponse dans le texte normalisé) : la pertinence est jugée au niveau du passage, quelle que soit la stratégie de chunking.

**LexML.** Les questions ont été écrites par Qwen3.6-35B-A3B (llama.cpp), puis filtrées automatiquement (citation retrouvée dans le texte, formulations vagues, réponses sans contenu). 40 questions ont été relues à la main ; les défauts trouvés ont été transformés en règles (`raglab lexml review-questions`), qui ont marqué 23 cas `rejected` avec leur `rejection_reason`. Ces cas restent dans le fichier pour l'audit et sont ignorés par le benchmark.

**Vérifier le corpus LexML.** Une collecte faite plus tard peut différer, car Planalto met ses textes consolidés à jour. Comparez les `sha256` de `corpus_manifest.json` avec ceux de `data/lexml/fulltext/manifest.json` : si un texte diffère, ses spans peuvent ne plus tomber au bon endroit.
