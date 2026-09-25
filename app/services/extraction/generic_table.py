"""OCR table reader for scanned non-GETS lists (employee repositories, leave registers).

Each data line is read positionally (words under the header label they line up with) and
semantically (IDs, e-mails and names recognised by shape); the stronger reading wins.
"""

from __future__ import annotations

import re

import cv2
import numpy as np

from app.services.extraction.normalize import FIELD_ALIASES, LEAVE_COLUMN_ALIASES, is_leave_column
from app.services.extraction.readers import RawTable

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+")
PUBLIC_MAIL = {"gmail", "yahoo", "outlook", "hotmail", "live", "icloud", "proton",
               "protonmail", "aol", "rediffmail", "zoho", "gmx", "mail", "yandex"}
TICK_RE = re.compile(r"^(\[?x\]?|✓|✔|☑|√|y|yes|true|done)$", re.IGNORECASE)

# canonical header name -> aliases (longest first when matching)
_ALIASES: list[tuple[str, str]] = sorted(
    [(canon, a) for canon, alts in FIELD_ALIASES.items() for a in alts if a != canon]
    + [(canon.replace("_", " "), a) for canon, alts in LEAVE_COLUMN_ALIASES.items() for a in alts],
    key=lambda kv: -len(kv[1]),
)


def _compact(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())



def _words(tok: dict) -> list[dict]:
    chars = tok.get("chars") or []
    if not chars:
        parts = tok["text"].split()
        n = max(1, len(tok["text"]))
        out, pos = [], 0
        for p in parts:
            start = tok["text"].index(p, pos)
            pos = start + len(p)
            x0 = tok["x0"] + (tok["x1"] - tok["x0"]) * start / n
            x1 = tok["x0"] + (tok["x1"] - tok["x0"]) * pos / n
            out.append({"text": p, "x0": x0, "x1": x1, "score": tok["score"]})
        return out
    words, cur = [], []
    for ch, cx in chars:
        if ch == " ":
            if cur:
                words.append(cur)
            cur = []
        else:
            cur.append((ch, cx))
    if cur:
        words.append(cur)
    out = []
    for w in words:
        half = max(2.0, (tok["y1"] - tok["y0"]) * 0.3)
        out.append({"text": "".join(c for c, _ in w), "x0": w[0][1] - half,
                    "x1": w[-1][1] + half, "score": tok["score"]})
    return out


