# Evaluation methodology and actual scope

Datasets: backend/evaluation/retrieval_v1.json (22 distinct questions); tasks_v1.json (17 distinct task scenarios). The original eight grammar smoke examples remain in benchmark.py. These counts are separate and must not be combined into a misleading AI accuracy claim. Dataset/corpus SHA-256 hashes and per-case output are recorded in docs/v02/evaluations.

## Actual local neural retrieval

MiniLM embeddings and the cross-encoder really executed on CPU. The same 22 questions were run across lexical, dense, hybrid and hybrid-reranked configurations: 88 query/configuration executions, not 88 unique questions. Twenty questions have positive document relevance judgments; two have no supporting policy. Paraphrases are authored separately from the corpus wording and were not used for model training. They are not a blinded third-party benchmark, and the small corpus is not evidence of generalization to real dealership knowledge.

For each query, retrieval keeps the top three chunks, then deduplicates document IDs for document-level Recall@3, reciprocal rank and binary nDCG@3. The retrieval artifact records chunk IDs and scores as well as expected document IDs. An expected-phrase field tests that at least one relevant answer phrase appears in the excerpts. Citation validity compares returned chunk ID and exact text to the active manifest. This is a provenance/integrity test, not independent semantic support assessment. There is no synthesized-policy-answer hallucination metric because the application quotes evidence rather than generating policy claims.

All configurations compute dense similarity for the common 0.35 abstention diagnostic, including lexical ranking. Therefore lexical timing is not a pure model-free performance baseline. Cold initialization may appear in a first case. Latencies are host-specific single-run measurements, not load-test service-level objectives.

Actual results in retrieval.json: lexical Recall@3 0.90/MRR 0.800; dense 0.95/0.858; hybrid 0.95/0.842; reranked 1.00/0.917. Lexical misses two relevant questions; dense and hybrid each miss one. Reranking fixes these top-three misses on this set, but increases median latency from roughly 10ms to 156ms. It does not prove that hybrid is universally better, and hybrid underperformed dense on MRR here. Both negative questions abstained in these runs; two negatives cannot establish a reliable open-domain abstention rate.

Reproduce from backend: `HF_HUB_DISABLE_XET=1 python evaluate.py retrieval --rerank`. The runner writes per-case outputs and aggregate configuration results. Reranker and embedding identities are pinned in app/config.py and included in output.

## Recommendations, preferences, tools and task completion

The task evaluator runs 17 authored scenarios against deterministic grammar and actual isolated local SQL state. Cases cover multi-turn increases/replacements/removal, negation/decimal currency, soft preferences, ambiguous inputs, two policy-tool selections, unsupported confirmation, injection, five recommendation comparisons/no-match filters and a confirmed booking/cancellation workflow.

Actual result: 17 passed, zero failed/skipped. The tiny set demonstrates regression behavior, not live language-model accuracy. Recommendation relevance uses controlled expected top/eligible vehicle IDs, not a learned ranker or human preference study. Hard-constraint checks use database facts. Ranking quality on real customer preferences remains unmeasured.

Reproduce: unset DATABASE_URL and run `python evaluate.py tasks`. A new temporary SQLite database is allocated by the evaluator. It refuses a supplied application DATABASE_URL. Case outputs include observed preferences, selected tools, ranked IDs, transaction results and latencies.

## Provider and grounding robustness

The pytest JUnit file lists each executed regression case. Mocked provider cases include arbitrary invented-vehicle/action prose, invalid factual plan fields, skipped tool requests, invalid nomination IDs, malformed JSON/envelopes, missing call IDs, unknown tools, invalid arguments, multiple provider calls, bounded internal tool lists, timeout/deadline, rate limits and transient/exhausted retries. Tests exercise valid typed plans, live-path preference proposals and concurrent inference version conflicts. These use HTTP mocks or a mocked planner, not actual LLM inference.

Success/unsupported-action claims are prevented structurally: the UI has no raw model-prose fact channel, and confirmed records are produced only after SQL commit. No LLM-judge score is used to certify that boundary. Prompt-understanding quality is not established by structural tests.

## Live evaluation

`python evaluate.py live` produces an explicit unexecuted artifact if OPENAI_API_KEY/OPENAI_MODEL are absent. That is the status of this release: zero paid LLM calls. When configured, the diagnostic records typed plans, usage/retry traces and errors per eligible task case. It currently does not automatically judge all live-plan semantics against gold labels. It is a diagnostic starting point, not a complete live benchmark runner. No multiple-provider requirement or paid comparative claim is imposed.

Costs remain null because no paid inference ran and no dated pricing model was applied. Pinecone is mock-tested only; no remote vector-service quality or latency claim is made. Local embedding/cross-encoder execution is distinguished from live generative-model execution throughout.
