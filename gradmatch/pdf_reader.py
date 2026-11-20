"""Isolated, time-bounded PDF worker; never execute active PDF content or perform OCR."""

import io
import json
import sys
from pypdf import PdfReader


def extract(raw):
    reader = PdfReader(io.BytesIO(raw), strict=True)
    if reader.is_encrypted or len(reader.pages) > 80:
        raise ValueError("Unsupported PDF")
    text = ""
    for page in reader.pages:
        contents = page.get_contents()
        if contents and len(contents.get_data()) > 12 * 1024 * 1024:
            raise ValueError("PDF stream limit")
        text += (page.extract_text() or "") + "\n"
        if len(text) >= 30000:
            break
    return text[:30000]


if __name__ == "__main__":
    try:
        raw = sys.stdin.buffer.read(10 * 1024 * 1024 + 1)
        if len(raw) > 10 * 1024 * 1024:
            raise ValueError("PDF size limit")
        print(json.dumps({"text": extract(raw)}))
    except Exception:
        sys.exit(2)
