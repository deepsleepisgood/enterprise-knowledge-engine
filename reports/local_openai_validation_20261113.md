# Local OpenAI validation — 13 November 2026

## Configuration tested

- Provider: OpenAI Chat Completions (`MODEL_SMART=gpt-4.1`, `MODEL_FAST=gpt-4o-mini`).
- Local database: embedded PostgreSQL 16, migrated to `0001`.
- Retrieval: `RERANK_MODEL=none`. The configured `BAAI/bge-reranker-base` model download did not complete, so these scores do **not** measure the normal cross-encoder path.
- Evaluation date used by the harness: 7 November 2026 (`run_eval.py` default).

## Setup and checks

| Check | Result |
| --- | --- |
| Sample ingestion | 5 input files parsed; 157 extractable passages |
| Graph build | 518 fact rows, 243 current facts; 157 passages, 397 facts and 32 entities indexed |
| Conflict scan | 65 groups, 176 comparisons, 54 conflicts, 0 scan failures |
| Default pytest suite | 256 passed; 112 live-model tests deselected |
| Ruff, Next.js lint, TypeScript, token check | Passed |

The induced schema covered 18 of 22 baseline topics. The AP plug-in bound 19 of 22 parameters; `quantity_tolerance.materials`, `tds.goods_purchase_threshold_inr`, and `tds.rate_technical_service` remained unbound.

## Development evaluation

Full 96-question dev split, config D, with the LLM judge: [detailed report](eval_20261113_dev.md) and [per-question CSV](eval_20261113_dev_D.csv).

| Metric | Result | Project target |
| --- | --- | --- |
| Accuracy | 67/96 (69.8%) | At least 90% |
| Strict citation accuracy | 86/96 (89.6%) | At least 95% |
| Conflict answers mentioning outdated values | 2/15 (13.3%) | 0 |
| Unverified answers | 9/96 (9.4%) | 0 shown to processors |
| Median latency | 10.7 s | Under 10 s (Gate A) |

Failure categories: 13 generation, 7 extraction/binding, 4 calculator, 4 verifier, and 1 wrong authority. The most concentrated cluster is TDS: the induced graph and binding map some distinct rates to the same attribute, causing incorrect professional, technical-service and rent calculations. Q007 selected an older GSTR-2A source instead of the current GSTR-2B rule in vector-ranking mode.

The local verifier fix for a retired cut-off weekday restored verified answers for Q004 and Q005. Its [targeted report](eval_20261113_dev_Q004_Q005.md) still shows one unnecessary mention of an old Thursday schedule. The first five calculator scenarios separately passed [5/5](eval_20261113_dev_scenarios5.md).

The OpenAI call log records tokens, but this gateway has no OpenAI price entries, so the displayed `$0.00` evaluation cost is **not** a measured spend. The live `pytest -m live_llm` suite, the holdout split, and browser Playwright checks were not run in this pass. The live suite rebuilds a separate graph; this run instead evaluated the already built local graph.

## Next validation gate

1. Finish downloading the configured reranker and rerun the dev split with `RERANK_MODEL` unset; compare with this vector-ranking baseline.
2. Separate the induced TDS attributes and repair the three unresolved plug-in bindings, then rerun TDS scenarios and the full dev split.
3. Resolve remaining verifier and authority errors before running the holdout split or claiming the historical NVIDIA results for the OpenAI configuration.
