"""Turn an uploaded PDF or image into positioned words.

Digital PDFs are read with pdfplumber. Scanned PDF pages and images go through Tesseract OCR.
Both paths produce the same Word/Page structure so the parsers don't care where text came from.
"""
from __future__ import annotations

from dataclasses import dataclass, field


class PasswordRequired(Exception):
    """The PDF is encrypted and the password is missing or wrong."""


class UnreadableDocument(Exception):
    """The file could not be opened or read."""


@dataclass
class Word:
    text: str
    x0: float
    x1: float
    top: float
    bottom: float


@dataclass
class Page:
    words: list[Word]
    width: float
    height: float
    ocr: bool = False


@dataclass
class Extracted:
    pages: list[Page] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ocr_used(self) -> bool:
        return any(p.ocr for p in self.pages)


def sniff_kind(head: bytes) -> str | None:
    """Identify the real file type from its first bytes (never trust the extension)."""
    if head.startswith(b"%PDF"):
        return "pdf"
    if head.startswith(b"\x89PNG"):
        return "png"
    if head[:3] == b"\xff\xd8\xff":
        return "jpeg"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "webp"
    return None


def _ocr_image(img) -> tuple[list[Word], float, float]:
    import pytesseract
    from PIL import Image, ImageOps

    img = ImageOps.exif_transpose(img).convert("L")
    if img.width > 4000:
        ratio = 4000 / img.width
        img = img.resize((4000, int(img.height * ratio)), Image.LANCZOS)
    elif img.width < 2400:
        ratio = min(3.0, 2400 / img.width)
        img = img.resize((int(img.width * ratio), int(img.height * ratio)), Image.LANCZOS)
    img = ImageOps.autocontrast(img)
    data = pytesseract.image_to_data(img, config="--psm 6", output_type=pytesseract.Output.DICT)
    words: list[Word] = []
    for i, text in enumerate(data["text"]):
        text = (text or "").strip()
        if not text:
            continue
        try:
            conf = float(data["conf"][i])
        except (TypeError, ValueError):
            conf = -1
        if conf < 20:
            continue
        x, y, w, h = data["left"][i], data["top"][i], data["width"][i], data["height"][i]
        words.append(Word(text, x, x + w, y, y + h))
    return words, float(img.width), float(img.height)


def extract_pdf(path: str, password: str | None = None) -> Extracted:
    import pdfplumber

    try:
        pdf = pdfplumber.open(path, password=password or "")
    except Exception as exc:  # pdfminer raises several encryption-related types
        name = type(exc).__name__.lower()
        if "password" in name or "encrypt" in name or "password" in str(exc).lower():
            raise PasswordRequired() from exc
        raise UnreadableDocument("This PDF could not be opened. It may be damaged.") from exc

    out = Extracted()
    try:
        if len(pdf.pages) > 80:
            out.warnings.append("This PDF has more than 80 pages; only the first 80 were read.")
        for page in pdf.pages[:80]:
            words = [
                Word(w["text"], w["x0"], w["x1"], w["top"], w["bottom"])
                for w in page.extract_words(x_tolerance=1.5, y_tolerance=2, keep_blank_chars=False)
            ]
            if len(words) >= 8:
                out.pages.append(Page(words, float(page.width), float(page.height)))
                continue
            # Little or no text layer: probably a scan. Rasterise and OCR.
            try:
                img = page.to_image(resolution=220).original
                ocr_words, w, h = _ocr_image(img)
                out.pages.append(Page(ocr_words, w, h, ocr=True))
            except Exception:
                out.pages.append(Page(words, float(page.width), float(page.height)))
                out.warnings.append("A page had no readable text and OCR failed on it.")
    except PasswordRequired:
        raise
    except Exception as exc:
        raise UnreadableDocument("This PDF could not be read.") from exc
    finally:
        pdf.close()
    return out


def extract_image(path: str) -> Extracted:
    from PIL import Image, UnidentifiedImageError

    try:
        img = Image.open(path)
        img.load()
    except (UnidentifiedImageError, OSError) as exc:
        raise UnreadableDocument("This image could not be opened.") from exc
    words, w, h = _ocr_image(img)
    out = Extracted(pages=[Page(words, w, h, ocr=True)])
    if len(words) < 8:
        out.warnings.append("Very little text was found in this image. Try a sharper, straight-on screenshot or the PDF.")
    return out


def extract_document(path: str, kind: str, password: str | None = None) -> Extracted:
    ex = extract_pdf(path, password) if kind == "pdf" else extract_image(path)
    if ex.ocr_used:
        ex.warnings.append("Text was read with OCR. Please double-check dates and amounts before confirming.")
    return ex
