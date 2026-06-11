# v0.9.3 Handoff — Mandatory OpenAI OCR Fallback

## What changed

v0.9.3 makes both OCR and OpenAI vision OCR fallback part of the required v1 runtime contract.

Required defaults:

```text
DUPE_OCR_ENABLED=true
DUPE_REQUIRE_OCR=true
DUPE_OPENAI_OCR_ENABLED=true
DUPE_REQUIRE_OPENAI_OCR=true
DUPE_OPENAI_OCR_DRY_RUN=false
```

A run now fails before processing if the required OpenAI OCR fallback is unavailable. The usual fix is to set one unified key:

```bash
export DUPE_OPENAI_API_KEY="your_key_here"
```

or:

```bash
export OPENAI_API_KEY="your_key_here"
```

Route-specific overrides still work:

```text
DUPE_OPENAI_OCR_API_KEY
DUPE_OPENAI_OCR_API_KEY_ENV
```

## Browser UI behavior

The local browser upload flow now always starts engine jobs with:

```text
--ocr
--require-ocr
--openai-ocr
--openai-ocr-live
--require-openai-ocr
```

The upload screen copy now says OCR plus OpenAI fallback are required.

## CLI behavior

The default `EngineConfig` enables and requires OpenAI OCR fallback. The new explicit flag is:

```text
--require-openai-ocr
```

It is kept mainly for script readability because the default is already required.

## Doctor behavior

`dupe-engine doctor` still acts as a diagnostic command, but it now prints blocking configuration errors when required capabilities are missing.

Expected healthy status:

```text
ocr: available
  required: true
openai_ocr_fallback: available
  required: true
```

If the OpenAI key is missing, normal engine runs exit before processing.

## Test corpora scripts

The v3 small and medium scripts now include the required OpenAI fallback flags. These scripts require a valid OpenAI key.
