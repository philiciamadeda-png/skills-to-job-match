"""
CV text extraction service.

Supports PDF (via pdfplumber) and DOCX (via python-docx).
File type is validated by magic bytes — not by extension.
Personal data (filenames, text content) is never written to logs.
"""
from __future__ import annotations

import io
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Magic byte signatures for supported types
_MAGIC = {
    b'%PDF': 'application/pdf',
    b'PK\x03\x04': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
}

SUPPORTED_MIME_TYPES = set(_MAGIC.values())
MAX_FILE_SIZE = 5 * 1024 * 1024   # 5 MB
MIN_TEXT_LENGTH = 50               # fewer chars → treat as scanned / image-based


@dataclass
class ExtractionResult:
    text: str
    mime_type: str
    is_scanned: bool = False
    error: str = ''

    @property
    def ok(self) -> bool:
        return not self.error and not self.is_scanned


def detect_mime(data: bytes) -> str | None:
    """Return MIME type from magic bytes, or None if unrecognised."""
    for magic, mime in _MAGIC.items():
        if data[:len(magic)] == magic:
            return mime
    return None


def extract_text(file_obj) -> ExtractionResult:
    """
    Extract plain text from a PDF or DOCX file-like object.

    - Reads at most MAX_FILE_SIZE bytes
    - Detects type by magic bytes
    - Returns ExtractionResult; never raises
    - Does NOT log file contents or filenames
    """
    try:
        data = file_obj.read(MAX_FILE_SIZE + 1)
    except Exception:
        logger.error('cv_extract: failed to read file object')
        return ExtractionResult(text='', mime_type='', error='Could not read file.')

    if len(data) > MAX_FILE_SIZE:
        return ExtractionResult(text='', mime_type='', error=f'File exceeds {MAX_FILE_SIZE // (1024*1024)} MB limit.')

    mime = detect_mime(data)
    if mime is None:
        return ExtractionResult(text='', mime_type='', error='Unsupported file type. Upload a PDF or DOCX.')

    try:
        if mime == 'application/pdf':
            text = _extract_pdf(data)
        else:
            text = _extract_docx(data)
    except Exception as exc:
        # Log the exception class only: parser messages and tracebacks can quote bytes from the file
        logger.error('cv_extract: extraction raised %s (mime=%s)', type(exc).__name__, mime)
        return ExtractionResult(text='', mime_type=mime, error='Text extraction failed. The file may be corrupt.')

    if len(text.strip()) < MIN_TEXT_LENGTH:
        return ExtractionResult(
            text='',
            mime_type=mime,
            is_scanned=True,
            error='No readable text found. This looks like a scanned or image-based PDF. '
                  'Please upload a text-based CV.',
        )

    return ExtractionResult(text=text, mime_type=mime)


def _extract_pdf(data: bytes) -> str:
    import pdfplumber
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        pages = [page.extract_text() or '' for page in pdf.pages]
    return '\n'.join(pages)


def _extract_docx(data: bytes) -> str:
    import docx
    doc = docx.Document(io.BytesIO(data))
    return '\n'.join(p.text for p in doc.paragraphs if p.text.strip())
