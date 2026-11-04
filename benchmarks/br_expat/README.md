# Jeu « Brésil expat » : 30 questions réelles

Les 30 questions qu'un Français installé au Brésil, gérant d'une société au lucro presumido, s'est réellement posées (immigration, impôts de société, INSS, fiscalité personnelle), compilées par son assistante. Les questions sont en **français**, le corpus en **portugais** : c'est aussi un test translingue. Le corpus est décrit dans [docs/corpus-br-expat.md](../../docs/corpus-br-expat.md).

| Fichier | Contenu |
|---|---|
| `ground_truth.jsonl` | 38 questions : les 30 questions (dont la Q13 réécrite pour être autonome) et 8 paraphrases familières |
| `corpus_manifest.json` | empreinte SHA-256 des 19 textes collectés le 4 novembre 2026 |
| `../../scripts/br_expat_ground_truth.py` | questions, réponses et références écrites à la main ; le script calcule les positions dans les textes et échoue si un article ou un passage n'est plus trouvé |

## Format

Chaque ligne suit le format des autres jeux (`expected_spans` lu par `raglab bench`), avec :

- `question_type` : le thème, `immigration` (Q1-11), `company_tax` (Q12-20), `inss_personal_tax` (Q21-28), `trap` (Q29-30) ou `paraphrase` ;
- `expected_spans` : **l'article entier** (de sa ligne de titre à l'article suivant). Un passage qui tombe n'importe où dans le bon article compte : c'est le niveau « article » demandé ;
- `context.provision_spans` : les lignes qui portent la réponse (le paragraphe, l'inciso). Plus strict, utilisé dans l'analyse des échecs ;
- `context.references` : les articles attendus, lisibles (« decreto_9199_2017 art. 20 ») ;
- `context.paraphrase_of` pour les paraphrases, `context.expected_behaviour` pour les pièges (`cite_and_flag_missing`, `abstain`).

La Q30 (Livret A) n'a pas de passage attendu : elle compte comme un échec dans les moyennes de recherche de `raglab bench`, qui ne savent pas l'exclure. Les tableaux de [docs/corpus-br-expat.md](../../docs/corpus-br-expat.md) la sortent des moyennes de recherche et la notent seulement sur la réponse.

## Paraphrases familières

Huit questions reformulées comme on les tape vraiment, avec les références de la question d'origine :

| id | Question | D'après |
|---|---|---|
| brx-p07 | je peux bosser payé au Brésil avec mon visa touriste ? | Q7 |
| brx-p01 | je peux rester combien de temps au Brésil en touriste, et ça se rallonge ? | Q1 |
| brx-p11 | mon nom est pas sur le bail, comment je prouve où j'habite ? | Q11 |
| brx-p12 | ma boîte fait de la presta en lucro presumido, l'impôt sur les bénéfices est calculé sur quelle part de ce que je facture ? | Q12 |
| brx-p17 | je facture un client en France depuis le Brésil, je dois payer l'ISS ? | Q17 |
| brx-p19 | si je me verse des dividendes de ma boîte, je paie de l'impôt dessus ? | Q19 |
| brx-p23 | la retraite au Brésil c'est à quel âge, faut avoir cotisé combien ? | Q23 |
| brx-p26 | au bout de combien de temps au Brésil je deviens résident fiscal là-bas ? | Q26 |

## Vérification des références

Chaque référence a été relue dans le texte collecté (version compilée de Planalto, vue « vigente » de la Receita Federal). Quand la référence de départ était fausse ou incomplète, c'est **la référence** qui a été corrigée, jamais la recherche. Le corpus a ensuite été parcouru à la recherche d'autres passages qui donnent la même réponse (l'IN RFB 1.700 reprend les taux et les règles des lois) ; ceux-là sont ajoutés comme références alternatives, avant toute mesure publiée : les deux runs ci-dessous sont notés sur le même jeu.

| Q | Référence de départ | Vérifié | Correction |
|---|---|---|---|
| 1-3 | Decreto 9.199, art. 20 (caput, §2º, §1º) | oui | — |
| 4 | Decreto 9.199, art. 307 ; Lei 13.445, art. 109 | en partie | Les art. 307 II et 109 II donnent la « multa por dia de excesso » mais pas le plafond. Le plafond est dans **Lei 13.445, art. 108, V** et **Decreto 9.199, art. 301, V** (de R$ 100 à R$ 10 000 pour une personne physique) : ajoutés |
| 5 | Decreto 9.199, art. 129 §3º (à vérifier) | **oui** | — (« a tramitação de pedido de autorização de residência ficará condicionada ao pagamento das multas ») |
| 6 | Lei 13.445, art. 31 §5º | oui | — |
| 7 | Lei 13.445, art. 13 §1º | oui | L'exception (diárias, ajuda de custo, cachê, pró-labore, frais) est au **§2º** : ajouté aux passages |
| 8 | Lei 13.445, art. 37 ; Decreto 9.199, art. 153 (à vérifier) | **oui** | — (art. 153, I : « cônjuge ou companheiro ») |
| 9 | Código Civil, art. 1.723 | oui | — |
| 10 | Decreto 9.199, art. 67 (à vérifier) | **oui**, avec une nuance | L'art. 67 porte sur le **registro** (l'enregistrement après l'autorisation), pas sur le dépôt de la demande : inciso II (unité de la circonscription du domicile) et §2º (autre unité par décision motivée). La réponse attendue est la bonne pour l'enregistrement |
| 11 | Lei 7.115/1983, art. 1º | oui | — (Planalto écrit « Art. . 1º - ») |
| 12 | Lei 9.249, art. 15 §1º, III, a | oui | Ajouté : **IN RFB 1.700, art. 33 §1º, IV** (même 32 %) et **art. 215** (le lucro presumido applique les taux de l'art. 33), trouvés quand la recherche naïve a remonté l'art. 33 §10. Le caput donne 8 % et l'art. 33 §10 donne 16 % pour les petits prestataires : deux pièges de lecture |
| 13 | Lei 9.249, art. 20 | oui | Le 32 % est à l'**inciso I** (inséré par la LC 167/2019) ; ajouté : **IN RFB 1.700, art. 34 §1º**. Question réécrite pour être autonome |
| 14 | Lei 9.249, art. 3º §1º ; Lei 9.430, art. 4º | oui | L'art. 4º de la Lei 9.430 est le texte modificatif de l'art. 3º ; ajouté : **IN RFB 1.700, art. 29 §1º** |
| 15 | Lei 9.430, art. 1º et 5º | oui | Trimestre à l'art. 1º, trois quotas à l'art. 5º §1º ; ajouté : **IN RFB 1.700, art. 31** (trimestre) |
| 16 | IN RFB 1.700/2017, art. 223 (à vérifier) | **oui** | — (« reconhecimento de suas receitas na medida do recebimento » et livro Caixa) |
| 17 | LC 116/2003, art. 2º, I | oui | La condition « résultat à l'étranger » est au **parágrafo único** : ajouté aux passages |
| 18 | Lei 10.833, art. 6º ; Lei 10.637, art. 5º | oui | — (inciso II, « ingresso de divisas ») |
| 19 | Lei 9.249, art. 10 ; Lei 15.270/2025 | oui | Précisé : la retenue de 10 % au-delà de R$ 50 000/mois est l'**art. 6º-A de la Lei 9.250**, inséré par l'art. 2º de la Lei 15.270 (la Lei 9.250 n'est pas dans le corpus, le texte de l'article est dans la Lei 15.270) ; le non-résident est à l'**art. 10 §4º** de la Lei 9.249. Ajouté : la nouvelle rédaction de l'art. 10, citée entre guillemets dans la Lei 15.270 (art. 3º) |
| 20 | LC 123/2006, art. 16 | oui | caput (irrévocable pour l'année) et §2º (en janvier) |
| 21 | Lei 8.212, art. 12, V, f ; Lei 10.666, art. 4º | en partie | Le chiffre de **11 % n'est écrit nulle part pour ce cas** : il vient de l'**art. 21** de la Lei 8.212 (20 %) moins la déduction de l'**art. 30 §4º** (45 % de la part patronale, plafonnée à 9 %). Ajoutés. Attention : l'art. 21 §2º, I dit bien « 11 % », mais pour le plan simplifié, sans rapport avec le pró-labore |
| 22 | Lei 8.212, art. 22, III | oui | — |
| 23 | EC 103/2019, art. 19 | oui | — (62 ans et 15 ans pour une femme, aussi dans la réponse) |
| 24 | EC 103/2019, art. 26 | oui | caput (moyenne de tous les salaires) et §2º (60 % + 2 points) |
| 25 | Decreto 8.300/2014 | précisé | L'accord est en annexe du décret, ses articles s'écrivent « Artigo N » : **Artigo 16** (totalisation) et **Artigo 19, §2** (prorata) |
| 26 | IN SRF 208/2002, art. 2º | oui | inciso III, b, items 2 et 3. Le premier identifiant de la Receita (15081) est la republication partielle de 2004 (l'annexe II seulement) : le texte complet est l'acte 15079 |
| 27 | Lei 14.754/2023, art. 2º et 3º | oui | 15 % à l'art. 2º §1º |
| 28 | Decreto 6.306/2007, art. 15-B | oui | inciso XXI (3,5 %, disponibilité) et XXI-A (1,10 %, investissement), réécrits par le Decreto 12.499/2025. L'art. 15-B fait 12 500 caractères : au niveau article, n'importe quel passage de l'article compte ; le niveau inciso est dans `provision_spans` |
| 29 | piège | oui | Decreto 9.199, art. 20 §2º. La liste des pays qui accordent la réciprocité (QGRV du MRE) n'est pas dans le corpus : la bonne réponse le dit au lieu de répondre oui |
| 30 | hors corpus | — | aucun passage ; la bonne réponse est « je ne trouve pas » |

## Reproduire

```bash
raglab lexml br-expat                       # collecte (19 textes, environ 20 s)
python scripts/br_expat_ground_truth.py     # recalcule les positions, échoue si un texte a bougé
raglab bench all --suite br_expat --label brexpat-naive-v1 --retrieval-mode dense --no-rerank --no-citations --versions all --ragas-limit 0
raglab bench all --suite br_expat --label brexpat-full-v1 --no-query-translation --ragas-limit 0
raglab bench all --suite br_expat --label brexpat-qt-v1 --ragas-limit 0    # défaut actuel, avec la traduction des questions
```

Planalto met ses textes compilés à jour en place : une collecte ultérieure peut différer (Lei 9.249 et Lei 10.666 ont été modifiées en 2026). Comparez les `sha256` de `corpus_manifest.json` avec ceux de `data/lexml/br_expat/manifest.json` ; `raglab bench` refuse de tourner si un texte a changé.

Licence : législation fédérale brésilienne, domaine public (Lei 9.610/1998, art. 8º, IV).
