from io import BytesIO

import pytest

from backend.core import document_ingestion


def test_extract_plain_text():
    result = document_ingestion.extract_bytes("notes.txt", b"Acme interview is Friday.")

    assert result.success is True
    assert "Acme interview" in result.text
    assert result.parts[0].kind == "text"


def test_extract_csv_as_markdown_table():
    result = document_ingestion.extract_bytes("jobs.csv", b"company,role\nAcme,QA\nBeta,SQA\n")

    assert result.success is True
    assert "| company | role |" in result.text
    assert "| Acme | QA |" in result.text


def test_extract_json_pretty_prints():
    result = document_ingestion.extract_bytes("data.json", b'{"company":"Acme","status":"viewed"}')

    assert result.success is True
    assert '"company": "Acme"' in result.text


def test_extract_xlsx_preserves_sheet_name():
    openpyxl = pytest.importorskip("openpyxl")
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "Applications"
    sheet.append(["company", "status"])
    sheet.append(["Acme", "viewed"])
    buffer = BytesIO()
    workbook.save(buffer)

    result = document_ingestion.extract_bytes("jobs.xlsx", buffer.getvalue())

    assert result.success is True
    assert "sheet=Applications" in result.text
    assert "| company | status |" in result.text


def test_capabilities_shape():
    caps = document_ingestion.capabilities()

    assert ".pdf" in caps["supported_extensions"]
    assert "pdfplumber" in caps["packages"]
    assert "ocr_ready" in caps