def _lines(tokens: list[dict]) -> list[list[dict]]:
    if not tokens:
        return []
    heights = sorted(t["y1"] - t["y0"] for t in tokens)
    tol = max(6.0, 0.5 * heights[len(heights) // 2])
    lines: list[list[dict]] = []
    for tok in sorted(tokens, key=lambda t: t["yc"]):
        if lines and abs(tok["yc"] - np.mean([t["yc"] for t in lines[-1]])) <= tol:
            lines[-1].append(tok)
        else:
            lines.append([tok])
    for ln in lines:
        ln.sort(key=lambda t: t["x0"])
    return lines


def _header_columns(words: list[dict]) -> list[tuple[str, float, float]]:
    """Greedy multi-word label match over a candidate header line."""
    cols: list[tuple[str, float, float]] = []
    i = 0
    while i < len(words):
        matched = False
        for span in (4, 3, 2, 1):
            if i + span > len(words):
                continue
            seg = words[i:i + span]
            text = _compact("".join(w["text"] for w in seg))
            for canon, alias in _ALIASES:
                if text == _compact(alias):
                    cols.append((canon, seg[0]["x0"], seg[-1]["x1"]))
                    i += span
                    matched = True
                    break
            if matched:
                break
        if not matched:
            # unknown header words become their own (extra) column
            cols.append((words[i]["text"], words[i]["x0"], words[i]["x1"]))
            i += 1
    return cols


def _is_code(word: str) -> bool:
    from app.services.employee_service import validate_employee_code

    return bool(re.search(r"\d", word)) and validate_employee_code(word) and "@" not in word


def _classify_email(email: str) -> str:
    domain = email.split("@", 1)[1].split(".")[0].lower()
    return "personal_email" if domain in PUBLIC_MAIL else "official_email"


def _clean_line_text(text: str) -> str:
    # OCR likes to space out e-mails: 'bob.t @ gmail . com'
    text = re.sub(r"\s*@\s*", "@", text)
    return re.sub(r"(?<=[A-Za-z0-9])\s*\.\s*(?=(?:com|io|in|org|net|co)\b)", ".", text)


def _parse_line(words: list[dict], columns: list[tuple[str, float, float]]) -> dict[str, str]:
    """One data line → {column: value}, positional first, semantic repair."""
    values: dict[str, str] = {}
    if columns:
        starts = [c[1] for c in columns]
        bounds = [(starts[i] + starts[i + 1]) / 2 for i in range(len(starts) - 1)]
        for w in words:
            xc = w["x0"] + 0.25 * (w["x1"] - w["x0"])       # left-aligned cells
            idx = sum(1 for b in bounds if xc >= b)
            key = columns[idx][0]
            values[key] = f"{values.get(key, '')} {w['text']}".strip()

    text = _clean_line_text(" ".join(w["text"] for w in words))
    # 'S-404Dev' — an ID glued to the next word by a dropped space
    text = re.sub(r"\b([A-Za-z]{1,3}-?\d{2,})(?=[A-Z][a-z])", r"\1 ", text)
    emails = EMAIL_RE.findall(text)
    remainder = EMAIL_RE.sub(" ", text).split()
    code = next((t for t in remainder if _is_code(t)), "")

    semantic: dict[str, str] = {}
    if code:
        semantic["employee_code"] = code
    for e in emails:
        key = _classify_email(e)
        if key in semantic:
            key = "personal_email" if key == "official_email" else "official_email"
        semantic.setdefault(key, e.lower())
    name_words = []
    if code:
        after = remainder[remainder.index(code) + 1:]
        for t in after:
            if TICK_RE.match(t) or not re.search(r"[A-Za-z]", t):
                break
            name_words.append(t)
    if name_words:
        semantic["full_name"] = " ".join(name_words[:4])

    # positional values win only where they look right
    if not _is_code(values.get("employee_code", "")) and "employee_code" in semantic:
        values["employee_code"] = semantic["employee_code"]
    for key in ("official_email", "personal_email"):
        pos_val = _clean_line_text(values.get(key, ""))
        if not EMAIL_RE.fullmatch(pos_val or "-"):
            if key in semantic:
                values[key] = semantic[key]
            elif key in values:
                values[key] = ""
        else:
            values[key] = pos_val.lower()
    pos_name = values.get("full_name", "")
    sem_name = semantic.get("full_name", "")
    if sem_name and (not pos_name or EMAIL_RE.search(pos_name) or _is_code(pos_name.split()[0])
                     or (sem_name.startswith(pos_name) and len(sem_name) > len(pos_name))):
        values["full_name"] = semantic["full_name"]
    # an e-mail must never be filed under both columns
    same = values.get("official_email")
    if same and same == values.get("personal_email"):
        wrong = "personal_email" if _classify_email(same) == "official_email" else "official_email"
        values[wrong] = ""
    return values


def read_generic_table(rgb: np.ndarray, ocr) -> RawTable:
    tokens = ocr.detect(rgb)
    angles = [t["angle"] for t in tokens if t["x1"] - t["x0"] > 3 * (t["y1"] - t["y0"])]
    if angles:
        angle = float(np.median(angles))
        if 0.4 < abs(angle) < 15:
            h, w = rgb.shape[:2]
            m = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
            rgb = cv2.warpAffine(rgb, m, (w, h), flags=cv2.INTER_CUBIC,
                                 borderMode=cv2.BORDER_REPLICATE)
            tokens = ocr.detect(rgb)

    from app.services.extraction.gets_grid import _restore_spaces

    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    for tok in tokens:
        _restore_spaces(tok, gray)
    lines = _lines(tokens)
    header_idx, columns = None, []
    for i, ln in enumerate(lines[:6]):
        words = [w for t in ln for w in _words(t)]
        cols = _header_columns(words)
        known = [c for c in cols if c[0] in FIELD_ALIASES or is_leave_column(c[0])]
        if any(c[0] == "employee_code" for c in known) and (len(known) >= 2 or i == 0):
            header_idx, columns = i, cols
            break

    headers = [c[0] for c in columns] if columns else ["employee_code", "full_name",
                                                       "official_email", "personal_email"]
    for extra in ("employee_code", "full_name", "official_email", "personal_email"):
        if extra not in headers:
            headers.append(extra)

    rows, confidences = [], []
    body = lines[header_idx + 1:] if header_idx is not None else lines
    for ln in body:
        words = [w for t in ln for w in _words(t)]
        values = _parse_line(words, columns)
        if not any(v for v in values.values()):
            continue
        rows.append([values.get(h, "") for h in headers])
        confidences.append(min(t["score"] for t in ln))
    return RawTable(headers=headers, rows=rows, row_confidences=confidences)
