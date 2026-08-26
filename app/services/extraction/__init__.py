"""Extraction sub-package.

Flow per file:
    reader (by detected content type) -> raw table(s)
    -> normalize() -> list[NormalizedRow]
    -> low-confidence fields -> LLM verification hook -> needs_review flags

Heavy model engines (PaddleOCR, Table Transformer) are lazy imports behind
interfaces so the pipeline runs anywhere; engines degrade to explicit
"engine unavailable" failures instead of silent misreads.
"""
