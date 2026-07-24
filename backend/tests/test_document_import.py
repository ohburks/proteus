import io
import subprocess
import zipfile

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from app.auth import CurrentUser, get_current_user
from app.document_import import (
    DocumentImportError,
    OLE_SIGNATURE,
    extract_document_text,
)
from app.main import app


def _docx_bytes(paragraphs: list[str]) -> bytes:
    body = "".join(
        f"<w:p><w:r><w:t>{paragraph}</w:t></w:r></w:p>"
        for paragraph in paragraphs
    )
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body>{body}</w:body></w:document>"
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("word/document.xml", xml)
    return buffer.getvalue()


def _pdf_bytes(text: str) -> bytes:
    writer = PdfWriter()
    page = writer.add_blank_page(width=612, height=792)
    font = DictionaryObject({
        NameObject("/Type"): NameObject("/Font"),
        NameObject("/Subtype"): NameObject("/Type1"),
        NameObject("/BaseFont"): NameObject("/Helvetica"),
    })
    page[NameObject("/Resources")] = DictionaryObject({
        NameObject("/Font"): DictionaryObject({
            NameObject("/F1"): writer._add_object(font),
        })
    })
    content = DecodedStreamObject()
    content.set_data(f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode())
    page[NameObject("/Contents")] = writer._add_object(content)
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def test_extract_docx_text_preserves_paragraphs():
    text, file_type = extract_document_text(
        "essay.docx",
        _docx_bytes(["First paragraph.", "Second paragraph."]),
    )
    assert file_type == "docx"
    assert text == "First paragraph.\nSecond paragraph."


def test_extract_pdf_text():
    text, file_type = extract_document_text(
        "essay.pdf",
        _pdf_bytes("Uploaded PDF essay text."),
    )
    assert file_type == "pdf"
    assert text == "Uploaded PDF essay text."


def test_file_content_must_match_extension():
    with pytest.raises(DocumentImportError, match="not a valid PDF"):
        extract_document_text("essay.pdf", b"This is plain text.")


def test_empty_extraction_has_scanned_pdf_guidance():
    with pytest.raises(DocumentImportError, match="No selectable text"):
        extract_document_text("essay.docx", _docx_bytes([]))


def test_legacy_doc_uses_bounded_converter(monkeypatch):
    monkeypatch.setattr("app.document_import.shutil.which", lambda name: f"/usr/bin/{name}")

    def run_converter(*args, **kwargs):
        kwargs["stdout"].write(b"Imported legacy essay.")
        return subprocess.CompletedProcess(args=["antiword"], returncode=0, stdout=None, stderr=b"")

    monkeypatch.setattr("app.document_import.subprocess.run", run_converter)

    text, file_type = extract_document_text("essay.doc", OLE_SIGNATURE + b"document")

    assert file_type == "doc"
    assert text == "Imported legacy essay."


def test_import_endpoint_returns_editable_text():
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        "instructor-user", "instructor", "instructor-id", "teacher"
    )
    try:
        response = TestClient(app).post(
            "/api/essays/import-text",
            files={
                "file": (
                    "essay.docx",
                    _docx_bytes(["Uploaded essay text."]),
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                )
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == {
        "text": "Uploaded essay text.",
        "filename": "essay.docx",
        "file_type": "docx",
        "character_count": 20,
    }
