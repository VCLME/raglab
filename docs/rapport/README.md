# Rapport technique (LaTeX)

`raglab-rapport.tex` est le rapport technique de raglab : contexte et objectifs, architecture (figure TikZ), méthodologie de mesure, briques de la phase 9, résultats, limites et suite. Il est écrit pour être lu en PDF, par exemple dans un portfolio.

## Construire le PDF

Une seule des chaînes suivantes suffit. Le document compile avec pdfLaTeX, XeLaTeX ou LuaLaTeX et n'utilise que des paquets standards (TikZ, booktabs, tabularx, listings, fancyhdr, titlesec, babel français).

| Outil | Installation (Windows) | Commande |
|---|---|---|
| [tectonic](https://tectonic-typesetting.github.io/) (recommandé : un seul binaire, télécharge les paquets nécessaires au premier build) | `winget install TectonicTypesetting.Tectonic` | `tectonic raglab-rapport.tex` |
| MiKTeX ou TeX Live | installateur officiel | `latexmk -pdf raglab-rapport.tex` |

Depuis la racine du dépôt :

```bash
powershell -NoProfile -ExecutionPolicy Bypass -File docs/rapport/build.ps1
```

Ou, là où `make` existe :

```bash
make -C docs/rapport
```

Le PDF est écrit à côté du `.tex` (`docs/rapport/raglab-rapport.pdf`).

## Mettre à jour les résultats

Les valeurs pas encore mesurées sont marquées `\aMesurer{}` (affichées « [à mesurer] » en orange). Quand un run existe, remplacer chaque marque par le chiffre lu dans `benchmarks/results/<label>.json` (ou dans le tableau de `raglab bench report …`), jamais par une estimation. Les chiffres déjà présents viennent de fichiers versionnés :

| Section du rapport | Source |
|---|---|
| Jeux d'évaluation, questions LexML | [`docs/benchmarks/protocole.md`](../benchmarks/protocole.md), [`benchmarks/README.md`](../../benchmarks/README.md) |
| Calibration des juges | [`benchmarks/judge_calibration.json`](../../benchmarks/judge_calibration.json) |
| Streaming de l'API | [`docs/api-production.md`](../api-production.md) |
| Génération sur GPU | [`docker-compose.gpu.yml`](../../docker-compose.gpu.yml), README du dépôt |
