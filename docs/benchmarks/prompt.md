# Le prompt de génération

Comment le prompt qui produit les réponses a été choisi, mesures à l'appui.

## Le problème

En lisant les réponses de `full-v1`, deux défauts sont apparus, invisibles dans les moyennes RAGAS :

- **des refus alors que la réponse est sous les yeux du modèle** : 24 questions PIAF sur 100 et 19 questions LexML (sur les 80 dont le bon passage est dans les 5 premiers) ont reçu la phrase « Je ne peux pas répondre… » ;
- **la mauvaise langue** : le prompt était écrit en français, et 29 réponses LexML sur 100 étaient en français pour des questions en portugais, parfois avec la phrase de refus déformée.

Ces refus comptent pour 0 dans la justesse (`answer_correctness`) : ils tiraient les scores vers le bas sans rien dire de la qualité de la recherche.

## La méthode

Pour comparer des prompts sans relancer 45 minutes de benchmark à chaque essai, la recherche n'est pas refaite : chaque variante génère sa réponse sur **exactement les mêmes 5 passages** que `full-v1` (100 premières questions de PIAF et de LexML, celles que le juge note), avec le même modèle (`qwen2.5:7b`, température 0,1). On compte d'abord les refus et la langue, puis le juge Gemma 4 note les variantes retenues, comme dans le benchmark.

| Variante | Idée |
|---|---|
| V0 (ancien prompt) | consignes en français, phrase de refus en français |
| V1 | consignes en français, phrase de refus en trois langues, « réponds en partie si tu peux » |
| V2 | consignes en anglais, phrase de refus dans la langue du corpus |
| V3 | prompt entièrement dans la langue de la question |
| **V4 (retenu)** | V3 + « recopie d'abord entre guillemets la phrase du contexte qui répond, puis réponds » |

## Les résultats

Refus et langue (100 questions par jeu ; entre parenthèses, les refus alors que le bon passage est dans le contexte) :

| Variante | Refus PIAF | Refus LexML | Réponses LexML dans la mauvaise langue |
|---|---|---|---|
| V0 | 24 (24) | 28 (19) | 29 |
| V1 | 58 (56) | 50 (35) | 40 |
| V2 | 42 (41) | 29 (19) | 0 |
| V3 | 24 (23) | 25 (17) | 0 |
| **V4** | **10 (9)** | **16 (9)** | **0** |

Juge Gemma 4 (V0 : notes de `full-v1`, mêmes passages) :

| | V0 | V3 | V4 |
|---|---|---|---|
| Fidélité PIAF / LexML | 0,907 / 0,895 | 0,952 / 0,865 | **0,943 / 0,930** |
| Pertinence PIAF / LexML | 0,930 / 0,865 | 0,885 / 0,895 | **0,930 / 0,910** |
| Justesse PIAF / LexML | 0,738 / 0,598 | 0,713 / 0,574 | **0,817** / 0,587 |

Ce qu'il faut en retenir :

- V4 divise les refus injustifiés par 2 à 3 et règle la langue, sans perdre en fidélité : elle monte sur les deux jeux ;
- la justesse progresse nettement sur PIAF (+0,08) mais pas sur LexML (0,598 → 0,587, dans le bruit) : sur les lois, la limite n'est plus le prompt mais le modèle ou la recherche ;
- V1 (« réponds en partie », trois phrases de refus) a doublé les refus : proposer plusieurs phrases de refus à un modèle 7B l'encourage à refuser.

## Ce qui est en production

`src/raglab/generation/prompts.py` : la langue est déduite de la question (mots fréquents ; 799 questions sur 800 des jeux figés bien classées), les consignes V4 sont écrites dans cette langue, la phrase de refus aussi (le français vient de `RAGLAB_GENERATION_NO_CONTEXT_ANSWER`). Le format du contexte (libellés « Fichier », « Extrait ») est resté celui qui a été mesuré. Une ligne a été ajoutée par rapport à V4 : citer chaque fait avec `[Rank X]` dans la réponse, dont l'interface a besoin pour ses pastilles de citation ; le benchmark complet `prompt-v4` vérifie l'ensemble. Quand les passages sont dans une autre langue que la question, l'étape de citation est remplacée (voir [plus bas](#question-et-corpus-de-langues-différentes-answer-lang-en-v1)).

Limites : mesure sur 100 questions par jeu, un seul modèle générateur ; la ligne ajoutée sur les citations n'était pas dans la variante mesurée.

## Mesure complète (`prompt-v4`) et générateur Qwen3.6 (`gen-qwen36-v1`)

Benchmark complet après la fusion (même recherche que `full-v1`, juge Gemma 4 sur 100 questions par jeu) :

| | `full-v1` (ancien prompt) | `prompt-v4` (prompt actuel, qwen2.5:7b) | `gen-qwen36-v1` (prompt actuel, Qwen3.6-35B-A3B) |
|---|---|---|---|
| Fidélité PIAF / LexML | 0,907 / 0,895 | 0,970 / 0,895 | 0,995 / 0,980 |
| Pertinence PIAF / LexML | 0,930 / 0,865 | 0,890 / 0,875 | 0,975 / 0,965 |
| Justesse PIAF / LexML | 0,738 / 0,598 | 0,763 / 0,550 | 0,935 / 0,710 |

