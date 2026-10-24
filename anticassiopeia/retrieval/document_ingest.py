"""
Format-dispatching text extraction for uploaded documents.

One job: turn arbitrary uploaded bytes (a datasheet, a report, a paper)
into plain text that `chunking.py`/`bm25.py`/`extract.py` can treat the
same way they already treat `anticassiopeia/corpus/`'s hand-curated
excerpts. Deliberately separate from any one domain adapter — this is a
general utility, same reasoning `retrieval/` is its own package rather
than code embedded in one adapter (see docs/DESIGN.md §5).

Supported formats, decided 2026-10-25 (see the v2 master build prompt,
§0.6, in the project's own docs): `.txt/.md/.csv/.rpt/.svd/.xml` are
already plain text, read as-is; `.pdf` via `pypdf`'s page text
extraction; `.docx` via `python-docx`'s paragraph text. An unsupported
extension, or a file that extracts to nothing usable (e.g. a scanned
PDF with no text layer — pypdf reads embedded text layers only, no OCR
in this phase), raises a specific, named error rather than silently
returning an empty string a caller might mistake for "successfully
extracted, document is just empty."
"""

from __future__ import annotations

import io

_PLAIN_TEXT_EXTENSIONS = frozenset({".txt", ".md", ".csv", ".rpt", ".svd", ".xml"})
_PDF_EXTENSIONS = frozenset({".pdf"})
_DOCX_EXTENSIONS = frozenset({".docx"})
SUPPORTED_EXTENSIONS = _PLAIN_TEXT_EXTENSIONS | _PDF_EXTENSIONS | _DOCX_EXTENSIONS


class DocumentIngestError(Exception):
    """Raised when a file's extension isn't supported, or extraction
    produces no usable text — never silently swallowed into an empty
    string a caller might treat as a successfully-parsed-but-empty doc."""


def _extension_of(filename: str) -> str:
    idx = filename.rfind(".")
    return filename[idx:].lower() if idx != -1 else ""


def _extract_plain_text(raw_bytes: bytes, filename: str) -> str:
    try:
        return raw_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise DocumentIngestError(
            f"'{filename}' has extension suggesting plain text, but isn't valid UTF-8: {exc}"
        ) from exc


def _extract_pdf_text(raw_bytes: bytes, filename: str) -> str:
    try:
        import pypdf
    except ImportError as exc:  # pragma: no cover - dependency declared in pyproject
        raise DocumentIngestError(
            "PDF extraction requires the 'pypdf' package, which is not installed."
        ) from exc
    try:
        reader = pypdf.PdfReader(io.BytesIO(raw_bytes))
    except Exception as exc:  # noqa: BLE001 -- any malformed-PDF failure is an honest named gap
        raise DocumentIngestError(f"'{filename}' could not be read as a PDF: {exc}") from exc

    pages_text = []
    for page in reader.pages:
        try:
            pages_text.append(page.extract_text() or "")
        except Exception:  # noqa: BLE001 -- one bad page shouldn't fail the whole document
            pages_text.append("")
    text = "\n\n".join(t for t in pages_text if t.strip())
    if not text.strip():
        raise DocumentIngestError(
            f"'{filename}' is a valid PDF but no extractable text was found on any page "
            "(a scanned/image-only PDF has no embedded text layer -- OCR is not supported "
            "in this build; see the v2 master build prompt §0.6/§7)."
        )
    return text


def _extract_docx_text(raw_bytes: bytes, filename: str) -> str:
    try:
        import docx
    except ImportError as exc:  # pragma: no cover - dependency declared in pyproject
        raise DocumentIngestError(
            "DOCX extraction requires the 'python-docx' package, which is not installed."
        ) from exc
    try:
        document = docx.Document(io.BytesIO(raw_bytes))
    except Exception as exc:  # noqa: BLE001 -- any malformed-DOCX failure is an honest named gap
        raise DocumentIngestError(f"'{filename}' could not be read as a DOCX file: {exc}") from exc

    text = "\n".join(p.text for p in document.paragraphs if p.text.strip())
    if not text.strip():
        raise DocumentIngestError(f"'{filename}' is a valid DOCX file but contains no extractable text.")
    return text


def extract_text(raw_bytes: bytes, filename: str) -> str:
    """Returns plain text extracted from `raw_bytes`, dispatched on
    `filename`'s extension. Raises DocumentIngestError (never returns an
    empty/placeholder string) on an unsupported extension or on
    extraction that yields no usable text."""
    ext = _extension_of(filename)
    if ext in _PLAIN_TEXT_EXTENSIONS:
        text = _extract_plain_text(raw_bytes, filename)
        if not text.strip():
            raise DocumentIngestError(f"'{filename}' is empty.")
        return text
    if ext in _PDF_EXTENSIONS:
        return _extract_pdf_text(raw_bytes, filename)
    if ext in _DOCX_EXTENSIONS:
        return _extract_docx_text(raw_bytes, filename)
    raise DocumentIngestError(
        f"Unsupported file extension '{ext}' for '{filename}'. Supported: {sorted(SUPPORTED_EXTENSIONS)}."
    )
