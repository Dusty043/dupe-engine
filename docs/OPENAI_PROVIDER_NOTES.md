# OpenAI Provider Notes

v0.9.3 treats OpenAI as the only external AI provider family while keeping each route logically separate.

The project may use one unified approved OpenAI key for compliance. Route-specific overrides are still allowed, but provider values should remain `openai`. The engine should still treat each OpenAI use as a different internal route with its own gate, input kind, model config, and ledger row.

## Logical routes

```text
vision_ocr_extraction
text_embedding
text_adjudication
vision_pair_adjudication
```

See `docs/V0_8_1_OPENAI_ROUTE_GOVERNANCE.md` for the full route contract.

## Shared key, separate routes

The code can use route-specific keys if available:

```bash
DUPE_OPENAI_OCR_API_KEY=...
DUPE_EMBEDDINGS_API_KEY=...
```

or one shared approved key:

```bash
DUPE_OPENAI_API_KEY=...
```

or the standard fallback:

```bash
OPENAI_API_KEY=...
```

A shared key is acceptable only if the engine keeps route boundaries in code and reporting.

## Vision OCR extraction

This is a fallback text-extraction route, not a general duplicate judgment route.

```text
selected weak-text candidate page
→ send one rendered page image
→ extract visible text only
→ update best_text only if usable/improved
```

Required configuration for live calls:

```bash
DUPE_OCR_ENABLED=true
DUPE_OPENAI_OCR_ENABLED=true
DUPE_REQUIRE_OPENAI_OCR=true
DUPE_OPENAI_OCR_DRY_RUN=false
DUPE_OPENAI_OCR_MODEL=<approved vision-capable model>
DUPE_OPENAI_API_KEY=...
```

Legacy dry-run validation, for governance tests only:

```bash
DUPE_OPENAI_OCR_DRY_RUN=true
```

Production-style v0.9.3 runs keep this false because OpenAI fallback is required.

## Embeddings

Embeddings are a detector/reranker layer, not final adjudication.

```text
candidate pair selected by deterministic escalation
→ embed page A and page B best text
→ compute cosine similarity
→ add embedding_similarity signal
```

Required configuration:

```bash
DUPE_EMBEDDINGS_ENABLED=true
DUPE_EMBEDDINGS_PROVIDER=openai
DUPE_EMBEDDINGS_MODEL=text-embedding-3-small
DUPE_OPENAI_API_KEY=...
```

Approved gateway shape:

Keep the provider as `openai` and override only the base URL/key when the approved gateway is OpenAI-compatible:

```bash
DUPE_EMBEDDINGS_PROVIDER=openai
DUPE_EMBEDDINGS_BASE_URL=https://internal-gateway/v1
DUPE_EMBEDDINGS_API_KEY=...
```

Dry-run validation:

```bash
DUPE_EMBEDDINGS_DRY_RUN=true
```

## LLM detector and adjudicator

These remain provisioned but deferred. They should stay separate:

```text
llm_candidate_detector = optional late detector for hard candidates
adjudicator_agent = final evidence reviewer for candidate pairs
```

Do not let the LLM scan all possible page pairs. Do not let vision OCR extraction silently become vision-pair duplicate adjudication.

## AI ledger outputs

Use:

```bash
--ai-ledger-out output/ai_ledger.json \
--ai-ledger-csv output/ai_ledger.csv
```

The ledger records route, status, provider, model, subject, reason, selected/attempted/succeeded flags, dry-run state, and whether evidence/matching changed. It does not store extracted page text by default.
