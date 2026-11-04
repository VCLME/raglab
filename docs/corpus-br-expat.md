# Corpus « Brésil expat » : 30 questions réelles

Les autres jeux de raglab sont écrits par un modèle à partir des textes. Celui-ci part de l'autre bout : les **30 questions qu'un Français installé au Brésil s'est réellement posées** en créant sa société (au lucro presumido), compilées par son assistante : séjour et résidence, impôts de la société, INSS et retraite, fiscalité personnelle. Les questions sont en **français**, la loi en **portugais**, et les mots de tous les jours (« le pourcentage du chiffre d'affaires », « un virement vers mon compte en France ») ne sont pas ceux de la loi (« percentual », « receita bruta », « liquidações de operações de câmbio »).

Le jeu figé et la vérification de chaque référence sont dans [benchmarks/br_expat/README.md](../benchmarks/br_expat/README.md).

## Les textes

19 textes fédéraux, chacun dans sa version **compilée** (modifications intégrées) :

| Fichier | Texte | Thème | Caractères |
|---|---|---|---|
| `lei_13445_2017` | Lei 13.445/2017, Lei de Migração | immigration | 89 687 |
| `decreto_9199_2017` | Decreto 9.199/2017, règlement de la Lei de Migração | immigration | 214 958 |
| `lei_7115_1983` | Lei 7.115/1983, preuve par déclaration | immigration | 1 105 |
| `lei_10406_2002` | Código Civil (complet) | immigration | 631 687 |
| `lei_9249_1995` | Lei 9.249/1995, IRPJ et CSLL | société | 39 764 |
| `lei_9430_1996` | Lei 9.430/1996 | société | 103 609 |
| `lei_10833_2003` | Lei 10.833/2003, Cofins | société | 137 532 |
| `lei_10637_2002` | Lei 10.637/2002, PIS/Pasep | société | 69 069 |
| `lei_15270_2025` | Lei 15.270/2025, imposition minimale et dividendes | société | 23 437 |
| `lc_116_2003` | LC 116/2003, ISS | société | 45 665 |
| `lc_123_2006` | LC 123/2006, Simples Nacional | société | 226 517 |
| `in_rfb_1700_2017` | IN RFB 1.700/2017, IRPJ et CSLL | société | 433 328 |
| `in_srf_208_2002` | IN SRF 208/2002, résidence fiscale | fiscalité perso. | 52 284 |
| `lei_8212_1991` | Lei 8.212/1991, financement de la Sécurité sociale | INSS | 148 430 |
| `lei_10666_2003` | Lei 10.666/2003, contribuinte individual | INSS | 10 865 |
| `ec_103_2019` | Emenda Constitucional 103/2019, réforme des retraites | INSS | 79 823 |
| `decreto_8300_2014` | Decreto 8.300/2014, accord de sécurité sociale France-Brésil | INSS | 43 008 |
| `lei_14754_2023` | Lei 14.754/2023, placements à l'étranger | fiscalité perso. | 66 499 |
| `decreto_6306_2007` | Decreto 6.306/2007, règlement de l'IOF | fiscalité perso. | 107 339 |

Total : 2,5 millions de caractères, **3 578 chunks** (découpage `traditional`, multilingual-e5-small). Tous les textes demandés ont pu être collectés.

## La source

| Source | Textes | Verdict |
|---|---|---|
| **planalto.gov.br** (pages compilées, `ccivil_03/...`) | les 17 lois, LC, décrets et l'EC | **retenue**, avec le lecteur du corpus LexML (`extract_planalto_text`) : le texte barré (ancienne rédaction) est retiré, les marqueurs « (Redação dada pela …) » et « (Revogado) » restent, pour la brique versions |
| **API JSON de la Receita Federal** (`normasinternet2.receita.fazenda.gov.br/api/consulta-externa/ato/<id>/visao/vigente`), derrière le site Angular `normas.receita.fazenda.gov.br` | IN RFB 1.700/2017 (acte 81268), IN SRF 208/2002 (acte 15079) | **retenue** : la vue « vigente » liste chaque segment avec un drapeau `omitir` pour les rédactions remplacées ; on garde les autres. Pas de marqueurs de version dans ce texte |
| Page `sijut2consulta/link.action` | — | écartée : une coquille Angular sans texte |

