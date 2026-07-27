"""Safe, in-memory text extraction for essay uploads."""
from __future__ import annotations

import io
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path
from xml.etree import ElementTree

from pypdf import PdfReader

MAX_UPLOAD_BYTES = 15 * 1024 * 1024
MAX_EXTRACTED_CHARS = 1_000_000
MAX_PDF_PAGES = 250
MAX_DOCX_MEMBERS = 1_000
MAX_DOCX_UNCOMPRESSED_BYTES = 60 * 1024 * 1024

PDF_SIGNATURE = b"%PDF-"
OLE_SIGNATURE = bytes.fromhex("D0CF11E0A1B11AE1")


class DocumentImportError(ValueError):
    pass


def _clean_text(text: str) -> str:
    text = text.replace("\x00", "").replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.rstrip() for line in text.splitlines()]
    text = "\n".join(lines).strip()
    if not text:
        raise DocumentImportError(
            "No selectable text was found. Scanned PDFs need OCR before they can be imported."
        )
    if len(text) > MAX_EXTRACTED_CHARS:
        raise DocumentImportError(
            f"The extracted document exceeds the {MAX_EXTRACTED_CHARS:,}-character limit."
        )
    return text


def _extract_pdf(data: bytes) -> str:
    if not data.startswith(PDF_SIGNATURE):
        raise DocumentImportError("The uploaded file is not a valid PDF.")
    try:
        reader = PdfReader(io.BytesIO(data), strict=False)
        if reader.is_encrypted and reader.decrypt("") == 0:
            raise DocumentImportError("Password-protected PDFs cannot be imported.")
        if len(reader.pages) > MAX_PDF_PAGES:
            raise DocumentImportError(
                f"PDFs are limited to {MAX_PDF_PAGES} pages."
            )
        return "\n\n".join(page.extract_text() or "" for page in reader.pages)
    except DocumentImportError:
        raise
    except Exception as exc:
        raise DocumentImportError("The PDF could not be read.") from exc


def _extract_docx(data: bytes) -> str:
    if not data.startswith(b"PK"):
        raise DocumentImportError("The uploaded file is not a valid DOCX document.")
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            members = archive.infolist()
            if len(members) > MAX_DOCX_MEMBERS:
                raise DocumentImportError("The DOCX archive contains too many files.")
            if any(member.flag_bits & 0x1 for member in members):
                raise DocumentImportError("Encrypted DOCX documents cannot be imported.")
            if sum(member.file_size for member in members) > MAX_DOCX_UNCOMPRESSED_BYTES:
                raise DocumentImportError("The expanded DOCX document is too large.")
            try:
                xml = archive.read("word/document.xml")
            except KeyError as exc:
                raise DocumentImportError("The DOCX document is missing its main text.") from exc
    except DocumentImportError:
        raise
    except (zipfile.BadZipFile, OSError) as exc:
        raise DocumentImportError("The DOCX document could not be read.") from exc

    try:
        root = ElementTree.fromstring(xml)
    except ElementTree.ParseError as exc:
        raise DocumentImportError("The DOCX document contains invalid XML.") from exc

    parts: list[str] = []

    def visit(element) -> None:
        tag = element.tag.rsplit("}", 1)[-1]
        if tag == "t" and element.text:
            parts.append(element.text)
        elif tag == "tab":
            parts.append("\t")
        elif tag in {"br", "cr"}:
            parts.append("\n")
        for child in element:
            visit(child)
        if tag == "p":
            parts.append("\n")
        elif tag == "tc":
            parts.append("\t")

    visit(root)
    return "".join(parts)


def _extract_doc(data: bytes) -> str:
    if not data.startswith(OLE_SIGNATURE):
        raise DocumentImportError("The uploaded file is not a valid legacy DOC document.")

    antiword = shutil.which("antiword")
    textutil = shutil.which("textutil")
    if antiword is None and textutil is None:
        raise DocumentImportError(
            "Legacy DOC import is unavailable on this server. Save the file as DOCX or PDF and try again."
        )

    with tempfile.TemporaryDirectory(prefix="proteus-doc-") as temp_dir:
        path = Path(temp_dir) / "upload.doc"
        path.write_bytes(data)
        command = (
            [antiword, str(path)]
            if antiword
            else [textutil, "-convert", "txt", "-stdout", str(path)]
        )
        with tempfile.TemporaryFile() as output:
            try:
                result = subprocess.run(
                    command,
                    cwd=temp_dir,
                    stdout=output,
                    stderr=subprocess.PIPE,
                    check=False,
                    timeout=20,
                )
            except (OSError, subprocess.TimeoutExpired) as exc:
                raise DocumentImportError("The legacy DOC document could not be converted.") from exc
            if result.returncode != 0:
                raise DocumentImportError("The legacy DOC document could not be converted.")
            output.seek(0)
            raw = output.read(MAX_EXTRACTED_CHARS * 4 + 1)
            if len(raw) > MAX_EXTRACTED_CHARS * 4:
                raise DocumentImportError("The converted DOC document is too large.")
            return raw.decode("utf-8", errors="replace")


def extract_document_text(filename: str, data: bytes) -> tuple[str, str]:
    """Return normalized text and the recognized format."""
    if not data:
        raise DocumentImportError("The uploaded document is empty.")
    if len(data) > MAX_UPLOAD_BYTES:
        raise DocumentImportError(
            f"Documents are limited to {MAX_UPLOAD_BYTES // (1024 * 1024)} MB."
        )

    suffix = Path(filename).suffix.lower()
    if suffix == ".pdf":
        text, file_type = _extract_pdf(data), "pdf"
    elif suffix == ".docx":
        text, file_type = _extract_docx(data), "docx"
    elif suffix == ".doc":
        text, file_type = _extract_doc(data), "doc"
    else:
        raise DocumentImportError("Choose a PDF, DOC, or DOCX document.")
    return _clean_text(text), file_type
