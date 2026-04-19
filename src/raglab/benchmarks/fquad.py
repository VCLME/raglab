from __future__ import annotations

from raglab.benchmarks.squad_style import SquadStyleLoader, _article_stem  # noqa: F401 (re-exported for tests)


class FQuADLoader(SquadStyleLoader):
    """Loader for FQuAD — SQuAD-style French reading-comprehension dataset.

    Source: https://fquad.illuin.tech (Illuin Technology).
    Hugging Face dataset id: ``fquad`` (may require ``huggingface-cli login``
    and accepting the licence; the dataset has been restricted at times).
    Licence: CC-BY-SA-3.0.

    If the download fails with `DatasetNotFoundError`, use the PIAF loader
    instead (``raglab bench download piaf``) which has similar French
    Wikipedia Q/A coverage under an openly accessible licence.
    """

    name = "fquad"
    language = "fr"
    licence = "CC-BY-SA-3.0"
    description = "SQuAD-style French QA over Wikipedia passages (Illuin Technology)"
    default_corpus_name = "fquad_fr"
    source = "https://huggingface.co/datasets/fquad"

    hf_dataset_id = "fquad"
    default_split = "validation"
