"""
image_processor.py
------------------
OCR extraction from photos and scanned images.

Supports:
  - JPEG / PNG / WEBP photos sent via Telegram
  - Grayscale + contrast enhancement for better accuracy
  - English + Arabic language detection (eng+ara)
  - Graceful fallback if Arabic language data isn't installed

Dependencies:
  pip install pytesseract Pillow --break-system-packages

Tesseract binary must be installed on the system:
  Railway / Nixpacks → nixpacks.toml handles this automatically
  Local Ubuntu/Debian → sudo apt install tesseract-ocr tesseract-ocr-ara
  Local macOS        → brew install tesseract tesseract-lang
"""

import logging
import os

from PIL import Image, ImageEnhance, ImageFilter

logger = logging.getLogger(__name__)

# ─────────────────────────── Try importing pytesseract ────────────────────────

try:
    import pytesseract
    _TESSERACT_AVAILABLE = True
except ImportError:
    _TESSERACT_AVAILABLE = False
    logger.warning("pytesseract not installed — image OCR disabled")


# ─────────────────────────── Image preprocessing ──────────────────────────────

def _enhance(img: Image.Image) -> Image.Image:
    """Shared enhancement logic — grayscale, contrast boost, sharpen."""
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    img = img.convert("L")
    w, h = img.size
    if max(w, h) < 1500:
        scale = 1500 / max(w, h)
        img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
    img = ImageEnhance.Contrast(img).enhance(2.0)
    img = img.filter(ImageFilter.SHARPEN)
    return img


def _preprocess(image_path: str) -> Image.Image:
    """
    Convert image to high-contrast grayscale for best OCR results.
    Works well on phone photos of receipts and printed invoices.
    """
    img = Image.open(image_path)

    return _enhance(img)


# ─────────────────────────── OCR extraction ───────────────────────────────────

def extract_text_from_image(image_path: str) -> str:
    """
    Run Tesseract OCR on an image file and return the raw text.

    Returns empty string if Tesseract is not available or fails.
    Automatically tries Arabic+English first, falls back to English-only.
    """
    if not _TESSERACT_AVAILABLE:
        raise RuntimeError(
            "pytesseract is not installed. "
            "Run: pip install pytesseract Pillow --break-system-packages"
        )

    img = _preprocess(image_path)

    # Page segmentation mode 6 = assume a single uniform block of text.
    # Good for receipts and invoices.
    config = "--psm 6 --oem 3"

    # Try bilingual first (Arabic + English)
    try:
        text = pytesseract.image_to_string(img, lang="eng+ara", config=config)
        if text.strip():
            logger.info("OCR (eng+ara): extracted %d chars", len(text))
            return text
    except pytesseract.TesseractError as e:
        # Arabic language data not installed — fall back to English
        logger.warning("Arabic language data missing, falling back to eng: %s", e)

    # English-only fallback
    text = pytesseract.image_to_string(img, lang="eng", config=config)
    logger.info("OCR (eng): extracted %d chars", len(text))
    return text


def extract_text_from_pil_image(pil_img: Image.Image) -> str:
    """
    Run Tesseract OCR directly on a PIL Image object (no file needed).
    Used for scanned PDF pages rendered by pdfplumber.
    """
    if not _TESSERACT_AVAILABLE:
        raise RuntimeError("pytesseract is not installed.")

    img    = _enhance(pil_img)
    config = "--psm 6 --oem 3"

    try:
        text = pytesseract.image_to_string(img, lang="eng+ara", config=config)
        if text.strip():
            return text
    except pytesseract.TesseractError:
        pass

    return pytesseract.image_to_string(img, lang="eng", config=config)


def ocr_available() -> bool:
    """Returns True if Tesseract is installed and functional."""
    if not _TESSERACT_AVAILABLE:
        return False
    try:
        pytesseract.get_tesseract_version()
        return True
    except Exception:
        return False
