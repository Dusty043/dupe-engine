# Detection vs Adjudication

## Detector role

A detector finds candidate duplicate pairs or emits evidence.

Detector examples:

```text
exact_image_detector
exact_text_detector
perceptual_visual_detector
weighted_text_detector
embedding_detector
llm_candidate_detector
```

Detector output should look like:

```json
{
  "candidate_pair": ["docA:p12", "docB:p4"],
  "source": "embedding_detector",
  "score": 0.91,
  "reason": "high semantic similarity"
}
```

## Adjudicator role

The adjudicator reviews evidence for an already-nominated pair.

It should not compare every page against every page.

Adjudicator input should contain structured evidence:

```json
{
  "pair": {
    "page_a": "docA:p12",
    "page_b": "docB:p4"
  },
  "signals": [
    {"layer": "tfidf", "score": 0.82},
    {"layer": "embedding", "score": 0.91},
    {"layer": "phash", "distance": 14}
  ],
  "evidence": {
    "text_source_a": "ocr",
    "text_source_b": "native",
    "shared_rare_terms": ["atorvastatin", "lumbar", "smith clinic"]
  }
}
```

Adjudicator output should be strict JSON:

```json
{
  "decision": "likely_duplicate",
  "confidence": 0.88,
  "reason": "The pair shares visit-specific provider, date, diagnosis, and medication evidence. Differences appear consistent with scan/OCR artifacts.",
  "supporting_factors": ["same provider", "same visit date", "high embedding similarity"],
  "risk_flags": ["OCR used on page A", "not exact image match"]
}
```

## Allowed final decisions

```text
duplicate
likely_duplicate
possible_duplicate
partial_overlap
not_duplicate
needs_review
```

## What not to do

Do not make the adjudicator the first-pass duplicate detector.

Do not ask the LLM to compare every possible page pair.

Do not allow the LLM to invent arbitrary labels.

Do not let the LLM overwrite detector evidence without preserving the original signals.
