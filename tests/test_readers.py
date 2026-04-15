from raglab.ingestion.readers import normalize_text


def test_normalize_text_reduces_repeated_spaces_and_newlines():
    raw = "Bonjour   monde.\r\n\r\n\r\nLigne   suivante."
    normalized = normalize_text(raw)
    assert "  " not in normalized
    assert "\r" not in normalized
    assert "\n\n\n" not in normalized