- En mesure complète, le nouveau prompt confirme son gain sur PIAF (fidélité +0,06, justesse +0,03) ; sur LexML, la justesse recule de 0,05, ce qui n'apparaissait pas dans la mesure par variantes (0,587). Sur 100 questions, l'écart est proche du bruit ; la ligne ajoutée pour les citations `[Rank X]` est une différence possible.
- Le vrai saut vient du générateur : avec le même prompt et les mêmes passages, Qwen3.6 (MoE, 3 milliards de paramètres actifs, via llama.cpp) porte la justesse sur les lois de 0,55 à 0,71 et la fidélité à 0,98. La limite était le modèle, pas le prompt.
- Les latences de génération de ces deux runs ne sont pas comparables entre elles ni avec `full-v1` : la carte chauffait (89 °C) et ralentissait.

## Question et corpus de langues différentes (`answer-lang-en-v1`)

**Le défaut.** Avec une question en anglais sur un corpus portugais (LexML) ou français (Code de la consommation), la réponse commençait par la phrase source recopiée dans la langue du corpus, puis une phrase en anglais. C'est l'étape 1 de V4 (« recopie la phrase du contexte entre guillemets ») qui le provoque, et le défaut touchait aussi les questions françaises sur LexML. La détection de langue de la question n'est pas en cause : elle classe bien les 180 questions translingues ci-dessous.

**La correction.** `build_prompt_bundle` détecte la langue des passages (`raglab.routing.language`, majorité des passages). Si elle est la même que celle de la question, le prompt V4 est inchangé, octet pour octet : PIAF, LexML et le Code de la consommation en langue d'origine ne bougent pas. Sinon, trois modes ont été comparés (`cross_language`) :

| Mode | Étape 1 du prompt |
|---|---|
| `verbatim` (avant) | recopier la phrase source entre guillemets |
| `translate` | la traduire dans la langue de la question et donner la traduction entre guillemets |
| **`omit` (retenu)** | repérer les passages qui répondent (« le contexte est en portugais »), puis répondre en citant chaque fait avec `[Rank X]`, toute la réponse dans la langue de la question |

**La mesure.** Même méthode que plus haut : la recherche est faite une fois (hybride + re-ranking, top 5, corpus complets), chaque mode écrit sa réponse sur exactement les mêmes passages. 120 questions : 40 questions anglaises sur LexML et 40 sur le Code de la consommation (jeu figé `benchmarks/answer_lang_en/`, traductions de questions des jeux d'origine, graine 42), 40 questions françaises de `benchmarks/lexml_fr/` (graine 42). Deux rédacteurs : Qwen3.6-35B-A3B (llama.cpp, le rédacteur par défaut) et qwen2.5:7b (Ollama, le repli). Juge Gemma 4 (fidélité, justesse), intervalles à 95 % par bootstrap apparié. Commande : `python scripts/answer_language_eval.py`, résultats dans `benchmarks/results/answer-lang-en-v1.json`.

Réponses contenant au moins une phrase dans une autre langue que la question (sur 120) :

| | `verbatim` | `translate` | `omit` |
|---|---|---|---|
| Qwen3.6 | 101 | 79 | **2** |
| qwen2.5:7b | 58 | 35 | **5** |

Juge Gemma 4, 120 questions (un refus compte 0, comme dans `raglab bench`) :

| | Qwen3.6 `verbatim` | Qwen3.6 `omit` | qwen2.5 `verbatim` | qwen2.5 `omit` |
|---|---|---|---|---|
| Refus | 16 | 16 | 47 | 34 |
| Fidélité | 0,626 | 0,651 | 0,467 | 0,597 |
| Justesse | 0,434 | 0,412 | 0,304 | 0,296 |
| Écart `omit` − `verbatim`, fidélité | | +0,022 [−0,031 ; +0,075] | | **+0,130 [+0,045 ; +0,213]** |
| Écart `omit` − `verbatim`, justesse | | −0,022 [−0,064 ; +0,017] | | −0,008 [−0,058 ; +0,046] |

Ce qu'il faut en retenir :

- **Traduire la citation ne suffit pas** : les deux rédacteurs recopient quand même l'original dans 79 et 35 réponses. Le mot « citation » l'emporte sur la consigne de traduction.
- **Sans citation, la réponse reste dans la langue de la question** : 2 réponses sur 120 avec Qwen3.6, et ce sont des faux positifs du détecteur (une liste de codes « DAS-4, DAS-3 », le titre « O PRESIDENTE DA REPÚBLICA ») ; 5 avec qwen2.5:7b, qui recopie encore parfois un article portugais.
- **L'étape « citer d'abord » n'apportait rien en translingue** : avec Qwen3.6, fidélité et justesse ne bougent pas (intervalles qui contiennent 0) et les refus sont identiques ; avec qwen2.5, la fidélité monte de 0,13 et les refus baissent de 47 à 34. Le gain mesuré de V4 (moins de refus, plus de fidélité) reste acquis là où il a été mesuré, en langue d'origine, puisque ce prompt-là ne change pas.
- **La justesse est biaisée en faveur de `verbatim`** sur LexML : la réponse de référence est un extrait portugais ; une réponse qui recopie le portugais obtient 1, la même réponse correcte en français 0,5 (par exemple lexml-0079, lexml-0286). La légère baisse de justesse avec Qwen3.6 vient surtout de là.
- Une première version de `omit` (« note leur `[Rank X]` ») faisait écrire `[Rank X]` tel quel à qwen2.5 dans 10 réponses sur 120 ; la version retenue ne met `[Rank X]` qu'à l'étape 2, comme V4 : aucune occurrence.

Limites : 120 questions, un seul juge ; les passages ont été retrouvés avec llama.cpp arrêté, donc sans traduction de la requête pour le BM25 (`RAGLAB_QUERY_TRANSLATION`) : beaucoup de refus viennent de la recherche, pas du prompt, et le nombre de refus n'est comparable qu'entre colonnes. Les modes `translate` n'ont pas été notés par le juge : ils échouaient déjà sur la langue.
