from __future__ import annotations

from raglab.benchmarks.squad_style import SquadStyleLoader


class PIAFLoader(SquadStyleLoader):
    """Loader for PIAF — « Pour une IA Francophone ».

    French Q/A dataset over Wikipedia, published by Etalab (French
    administration). SQuAD-style schema, ~3800 questions over ~500 articles,
    CC-BY-4.0 / CC-BY-SA-3.0 (inherits Wikipedia licensing).

    Hugging Face dataset id: ``etalab-ia/piaf`` (openly accessible, no
    authentication required).

    Source: https://www.data.gouv.fr/fr/datasets/piaf-le-dataset-francophone-de-questions-reponses/
    """

    name = "piaf"
    language = "fr"
    licence = "CC-BY-SA-3.0"
    description = "French Wikipedia QA dataset (SQuAD-style) published by Etalab"
    default_corpus_name = "piaf_fr"
    source = "https://huggingface.co/datasets/etalab-ia/piaf"

    hf_dataset_id = "etalab-ia/piaf"
    default_split = "train"
