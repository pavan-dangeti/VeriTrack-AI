"""LLM-based verification of low-confidence OCR fields (LangChain).

Contract:
    verify_row(row: NormalizedRow) -> NormalizedRow
    - If an LLM is configured, asks the model to re-read ambiguous cells and
      either corrects them (confidence raised, note appended) or confirms the
      row needs manual review.
    - Never silently accepts low-confidence data: without an LLM the row keeps
      needs_review=True and flows to the review queue.

The chat model is constructed lazily; tests inject a fake verifier directly.
"""

from app.core.config import settings
from app.services.extraction.normalize import NormalizedRow


def _build_model():  # pragma: no cover - requires API key
    from langchain_openai import ChatOpenAI  # noqa: PLC0415

    return ChatOpenAI(
        model=settings.llm_model,
        api_key=settings.llm_api_key,
        temperature=0,
    )


def _prompt(row: NormalizedRow) -> str:
    return (
        "You are verifying OCR output from a scanned employee leave sheet.\n"
        "Return ONLY compact JSON: {\"employee_code\": str|null, \"full_name\": str|null,"
        " \"official_email\": str|null, \"personal_email\": str|null}\n"
        "Use null for any field you cannot read with high confidence.\n"
        f"OCR values: {row.values}"
    )


def verify_row(row: NormalizedRow) -> NormalizedRow:
    if not row.needs_review or not settings.llm_api_key:
        return row  # stays flagged for manual review

    try:  # pragma: no cover - requires network + key
        model = _build_model()
        response = model.invoke(_prompt(row))
        import json  # noqa: PLC0415

        parsed = json.loads(response.content.strip().strip("`"))
    except Exception as exc:  # noqa: BLE001 — LLM failure must never crash pipeline
        row.review_note = f"{row.review_note or ''} | llm_verify_error: {str(exc)[:120]}"
        return row

    corrections = []
    for field_name in ("employee_code", "full_name", "official_email", "personal_email"):
        suggestion = parsed.get(field_name)
        current = row.values.get(field_name)
        if suggestion and str(suggestion).strip().lower() != str(current or "").strip().lower():
            corrections.append(f"{field_name}: '{current}' -> '{suggestion}'")
            row.values[field_name] = str(suggestion).strip()

    if corrections:
        row.needs_review = False
        row.confidence = max(row.confidence or 0.0, settings.low_confidence_threshold)
        row.review_note = f"llm_corrected: {'; '.join(corrections)}"[:400]
    else:
        row.review_note = f"{row.review_note or ''} | llm_confirmed_uncertain"
    return row


class FakeLlmVerifier:
    """Test double — corrects employee codes it recognizes."""

    def __init__(self, corrections: dict[str, str]):
        self.corrections = corrections

    def verify_row(self, row: NormalizedRow) -> NormalizedRow:
        code = row.employee_code
        if code in self.corrections:
            row.values["employee_code"] = self.corrections[code]
            row.needs_review = False
            row.review_note = "llm_corrected (fake)"
        return row
