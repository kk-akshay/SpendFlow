def extract_pdf(path: str, password: str | None = None) -> Extracted:
    import pdfplumber

    try:
        pdf = pdfplumber.open(path, password=password or "")
    except Exception as exc:
        name = type(exc).__name__.lower()
        if "password" in name or "encrypt" in name or "password" in str(exc).lower():
            raise PasswordRequired() from exc
        raise UnreadableDocument(
            "This PDF could not be opened. It may be damaged."
        ) from exc

    out = Extracted()

    try:
        if len(pdf.pages) > 80:
            out.warnings.append(
                "This PDF has more than 80 pages; only the first 80 were read."
            )

        for page in pdf.pages[:80]:
            # Remove overlapping duplicate PDF characters.
            page = page.dedupe_chars(tolerance=1)

            words = [
                Word(
                    w["text"],
                    w["x0"],
                    w["x1"],
                    w["top"],
                    w["bottom"]
                )
                for w in page.extract_words(
                    x_tolerance=1.5,
                    y_tolerance=2,
                    keep_blank_chars=False
                )
            ]

            if len(words) >= 8:
                out.pages.append(
                    Page(words, float(page.width), float(page.height))
                )
                continue

            # Scanned PDF: use OCR.
            try:
                img = page.to_image(resolution=220).original
                ocr_words, w, h = _ocr_image(img)
                out.pages.append(Page(ocr_words, w, h, ocr=True))
            except Exception:
                out.pages.append(
                    Page(words, float(page.width), float(page.height))
                )
                out.warnings.append(
                    "A page had no readable text and OCR failed on it."
                )

    except PasswordRequired:
        raise
    except Exception as exc:
        raise UnreadableDocument(
            "This PDF could not be read."
        ) from exc
    finally:
        pdf.close()

    return out