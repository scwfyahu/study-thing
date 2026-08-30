"""Handwritten notes OCR — macOS Apple Vision (VNRecognizeTextRequest).

Local, no cloud. Handles photos (jpg/png/webp/heic) and PDFs (rasterized per page).
Windows/Linux: not yet supported (raises a clear error).
"""
import platform

NOTES_EXT = {".png", ".jpg", ".jpeg", ".webp", ".heic", ".pdf"}


def ocr_file(path: str) -> str:
    if platform.system() != "Darwin":
        raise RuntimeError(
            "Handwritten-note OCR uses Apple Vision (macOS only). "
            "On Windows/Linux use audio recordings or plain-text notes for now."
        )
    if str(path).lower().endswith(".pdf"):
        return _ocr_pdf(path)
    return _ocr_image(path)


def _ocr_image(path: str) -> str:
    import Vision
    from Foundation import NSURL

    handler = Vision.VNImageRequestHandler.alloc().initWithURL_options_(
        NSURL.fileURLWithPath_(path), {}
    )
    return _run(handler)


def _ocr_pdf(path: str) -> str:
    import Vision
    from AppKit import NSBitmapImageRep, NSImage, NSSize
    from Quartz import PDFDocument

    doc = PDFDocument.alloc().initWithURL_(__import__("Foundation").NSURL.fileURLWithPath_(path))
    if doc is None or doc.pageCount() == 0:
        raise RuntimeError(f"could not read PDF: {path}")
    parts = []
    for i in range(doc.pageCount()):
        page = doc.pageAtIndex_(i)
        thumb = page.thumbnailOfSize_(NSSize(1600, 2000))
        rep = NSBitmapImageRep.alloc().initWithData_(thumb.TIFFRepresentation())
        handler = Vision.VNImageRequestHandler.alloc().initWithCGImage_options_(rep.CGImage(), {})
        parts.append(_run(handler))
    return "\n\n".join(parts)


def _run(handler) -> str:
    import Vision

    req = Vision.VNRecognizeTextRequest.alloc().init()
    req.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate)
    req.setUsesLanguageCorrection_(True)
    ok, err = handler.performRequests_error_([req], None)
    if not ok:
        raise RuntimeError(f"Vision OCR failed: {err}")
    rows = []
    for obs in (req.results() or []):
        cand = obs.topCandidates_(1)
        if not cand:
            continue
        box = obs.boundingBox()
        rows.append((round(box.origin.y, 2), box.origin.x, cand[0].string()))
    rows.sort(key=lambda r: (-r[0], r[1]))
    return "\n".join(r[2] for r in rows).strip()