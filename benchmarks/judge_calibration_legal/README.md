# Calibration du juge sur les pièges juridiques (préparée, non annotée)

Ce jeu répond au lot 3 de la contre-relecture des PR #83 à #85. Le juge Gemma a donné 1,0 en fidélité et 1,0 en exactitude à des réponses qui ratent le piège Q29 de Brazil expat. Ces réponses citent la règle de réciprocité, mais ne disent pas que la liste des pays manque, et certaines commencent par « Oui ». La calibration existante (`benchmarks/judge_calibration.json`) ne teste ni ce cas, ni `answer_correctness`.

## Contenu

`cases.jsonl` contient 42 réponses enregistrées, aucune régénérée :
- les 38 réponses du run `brexpat-qt-v1` (traduction de la question, rédacteur Qwen3.6) ;
- les deux pièges, Q29 et Q30, des runs `brexpat-full-v1` et `brexpat-naive-v1`.

Chaque cas porte :
- la question, la réponse attendue, et le comportement attendu pour les pièges (`cite_and_flag_missing`, `abstain`) ;
- le contexte **tel que présenté** au rédacteur, reconstruit avec l'horloge du run (4 novembre 2026) ;
- les verdicts du **modèle** (`model_verdicts` : juge, protocole, scores et raisons enregistrés) ;
- des champs **humains vides** : `human_verdict`, `human_labels`, `human_annotator`, `human_notes`. Aucun n'est rempli : ce jeu ne contient aucune annotation humaine, et aucune ne doit être écrite par un modèle.

Construit par `scripts/build_judge_calibration_legal.py` à partir des rapports détaillés.

## Annoter

Pour chaque cas, une personne qui lit le contexte et la réponse remplit les champs suivants.

`human_verdict` prend l'une de ces valeurs :
- `supported` : chaque affirmation de la réponse est portée par le contexte ;
- `partially_supported` : une partie seulement l'est ;
- `unsupported` : une affirmation centrale ne l'est pas ;
- `correct_refusal` : la réponse refuse, et le contexte ne permet pas de répondre ;
- `wrong_refusal` : la réponse refuse alors que le contexte permet de répondre.

`human_labels` contient zéro, une ou plusieurs de ces étiquettes :
- `missing_condition_not_flagged` : une règle conditionnelle est appliquée sans que la condition soit établie (Q29) ;
- `exception_ignored` : une exception du contexte est passée sous silence ;
- `conclusion_beyond_context` : la conclusion va au-delà de ce que disent les passages ;
- `wrong_provision` : la réponse s'appuie sur une disposition voisine ;
- `language_or_format` : un défaut de forme seulement.

Il faut aussi remplir `human_annotator` et, au besoin, `human_notes`.

## Mesurer, une fois annoté

`python scripts/score_judge_calibration_legal.py` compare les verdicts du modèle aux verdicts humains. Il calcule :
- l'accord sur « fidèle » (score 1,0 contre `supported`) ;
- l'accord sur l'exactitude ;
- les faux « fidèle » sur les cas étiquetés `missing_condition_not_flagged`, `exception_ignored` ou `conclusion_beyond_context`.

Le script refuse de calculer s'il n'y a aucun verdict humain. Les verdicts du juge en protocole v2 s'ajoutent avec `raglab bench rejudge` sur les mêmes rapports. Ils sont gardés à part des verdicts humains.
