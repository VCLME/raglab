# Plan d'expérimentation

## 1. Objectif

Comparer, de manière reproductible, plusieurs stratégies de chunking sur un même corpus documentaire local.

Les stratégies ciblées au démarrage :

- `traditional`
- `slide`
- `late`

## 2. Question expérimentale principale

Sur ce corpus local, quelle stratégie offre le meilleur compromis entre :

- qualité de récupération
- qualité des réponses générées
- coût de stockage
- latence

## 3. Baseline MVP

Configuration de référence pour démarrer :

- génération : `llama3.2:3b` via Ollama
- embeddings : `intfloat/multilingual-e5-small`
- distance : cosine
- top-k retrieval : 5

Paramètres baseline :

- `traditional`
  - chunk size : 900 caractères
  - overlap : 150 caractères
- `slide`
  - window size : 900 caractères
  - stride : 300 caractères
- `late`
  - focal chunk size : 700 caractères
  - contexte autour du chunk : 500 caractères à gauche et à droite

## 4. Variables à faire varier

### Variables de chunking

- stratégie
- taille cible du chunk
- overlap
- stride
- taille de contexte pour la variante late

### Variables de retrieval

- top-k
- distance metric
- prompt de synthèse

### Variables d’embeddings

Au MVP :

- un modèle de référence

Ensuite :

- comparaison de plusieurs providers ou modèles
- même protocole d’indexation et de requête

## 5. Métriques recommandées

### Retrieval

- `top_k`
- nombre de chunks produits
- nombre total de tokens/char stockés
- latence d’indexation
- latence de requête
- `retrieval_hit`
  - au moins un chunk récupéré contient un signal attendu

### Génération

- `answer_hit`
  - la réponse contient un élément attendu
- précision factuelle manuelle
- concision
- présence d’hallucinations

### Exploitabilité

- lisibilité des chunks restitués
- duplication d’information
- coût disque / base

## 6. Format de dataset recommandé

Fichier JSONL, une ligne par cas :

```json
{"id":"q1","question":"Quel est le délai de résiliation ?","expected_substrings":["résiliation","30 jours"]}
{"id":"q2","question":"Qui est responsable de la maintenance ?","expected_substrings":["maintenance","prestataire"]}
```

Champs utiles :

- `id`
- `question`
- `expected_substrings`
- `ground_truth_answer` plus tard si besoin

## 7. Protocole minimal

1. Ingestion du corpus.
2. Exécution d’un `index_run` par stratégie.
3. Lancement du runner d’expérimentation sur le même dataset.
4. Sauvegarde d’un rapport JSON.
5. Analyse comparative.

## 8. Ordre conseillé des expériences

### Vague 1

Valider que le pipeline fonctionne :

- `traditional`
- petit dataset de 10 questions

### Vague 2

Comparer `traditional` vs `slide` :

- même embeddings
- mêmes prompts
- même top-k

### Vague 3

Ajouter `late` :

- mesurer gain qualitatif
- mesurer surcoût de calcul

### Vague 4

Tester plusieurs embeddings :

- même protocole
- mêmes stratégies

## 9. Critères de décision pragmatiques

Choisir la stratégie par défaut du projet non pas sur une intuition, mais sur :

- stabilité des réponses
- rappel suffisant
- complexité opérationnelle acceptable
- coût raisonnable d’indexation

## 10. Décision attendue à la fin du MVP

Le MVP doit permettre de décider :

- quelle stratégie devient la baseline par défaut
- si le late chunking apporte une valeur mesurable sur ce corpus
- si un second modèle d’embeddings mérite d’entrer dans la prochaine phase
