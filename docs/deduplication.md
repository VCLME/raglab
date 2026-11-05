# Déduplication des passages (expérimental)

Ce document répond au lot 3 de l'audit du 4 novembre 2026. Option `dedup`, désactivée par défaut (`RAGLAB_RETRIEVAL_DEDUP=false`). Elle est disponible :
- en CLI : `raglab query --dedup`, `raglab bench all --dedup` ;
- dans l'API : `dedup` dans `/api/query`, `/api/query/stream` et `/api/experiments` ;
- dans le Chat (options de recherche), sur la page Retrieval et dans le lanceur de benchmarks (Évaluation), chacun avec les valeurs défaut, activée et désactivée.

## Le problème

Brazil expat, Q28 (IOF) : trois des cinq passages donnés au rédacteur sont des découpes du même article 22 du Decreto 6.306. Leurs offsets se chevauchent dans le même document. Le rédacteur lit trois fois le même fait au lieu de deux autres passages. Retirer les doublons des cinq passages finaux seulement laisserait des places vides.

## La méthode (`src/raglab/retrieval/dedup.py`)

1. Le re-ranker garde une réserve de `RAGLAB_DEDUP_POOL` candidats (40), au lieu de couper tout de suite à 5. Il note les mêmes 40 paires qu'avant.
2. Les versions de cette réserve sont annotées. Puis on la parcourt dans l'ordre, et on garde les 5 premiers passages qui ne répètent pas un passage déjà gardé.
3. Un passage est écarté seulement s'il est **entièrement inclus** dans un passage déjà gardé : même document, même état de version, et son intervalle d'offsets compris dans celui du passage gardé. Il n'ajoute alors aucun caractère.

   Un passage qui ajoute du texte est toujours gardé, quoi que ce texte dise. La règle v2 écartait un passage couvert à 80 % ou plus, pourvu que le texte ajouté ne contienne ni nombre, ni négation, ni exception. La contre-relecture l'a mise en défaut : « These duties concern legal persons. » n'a rien de tout cela, mais dit qui est tenu. Un passage couvert à 92 % qui l'ajoutait était écarté. C'est désormais la règle v3, par inclusion stricte.
4. Les passages épinglés par le résolveur de citations ne sont jamais écartés. Les passages gardés conservent leurs offsets, leurs scores et leurs rangs d'origine ; seul `rank` est renuméroté.
5. La réponse indique la taille de la réserve, les passages écartés (avec le passage qu'ils répètent) et le nombre de places remplies (`dedup_stats`).

Les découpeurs ne sont pas modifiés.

## Mesure

Pipeline par défaut (hybride, re-ranking, citations, versions `in_force`), traduction coupée des deux côtés, sur les 6 jeux figés. Runs appariés : `audit-lot3-dedup-off` contre `audit-lot3-dedup-on` (v1) et `audit-lot3-dedup-on-v2`.

**v1, rejetée.** Elle fusionnait aussi un texte identique trouvé dans un autre document ou à un autre endroit du même document. Résultat (résultats publiés, `bench compare`) : **6 questions perdues** (LexML 2, Code de la consommation 1, UE 3), toutes par cette règle, et **2 gagnées**, toutes par la règle de chevauchement. Une première version de ce document et de la PR #85 annonçait 4 pertes ; c'était une erreur de décompte. Les pertes :
- `lexml-0076` : deux lois différentes ;
- `lexml-0231` : un paragraphe répété ailleurs dans la même loi ;
- `legi-consommation-0181` : L452-3, au même texte que L454-7 ;
- `eurlex-0081`, `eurlex-0132`, `eurlex-0139` : la version consolidée, au même texte que la version du Journal officiel.

Dans un texte juridique, la disposition qui le dit compte. La règle a été retirée, puis la mesure refaite (v2). Cette v2 est donc choisie après avoir vu la v1 : elle n'est pas aveugle.

**v2, remplacée par la v3** (règle de chevauchement à 80 %, mise en défaut par la contre-relecture ; mesures gardées pour l'historique) :

| Jeu | Recall@5 off → v2 | Gagnées / perdues | Passages répétés dans le top 5 | Texte non répété par question (IC 95 % de l'écart) | p50 de l'étape |
|---|---|---|---|---|---|
| PIAF (500) | 0,966 → 0,966 | 0 / 0 | 0 → 0 | 3 322 → 3 322 | 4,7 ms |
| LexML (277) | 0,816 → 0,823 | +2 / −0 (p = 0,50) | 25 → 13 | 4 100 → 4 128 [+11 ; +49] | 4,8 ms |
| Code de la consommation (300) | 0,820 → 0,820 | 0 / 0 | 0 → 0 | 3 484 → 3 484 | 6,5 ms |
| Versions (100) | 0,930 → 0,930 | 0 / 0 | 0 → 0 | 3 098 → 3 098 | 6,5 ms |
| UE (300) | 0,717 → 0,717 | 0 / 0 | 13 → 6 | 4 154 → 4 178 [+5 ; +46] | 8,2 ms |
| Brazil expat (38) | 0,526 → 0,526 | 0 / 0 | 1 → 0 | 3 815 → 3 838 [+0 ; +70] | 4,4 ms |

- Les deux questions gagnées (`lexml-0017`, `lexml-0128`) avaient un fragment entièrement inclus dans un passage déjà gardé. Leur place libérée a fait entrer le bon passage.
- La redondance baisse sur LexML et l'UE, et disparaît sur Brazil expat (Q28 : le fragment inclus est écarté, celui qui ajoute « 1º, incisos II e III » est gardé).
- Le reste du contexte est inchangé. Aucun nouveau poids n'est chargé ; le pic de VRAM n'a pas été mesuré séparément.
- La latence totale varie d'un run à l'autre avec le re-ranking (GPU partagé pendant la mesure). Seule l'étape `dedup` est attribuable.

**Pas mesuré :** l'exactitude des réponses avec et sans déduplication (génération et juge). Le gain de recherche n'est pas significatif et ne touche que quelques questions. C'est donc une absence de preuve de régression, pas une non-régression établie, et aucune amélioration n'est affirmée.

**v3, inclusion stricte (actuelle).** Elle est re-mesurée avec les paramètres de production, réponses comprises : voir [benchmarks/pipeline-2026-11/README.md](../benchmarks/pipeline-2026-11/README.md) (lot 4 de la contre-relecture). Sur les runs v2 enregistrés, les deux questions gagnées (`lexml-0017`, `lexml-0128`) venaient de fragments entièrement inclus, que la v3 écarte aussi.

## Décision

Option laissée **désactivée par défaut**. Elle ne coûte presque rien et réduit la redondance là où il y en a. Mais aucun gain significatif de recherche n'est mesuré, et l'effet sur les réponses reste à mesurer.