Un piège de la Receita : l'identifiant 15081 est la **republication partielle de 2004** de l'IN SRF 208 (l'annexe II seule, 229 caractères) ; le texte complet est l'acte 15079.

Licence : législation fédérale brésilienne, domaine public (Lei 9.610/1998, art. 8º, IV).

## La collecte

```bash
raglab lexml br-expat                 # les 19 textes, une requête par seconde, environ 20 s
raglab lexml br-expat --only lei_9249_1995,in_rfb_1700_2017
```

Ou depuis l'Atelier : Corpus › **Sources officielles** › « Brésil expat » › « Collecter et ingérer » (`POST /api/sources/br_expat/fetch`), qui ingère dans `bench_br_expat_pt` sans indexer.

Sortie dans `data/lexml/br_expat/` (hors git) : `raw/` (pages et JSON téléchargés ; une collecte suivante les relit sans requête), `corpus/` (un `.txt` et un `.json` par texte), `manifest.json` (empreinte SHA-256 de chaque texte ; copie figée dans `benchmarks/br_expat/corpus_manifest.json`). Un texte qui ne répond pas est listé dans `missing` et la collecte continue.

Les métadonnées reprennent celles du corpus LexML (`number`, `year`, `signed_on`, `title`, `urn`, `source_url`, `language`) : le résolveur de citations trouve « art. 15 da Lei 9.249 » comme sur `bench_lexml_pt`. En plus : `kind` (`lei`, `lc`, `decreto`, `ec`, `in`), `theme`, `key`.

## Les mesures

```bash
raglab bench all --suite br_expat --label brexpat-naive-v1 --retrieval-mode dense --no-rerank --no-citations --versions all --ragas-limit 38 --generator-provider llamacpp --generator-profile qwen35b-moe-rag
raglab bench all --suite br_expat --label brexpat-full-v1 --ragas-limit 38 --generator-provider llamacpp --generator-profile qwen35b-moe-rag
python scripts/br_expat_report.py brexpat-naive-v1 brexpat-full-v1 --answers brexpat-full-v1
```

- **RAG naïf** : recherche dense seule (multilingual-e5-small), sans BM25, re-ranking, résolveur de citations ni filtre de versions.
- **Pipeline complet** (défaut) : hybride BM25 + dense (RRF), re-ranking bge-reranker-v2-m3, résolveur de citations, versions `in_force`.
- Dans les deux cas, réponses écrites par **Qwen3.6-35B-A3B** (llama.cpp, profil `qwen35b-moe-rag`) avec le prompt V4 (réponse dans la langue de la question, citation d'abord), à partir des 5 premiers passages, et notées par le juge habituel (Gemma 4 26B-A4B) : exactitude par rapport à la réponse attendue, fidélité au contexte.
- Mesures du 4 novembre 2026 sur une RTX 3070 Ti 8 Go, commit `f3fd1be`.
- La **traduction des questions pour le BM25** ([langues-croisees.md](langues-croisees.md)) est devenue le défaut pendant ces mesures (PR #75) : `brexpat-full-v1` est le pipeline complet **sans** elle, tel qu'il était au début du travail ; `brexpat-qt-v1` est le pipeline complet **avec** elle, le défaut actuel (section suivante).

### Recherche, niveau article

Un passage compte s'il tombe dans un article attendu. La Q30 (hors corpus) n'a pas de passage : elle est sortie des moyennes de recherche (`raglab bench` la compte comme un échec, d'où 0,447 et 0,526 en Recall@5 sur 38 questions dans `benchmarks/results/`).

| Thème | n | R@3 naïf | R@5 naïf | MRR naïf | R@3 complet | R@5 complet | MRR complet |
|---|---|---|---|---|---|---|---|
| Immigration (Q1-11) | 11 | 0,455 | 0,636 | 0,520 | 0,636 | 0,727 | 0,492 |
| Société et impôts (Q12-20) | 9 | 0,222 | 0,222 | 0,190 | 0,333 | 0,444 | 0,263 |
| INSS et fiscalité perso. (Q21-28) | 8 | 0,250 | 0,375 | 0,281 | 0,250 | 0,250 | 0,140 |
| Piège Q29 | 1 | 1,000 | 1,000 | 1,000 | 1,000 | 1,000 | 1,000 |
| Paraphrases familières | 8 | 0,500 | 0,500 | 0,417 | 0,375 | 0,625 | 0,425 |
| **Total (37 questions)** | 37 | **0,378** | **0,459** | **0,379** | **0,432** | **0,541** | **0,360** |

Comparaison appariée (`raglab bench compare brexpat-naive-v1 brexpat-full-v1`) : le pipeline complet trouve 5 questions de plus que le naïf et en perd 2 (Recall@5, McNemar p = 0,45, **non significatif** sur 37 questions) ; MRR −0,019, IC 95 % [−0,144 ; +0,099]. Le gain vient des impôts de société (+2, aucune perdue) ; l'INSS perd une question (Q22 passe du rang 4 au rang 7).

Au niveau de la **disposition** (le paragraphe ou l'inciso qui porte la réponse), le Recall@5 total est 0,432 (naïf) et 0,514 (complet) : sur ce jeu, trouver le bon article et trouver la bonne ligne vont presque toujours ensemble.

Latence de la recherche (p50, sans génération) : 47 ms en naïf, 379 ms avec le pipeline complet, dont 309 ms de re-ranking.

### Réponses

| Thème | Exactitude naïf | Exactitude complet | Fidélité naïf | Fidélité complet |
|---|---|---|---|---|
| Immigration | 0,727 | 0,727 | 1,000 | 0,955 |
| Société et impôts | 0,250 | 0,556 | 1,000 | 1,000 |
| INSS et fiscalité perso. | 0,438 | 0,125 | 0,875 | 0,938 |
| Pièges (Q29, Q30) | 1,000 | 1,000 | 1,000 | 1,000 |
| Paraphrases | 0,487 | 0,637 | 0,938 | 1,000 |
| **Total (38)** | **0,517** | **0,555** | **0,961** | **0,974** |

Sur 37 questions (sans Q30) : 13 réponses justes en naïf, 16 avec le pipeline complet ; 12 refus (« Je ne peux pas répondre de façon fiable avec le contexte actuellement récupéré. ») en naïf, 8 en complet ; 3 réponses fausses en naïf, 6 en complet. Le pipeline complet trouve plus, donc répond plus, et se trompe plus souvent quand il répond sans le bon passage.

### Les pièges

| | Naïf | Complet |
|---|---|---|
| **Q29** (un Français peut-il prolonger au-delà de 90 jours ?) | « **Oui**, un Français peut potentiellement prolonger […], mais cela n'est possible que si la France assure une réciprocité de traitement » ; cite le §2º | « la prorrogation est soumise à la condition de réciprocité » ; cite le §2º |
| **Q30** (taux du Livret A) | refus | refus |

**Q30 : réussie** dans les deux cas (le prompt V4 refuse sans contexte utile ; le routeur, derrière un drapeau, n'a pas été mesuré ici).

**Q29 : à moitié.** Les deux réponses citent l'art. 20 §2º (la réciprocité) et le pipeline complet ne répond plus « oui » ; mais **aucune ne dit que la liste des pays qui accordent la réciprocité manque dans les documents**, ce qui était la réponse attendue. Le juge leur donne 1,0 : il juge la condition de réciprocité, pas l'aveu de ce qui manque. Verdict relu à la main : piège non déjoué, réponse naïve la plus dangereuse (elle commence par « Oui »).

### Avec la traduction des questions (le défaut depuis la PR #75)

```bash
raglab bench all --suite br_expat --label brexpat-qt-v1 --query-translation --ragas-limit 38 --generator-provider llamacpp --generator-profile qwen35b-moe-rag
```

Le rédacteur traduit la question française en portugais pour le BM25 (la recherche dense et le re-ranking gardent la question d'origine). Même jeu, mêmes juges :

| Thème | R@5 complet | R@5 + traduction | MRR complet | MRR + traduction | Exactitude complet | Exactitude + traduction |
|---|---|---|---|---|---|---|
| Immigration | 0,727 | **0,909** | 0,492 | 0,598 | 0,727 | 0,891 |
| Société et impôts | 0,444 | **0,556** | 0,263 | 0,393 | 0,556 | 0,589 |
| INSS et fiscalité perso. | 0,250 | **0,500** | 0,140 | 0,289 | 0,125 | 0,125 |
| Piège Q29 | 1,000 | 1,000 | 1,000 | 1,000 | | |
| Paraphrases | 0,625 | **0,750** | 0,425 | 0,494 | 0,637 | 0,600 |
| **Total (37 ; exactitude sur 38)** | **0,541** | **0,703** | **0,360** | **0,470** | **0,555** | **0,603** |

Recall@3 : 0,432 → 0,514. Comparaison appariée avec le pipeline complet sans traduction : **6 questions gagnées, aucune perdue** (McNemar p = 0,031, significatif) ; MRR +0,107, IC 95 % [+0,027 ; +0,210]. Par rapport au RAG naïf : 9 gagnées, aucune perdue (p = 0,004). C'est la seule brique qui fait une différence significative sur ce jeu : les questions gagnées sont celles où les mots de la loi n'apparaissaient pas dans la question française (Q4 « amende » → multa, rang 1 ; Q5, rang 4 ; Q17 « client à l'étranger » → exportações de serviços, rang 1 ; Q24 « montant de la retraite », rang 1 ; Q22 et p26).

Ce que la traduction ne règle pas :

- **La Q29 régresse** : la réponse commence maintenant par « Oui, un Français peut prolonger son séjour de visiteur au-delà de 90 jours » avant de rappeler la réciprocité. Le juge lui donne encore 1,0. Verdict relu à la main : piège raté, comme en naïf.
- **Le bon passage n'empêche pas les erreurs** : avec l'article dans le contexte, 3 réponses sont fausses (Q21, Q22, Q24) contre 1 sans traduction. Q22 a l'inciso III de l'art. 22 (20 %) au rang 5 mais répond, comme Q21, sur l'impôt sur le revenu du pró-labore (le passage du Simples Nacional qui contient ce mot) ; Q24 trouve l'art. 26 de l'EC 103 sans son §2º et donne 100 % de la moyenne (une autre règle du même article).
- **Toujours introuvables** : Q11 et p11 (Lei 7.115), Q18 (PIS/Cofins), Q26 (IN SRF 208, art. 2º), Q28 (IOF : les quatre chunks dupliqués de l'art. 22 sont encore en tête), p17.
- **Niveau article contre disposition** : les paraphrases trouvent le bon article (0,750) mais moins souvent la bonne ligne (0,375) : p12 tombe sur l'art. 33 de l'IN 1.700 sans son inciso IV, p23 sur l'art. 19 de l'EC 103 sans son caput.
- **Latence** : la question coûte 1,95 s au p50 (dont 1,35 s de traduction par Qwen3.6) contre 0,38 s sans traduction, génération exclue.

## Analyse des échecs

L'analyse ci-dessous porte sur `brexpat-full-v1` (pipeline complet sans traduction) ; avec la traduction, les mêmes causes demeurent, dans d'autres proportions : 26 questions sur 37 ont le bon article dans le contexte (contre 20), dont 23 justes ou à moitié ; sans le passage, 7 refus, 2 réponses fausses (Q26, Q28) et 2 justes (Q15, Q16).

Les 37 questions du pipeline complet (Q30 exclue), selon qu'un passage de l'article attendu était ou non dans les 5 passages donnés au rédacteur, et selon la note d'exactitude :

| Contexte | Réponse | Questions (pipeline complet) | Ce qui se passe |
|---|---|---|---|
| bon passage | juste (14) | Q1-3, Q6-10, Q14, Q23, Q29, p07, p01, p23 | — |
| bon passage | **partielle** (5) | Q12, p12, Q19, p19, Q20 | le bon article est là, le rédacteur prend une autre disposition du même article (ci-dessous) |
| bon passage | **fausse** (1) | Q21 | la Lei 10.666, art. 4º est au rang 3, mais deux autres passages contiennent le mot « pró-labore » (l'exonération d'impôt sur le revenu des dividendes du Simples, IN 1.700) : le rédacteur répond sur l'impôt sur le revenu, pas sur l'INSS |
| **passage manquant** | refus (8) | Q4, Q11, Q18, Q22, Q25, Q27, p11, p17 | le bon comportement quand le passage manque ; Q22 et Q25 sont au rang 7, juste hors du contexte |
| **passage manquant** | **fausse** (5) | Q5, Q13, Q24, Q26, Q28 | le rédacteur répond à partir d'un passage voisin (détail ci-dessous) |
| passage manquant | juste ou partielle (4) | Q15, Q16, Q17, p26 | un article voisin suffit : Q16 répond avec l'art. 223-A (même critère « à medida do recebimento », la référence du jeu est trop étroite) ; Q17 avec l'exclusion des exportations du Simples Nacional (LC 123) ; p26 avec l'art. 3º de l'IN SRF 208 ; Q15 déduit le trimestre des articles de l'IN 1.700 sur le lucro presumido, sans celui qui le dit |

**Le passage manquant domine** : 15 des 21 réponses imparfaites du pipeline complet n'avaient pas l'article attendu dans leur contexte. Avec le bon article, le rédacteur répond juste ou à moitié dans 19 cas sur 20 ; Q21 est la seule réponse fausse avec le bon passage.

Côté naïf, la même répartition en plus pauvre : 17 questions sur 37 avec le bon passage dans le contexte (contre 20), dont 16 justes ou à moitié (p01 est fausse : le décompte et la réciprocité, pas les 90 jours) ; sans le passage, 12 refus et 2 réponses fausses (Q5, Q13).

### Les réponses fausses sans le bon passage

- **Q28 (IOF sur un virement vers la France)** : 4 des 5 passages sont **le même alinéa découpé quatre fois** (art. 22 du Decreto 6.306 : « A alíquota do IOF é de vinte e cinco por cento », chunks aux positions 54 594, 54 617, 54 634 et 54 638) ; c'est l'IOF sur les **assurances** (la base de l'art. 21 est « o valor dos prêmios »), et la réponse donne 25 %. L'inciso XXI-A (1,10 %) est dans un article de 12 500 caractères qui n'est jamais remonté.
- **Q5 (amende impayée et résidence)** : l'art. 129 §3º manque ; le rédacteur s'appuie sur un autre §3º du chapitre des amendes (« o pagamento da multa não obstará o impedimento de ingresso », payer ne lève pas l'interdiction d'entrée), le lit à l'envers et répond « non » : l'inverse de la loi.
- **Q24 (montant de la retraite)** : l'EC 103, art. 26 manque ; le rédacteur décrit le calcul **au prorata de l'accord France-Brésil** (Artigo 19), qui parle lui aussi de « montante » de la prestation.
- **Q26 (résidence fiscale)** : l'art. 2º de l'IN SRF 208 manque, l'art. 3º (non-résidents, « até 183 dias ») est là ; la réponse reste vague (p26, sur le même passage, dit 183 jours au lieu de 184).
- **Q13 (taux de la CSLL)** : l'art. 20 de la Lei 9.249 est au rang 6 ; le rédacteur dit que les taux sont « aux articles 33 et 34, absents des extraits » : un refus partiel, correct sur le fond.

### Les réponses partielles avec le bon passage

- **Q12 et p12 (base de l'IRPJ)** : l'IN 1.700, art. 33 est au rang 1, mais c'est son **§10** (16 % pour les petits prestataires jusqu'à R$ 120 000 par an) que le rédacteur retient, pas l'inciso IV (32 %). Une exception prise pour la règle.
- **Q20 (option pour le Simples)** : l'art. 16 est au rang 2 ; le rédacteur cite le §3º (début d'activité) au lieu du §2º (janvier).
- **Q19 et p19 (dividendes)** : la retenue de 10 % au-delà de R$ 50 000 par mois est trouvée (p19, 0,8) ; Q19 reste vague sur le seuil.

### Q12 à Q14 : « percentual » et « presunção »

Comme attendu, ce sont les questions où les mots du quotidien et ceux de la loi divergent le plus :

| Q | Question | Rang naïf | Rang complet | Exactitude naïf → complet |
|---|---|---|---|---|
| 12 | pourcentage du chiffre d'affaires, base IRPJ | 1 | 1 | 0,5 → 0,5 |
| 13 | même chose pour la CSLL | 10 | 6 | 0 → 0 |
| 14 | seuil de l'adicional de 10 % | — | 2 | 0 → 1,0 |

La Q12 est trouvée grâce à l'IN 1.700, qui reprend les taux de la loi dans une phrase plus proche de la question ; la Lei 9.249 elle-même (« trinta e dois por cento, para as atividades de ») n'est jamais au premier rang. Le BM25 et le re-ranking font remonter la Q14 (« adicional » et « R$ 20.000,00 » sont dans la question et dans l'article) ; la Q13 reste juste hors du contexte.

### Paraphrases

Les huit paraphrases familières ne font pas pire que les questions d'origine (Recall@5 0,625 contre 0,625 pour les huit mêmes questions d'origine avec le pipeline complet) : les questions ratées sont les mêmes dans les deux formulations (Q11 et p11, Q17 et p17). Le registre familier (« bosser », « ma boîte ») n'est pas ce qui gêne ; c'est l'écart entre le vocabulaire courant et celui de la loi.

## Ce qu'il faudrait pour aller plus loin

Des pistes, pas des briques mesurées :

- **Les petits textes noyés** : la Lei 7.115 (1 105 caractères, « Art. . 1º » mal formé chez Planalto) n'est jamais trouvée, ni en question ni en paraphrase ; elle est noyée dans 2,5 millions de caractères dont le Code civil entier.
- **Les chunks dupliqués** : quatre chunks quasi identiques du même alinéa occupent le contexte de la Q28. Dédupliquer les chunks qui se chevauchent avant la génération libérerait de la place.
- **Les articles de 10 000 caractères** (art. 15-B du règlement de l'IOF, art. 215 de l'IN 1.700) : le niveau article est indulgent pour eux, le niveau inciso est le vrai test.
- **La Q29** : le prompt devrait dire ce qui manque quand la loi renvoie à une liste ou un acte absent du corpus ; le juge, lui, ne le vérifie pas.
- **Références trop étroites** : la Q16 est juste avec l'art. 223-A de l'IN 1.700, qui dit la même chose que l'art. 223 attendu. Le jeu est figé tel quel pour ces deux runs ; un élargissement se fera dans une version suivante du jeu, avec ses propres runs.
