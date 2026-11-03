"""French codes from Légifrance (LEGI open data) for the legal benchmark."""

from raglab.legifrance.codes import CODES, CodeSpec, get_code
from raglab.legifrance.collector import CodeCollector

__all__ = ["CODES", "CodeCollector", "CodeSpec", "get_code"]
