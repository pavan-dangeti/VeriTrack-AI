"""LLM re-reading of low-confidence OCR fields (LangChain).

Without a configured model rows keep needs_review=True: low-confidence data is never silently
accepted. The chat model is built lazily; tests inject a fake verifier.
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
