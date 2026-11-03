# Juges RAGAS : choix et calibration

Les métriques de génération (faithfulness, answer relevancy, answer correctness) sont notées par un LLM, ce qu'on appelle un « LLM-as-judge ». Une note n'a de valeur que si le juge est fiable. Ce document explique quel juge raglab utilise, pourquoi, et comment on l'a vérifié.

## Le juge retenu : Gemma 4 26B-A4B, servi par llama.cpp

Les réponses sont générées par qwen2.5:7b (Ollama). Si qwen2.5 les notait lui-même, il jugerait ses propres réponses : un modèle tend à préférer son propre style, et un 7B repère mal une affirmation plausible mais absente du contexte. Le juge est donc un modèle **d'une autre famille** (Google), plus gros (MoE, ~3,8 B paramètres actifs) et dont la sortie JSON est contrainte par grammaire (llama-server `response_format`), ce qui supprime les notes perdues sur du JSON invalide.

## Notation en deux passes

Les 8 Go de VRAM ne tiennent pas qwen2.5:7b et Gemma en même temps. Le benchmark :

1. fait tout le retrieval et génère les réponses des N premières questions avec qwen2.5 (Ollama) ;
2. décharge le modèle Ollama (`keep_alive: 0`), démarre llama-server avec le profil `gemma4-moe` (via `RAGLAB_LLAMACPP_START_COMMAND`) ;
3. note toutes les réponses, puis arrête le serveur s'il l'a démarré.

Rien à lancer à la main. Le rapport indique quel juge a noté (`judge: "llamacpp:gemma4-26b-a4b"`). `--judge-backend ollama` reste disponible, par exemple sur une machine sans llama.cpp.

## Les trois juges

| Métrique | Question posée au juge | Voit |
|---|---|---|
| `faithfulness` | Chaque affirmation de la réponse est-elle appuyée par le contexte récupéré ? | question, contexte, réponse |
| `answer_relevancy` | La réponse traite-t-elle la question posée, sans dériver ? | question, réponse |
| `answer_correctness` | La réponse dit-elle la même chose que la réponse attendue ? | question, réponse attendue, réponse |

Grille commune : 1,0 = pleinement, 0,5 = à moitié, 0,0 = pas du tout. `answer_relevancy` est ici une variante « LLM-as-judge », pas la méthode de RAGAS (qui régénère des questions depuis la réponse et compare leurs embeddings).

## Calibration

`raglab experiment calibrate-judges` fabrique des réponses dont on connaît le bon verdict, à partir de 30 paragraphes PIAF (contexte = le paragraphe, vérité = la réponse annotée), et les fait noter par chaque juge :

| Variante | Réponse | Verdict attendu |
|---|---|---|
| `faithful` | la réponse annotée | fidèle |
| `fabricated` | la réponse d'une autre question, d'un autre paragraphe | infidèle |
| `embellished` | la bonne réponse + une affirmation absente du contexte (« confirmé par le Conseil d'État en 2019 ») | infidèle (le cas difficile) |
| `on_topic` | la réponse annotée | pertinente |
| `off_topic` | la réponse à une autre question sur le même paragraphe | non pertinente |

Une note compte comme « positive » à partir de 0,75, donc seulement une note pleine. Premier essai, avec un seuil à 0,5 : les deux juges semblaient incapables de voir les ajouts inventés (13 % et 33 %). En réalité, ils notaient presque tous ces réponses 0,5, ce qui est exactement la bonne note selon leur grille (« la moitié des affirmations est ancrée »). C'était le seuil qui était faux.

### Résultats (150 réponses, graine 7)

| Taux de bons verdicts | qwen2.5:7b (Ollama) | Gemma 4 26B-A4B (llama.cpp) |
|---|---|---|
| Réponse fidèle reconnue fidèle | 0,83 | **0,93** |
| Réponse inventée repérée | 1,00 | 1,00 |
| Ajout inventé repéré | 1,00 | 1,00 |
| **Faithfulness** | 0,944 | **0,978** |
| Bonne réponse jugée pertinente | 0,40 | **0,97** |
| Réponse à une autre question repérée | **0,93** | 0,70 |
| **Answer relevancy** | 0,667 | **0,833** |

Les notes brutes sont dans [`benchmarks/judge_calibration.json`](../../benchmarks/judge_calibration.json).

**Deuxième correction : le juge lisait un contexte tronqué.** Une première version du juge de fidélité ne gardait que les 600 premiers caractères de chaque passage (un chunk en fait jusqu'à 900, un paragraphe PIAF souvent plus). Il pouvait donc juger « inventée » une affirmation présente dans la partie coupée. Mesuré avant correction : faithfulness 0,933 (qwen2.5) et 0,944 (Gemma), les erreurs portant surtout sur des réponses pourtant fidèles. Avec les passages complets : 0,944 et 0,978.

**Lecture**

- Sur la fidélité, les deux juges repèrent toutes les réponses inventées ou enjolivées ; Gemma reconnaît mieux les réponses fidèles (0,93 contre 0,83), donc il accuse moins souvent à tort. Il évite surtout que le générateur se note lui-même.
- Sur la pertinence, qwen2.5 pénalise à tort plus de la moitié des bonnes réponses courtes (« 100 000. » à « Combien de personnes… ? » reçoit 0,5 ou 0).
- Gemma se laisse tromper 3 fois sur 10 par une réponse du bon format à une autre question (un nombre pour un « combien »). C'est en partie dû au protocole : le juge de pertinence ne voit pas le contexte, il ne peut donc pas savoir que « 20 000 » répond à une autre question.

## Limites

- 30 paragraphes, une graine : les écarts de quelques points ne sont pas significatifs.
- Calibration en français uniquement (PIAF). Le comportement sur le portugais juridique n'est pas mesuré.
- Les variantes sont fabriquées : de vraies hallucinations sont plus subtiles. La calibration donne une borne optimiste de la fiabilité des juges.
