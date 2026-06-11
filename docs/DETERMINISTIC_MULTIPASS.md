# Deterministic Multi-Pass Matching

The deterministic engine uses strict, standard, and loose threshold bands before using AI.

```text
exact hash
→ strict deterministic
→ standard deterministic
→ loose deterministic
→ candidate hygiene / budgets
→ optional embeddings
→ later LLM detector/adjudicator
```

The bands are confidence levels, not independent votes.

Example:

```text
pHash distance <= 8  = strict visual
pHash distance <= 16 = standard visual
pHash distance <= 28 = loose visual
```

A page pair that passes loose also technically passes the looser threshold only once. Do not count strict/standard/loose as three independent signals.

v0.6 defaults visual-all-pages to false because the medium synthetic corpus showed that applying loose visual matching across all text-rich pages can create candidate explosion. Enable with:

```bash
--multipass-visual-all-pages
```
