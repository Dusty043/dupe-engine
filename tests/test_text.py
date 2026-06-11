from dupe_engine.text import normalize_text_for_hash, normalize_text_for_similarity, tokenize_for_similarity


def test_hash_normalization_preserves_dates_and_ids():
    text = "Patient: Alex Morgan\nDOB: 01/02/1980\nMRN: 123456"
    normalized = normalize_text_for_hash(text)
    assert "01/02/1980" in normalized
    assert "123456" in normalized


def test_similarity_normalization_removes_page_labels():
    text = "Page 1 of 4\nAssessment and Plan"
    normalized = normalize_text_for_similarity(text)
    assert "page 1 of 4" not in normalized
    assert "assessment" in normalized


def test_tokenizer_removes_domain_stopwords():
    tokens = tokenize_for_similarity("Patient medical record lumbar radiculopathy")
    assert "patient" not in tokens
    assert "medical" not in tokens
    assert "lumbar" in tokens
    assert "radiculopathy" in tokens
