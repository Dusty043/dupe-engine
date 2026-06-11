# v0.6 Embedding Detector

Embeddings are a detector/reranker, not the final adjudicator.

## Placement

```text
deterministic candidate
→ escalation policy says embedding is justified
→ embed best available text for the pair
→ add embedding_similarity signal
→ later adjudicator can review the evidence
```

## Important constraints

- No embeddings for exact image/text duplicates by default.
- No embeddings for low-information pairs.
- No embeddings for all possible page pairs.
- Embedding provider usage is visible in the capability report.
- If the provider is unavailable, the deterministic job still runs unless strict mode is enabled.

## OpenAI provider

The current provider posts to `/embeddings` using:

```text
DUPE_EMBEDDINGS_PROVIDER=openai
DUPE_EMBEDDINGS_MODEL=text-embedding-3-small
DUPE_OPENAI_API_KEY=...
```

For approved OpenAI-compatible gateways in v0.9.3, keep the provider as `openai` and override the base URL/key only:

```text
DUPE_EMBEDDINGS_PROVIDER=openai
DUPE_EMBEDDINGS_BASE_URL=https://internal-gateway/v1
DUPE_EMBEDDINGS_API_KEY=...
```
