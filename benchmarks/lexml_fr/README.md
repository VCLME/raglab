# Questions en français sur les lois brésiliennes (`lexml_fr`)

Jeu figé pour le mode d'échec « langues croisées » : un utilisateur pose sa question en français, la réponse est dans le corpus LexML en portugais (252 lois fédérales, `bench_lexml_pt`). Les deux fichiers ont les mêmes identifiants, dans le même ordre :

| Fichier | Question | Suite |
|---|---|---|
| `ground_truth.jsonl` | en français (`question`), la question portugaise d'origine dans `source_question` | `lexml_fr` |
| `ground_truth_pt.jsonl` | la question portugaise d'origine | `lexml_fr_pt` |

La pertinence (`expected_file_names`, `expected_spans`, `ground_truth_answer`) est celle de la question d'origine, inchangée : on compare les deux langues sur exactement les mêmes passages attendus.

## Comment il a été fait

```bash
python scripts/build_lexml_fr.py --select              # le tirage
python scripts/build_lexml_fr.py --translations t.tsv  # écrit les deux fichiers
```

1. **Candidats** : les questions de `benchmarks/lexml_fulltext/ground_truth.jsonl` de type `paraphrase` ou `entity`, non rejetées à la relecture, qui ne citent ni article, ni paragraphe (`§`), ni numéro de loi, de décret ou de mesure provisoire. Les questions `reference` (« art. 2 da Lei nº 7.689 ») sont exclues : elles se résolvent par l'identifiant, que le résolveur de citations lit dans les deux langues, et ne disent rien de la langue. Les questions en double (même texte, autre passage) ne sont gardées qu'une fois. Restent 175 candidats.
2. **Tirage** : 100 questions, triées par identifiant puis tirées avec la graine 42 (52 `paraphrase`, 48 `entity`).
3. **Traduction** : écrite par un LLM (Claude Opus 5.5), consigne « français naturel, comme le poserait un juriste ou un particulier francophone, pas du mot à mot ». Règles suivies :
   - les noms communs d'institutions sont traduits (« Ministério da Fazenda » → « ministère des Finances », « Conselhos Regionais » → « conseils régionaux ») ;
   - les sigles restent tels quels (DNPM, BNDES, Finep, IPI, FINSOCIAL, CETEM…), comme un francophone les recopierait ;
   - les noms propres de programmes ou de titres sans équivalent restent en portugais (ProJovem, Empresa Cidadã, Letras Financeiras do Tesouro), parfois glosés (« maté (erva-mate) ») ;
   - la tournure suit le français (« De que maneira… ? » → « Comment… ? »), sans ajouter ni retirer d'indice sur la réponse.
4. **Relecture** : 20 questions tirées au hasard (graine 7) relues à la main face à la question d'origine et à la réponse attendue. Les 20 gardent le sens et les mêmes indices ; aucune n'a été corrigée. Une remarque : `lexml-0151` (« Qui est l'auteur du texte qui ne remplace pas celui publié au Journal officiel… ») est une question faible dès la source (elle vise la mention finale de la loi), gardée telle quelle pour rester apparié.

## Limites

- Traduction par un modèle, relue sur un échantillon : une tournure peut rester plus proche du portugais qu'une question spontanée.
- Les questions d'origine sont écrites par Qwen3.6 en lisant le passage : elles reprennent souvent ses mots (`lexical_overlap`), ce qui avantage la question portugaise face au BM25. C'est justement l'écart qu'on mesure, mais la perte réelle d'une question française spontanée peut être différente.
- La réponse attendue (`ground_truth_answer`) reste en portugais ; un juge qui note une réponse française la compare donc à une référence portugaise.

Licence : législation brésilienne, domaine public (Lei 9.610/1998, art. 8º, IV) ; traductions écrites pour raglab.
