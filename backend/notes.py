"""Handwritten notes & slide ingestion — two backends:

1. vision (default, OpenRouter): images/PDF pages go STRAIGHT to a vision
   LLM (STUDY_OPENROUTER_VISION_MODEL, default google/gemini-2.5-flash) —
   no OCR pass, the model reads the pixels. Handles handwriting, layout,
   diagrams-as-text, math.
2. ocr (fallback): Apple Vision VNRecognizeTextRequest — local, macOS only.
   Used when provider is local Ollama or the vision call fails.

Images: jpg/png/webp (heic converted via sips). PDFs: rasterized per page.
"""
import base64
import logging
import platform

logger = logging.getLogger(__name__)

NOTES_EXT = {".png", ".jpg", ".jpeg", ".webp", ".heic", ".pdf"}

OUTLINE_PROMPT = (
    "This is one page of a lesson slide deck (or handwritten notes). Read it and "
    "return a DETAILED OUTLINE fragment for that page — not a transcription. "
    "Rules: keep every factual detail (terms, definitions, processes, formulas, "
    "numbers, examples); condense everything else; organize as a hierarchical "
    "outline with the page's section title as heading and nested bullets "
    "(indent with two spaces per level); write definitions and lists out fully "
    "but never repeat slide decoration, headers/footers, or page numbers; "
    "include handwritten annotations only if they add lesson content; output "
    "plain text only — no commentary, no markdown code fences."
)


def read_notes(path: str) -> str:
    """Vision-first transcription of an image/PDF, OCR fallback."""
    from . import llm

    if llm.provider() == "openrouter":
        try:
            return vision_read(path)
        except Exception as e:  # noqa: BLE001
            logger.warning("vision notes failed (%s) — falling back to OCR", e)
    return ocr_file(path)


def vision_read(path: str) -> str:
    """Send image(s)/PDF pages directly to the vision LLM."""
    import os

    from . import llm

    model = os.environ.get("STUDY_OPENROUTER_VISION_MODEL",
                           "google/gemini-2.5-flash")
    images = vision_images(path)
    if not images:
        raise RuntimeError(f"no readable images in {path}")
    parts = []
    out = []
    for i, (mime, b64) in enumerate(images, 1):
        content = [
            {"type": "text", "text": (
                (f"Page {i} of {len(images)}. " if len(images) > 1 else "")
                + OUTLINE_PROMPT)},
            {"type": "image_url",
             "image_url": {"url": f"data:{mime};base64,{b64}"}},
        ]
        text = llm.chat(
            [{"role": "user", "content": content}],
            num_predict=4000, temperature=0.0, timeout=300,
            model_override=model,
        )
        if text.strip():
            out.append(text.strip())
    return "\n\n".join(out)


def vision_images(path: str) -> list[tuple[str, str]]:
    """[(mime, base64)] for an image file, or each PDF page as JPEG."""
    p = str(path).lower()
    if p.endswith(".pdf"):
        return _pdf_pages_jpeg(path)
    mime = {".png": "image/png", ".webp": "image/webp"}.get(
        _ext(path), "image/jpeg")
    src = path
    if _ext(path) == ".heic":
        src = _heic_to_jpeg(path)
        mime = "image/jpeg"
    with open(src, "rb") as f:
        return [(mime, base64.b64encode(f.read()).decode())]


def _ext(path: str) -> str:
    import os
    return os.path.splitext(str(path).lower())[1]


def _heic_to_jpeg(path: str) -> str:
    import subprocess
    import tempfile

    out = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False).name
    subprocess.run(["sips", "-s", "format", "jpeg", str(path),
                    "--out", out], check=True, capture_output=True)
    return out


def _pdf_pages_jpeg(path: str) -> list[tuple[str, str]]:
    import base64

    from Foundation import NSURL
    from Quartz import PDFDocument

    doc = PDFDocument.alloc().initWithURL_(
        NSURL.fileURLWithPath_(str(path)))
    if doc is None or doc.pageCount() == 0:
        raise RuntimeError(f"could not read PDF: {path}")
    from AppKit import NSBitmapImageRep, NSImage, NSSize, NSJPEGFileType
    pages = []
    for i in range(doc.pageCount()):
        page = doc.pageAtIndex_(i)
        # thumbnailOfSize_ is not exposed on PDFPage in all PyObjC builds;
        # thumbnailOfSize_forBox_ is the API that exists (10.13+)
        try:
            thumb = page.thumbnailOfSize_forBox_(NSSize(1600, 2000), 0)  # 0 = kPDFDisplayBoxMediaBox
        except AttributeError:
            thumb = page.thumbnailOfSize_(NSSize(1600, 2000))
        rep = NSBitmapImageRep.alloc().initWithData_(thumb.TIFFRepresentation())
        jpeg = rep.representationUsingType_properties_(NSJPEGFileType, {
            "NSImageCompressionFactor": 0.85})
        pages.append(("image/jpeg",
                      base64.b64encode(bytes(jpeg)).decode()))
    return pages


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
        try:
            thumb = page.thumbnailOfSize_forBox_(NSSize(1600, 2000), 0)
        except AttributeError:
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