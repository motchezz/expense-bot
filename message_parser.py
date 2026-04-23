"""
message_parser.py
-----------------
Parses text messages and OCR output into expense or sales records.

Text formats supported
----------------------
Simple:
  vegetables 150
  electricity bill 450

With supplier/customer:
  vegetables | Hassan Market | 250
  meat | Al Baraka | 500 | Invoice #12

Sales (keyword triggers routing to the Sales sheet):
  sales chicken 500
  مبيعات لحم | Hassan Market | 300

PDF/photo invoices are processed via parse_expenses_from_ocr() or
parse_sales_from_ocr().
"""

import re
from datetime import datetime
from dataclasses import dataclass
from typing import Optional


# ─────────────────────────── Data classes ─────────────────────────────────────

@dataclass
class ExpenseRecord:
    date: str
    name: str
    category: str
    supplier: str
    amount: float
    invoice_no: str
    payment_method: str
    notes: str

    def to_row(self) -> list:
        return [
            self.date,
            self.name,
            self.category,
            self.supplier,
            self.amount,
            self.invoice_no,
            self.payment_method,
            self.notes,
        ]

    @staticmethod
    def headers() -> list:
        return [
            "#", "Date", "Item / Description", "Category",
            "Supplier", "Amount", "Invoice #", "Payment Method", "Notes",
        ]


@dataclass
class SalesRecord:
    date: str
    name: str
    category: str
    customer: str
    amount: float
    invoice_no: str
    payment_method: str
    notes: str

    def to_row(self) -> list:
        return [
            self.date,
            self.name,
            self.category,
            self.customer,
            self.amount,
            self.invoice_no,
            self.payment_method,
            self.notes,
        ]

    @staticmethod
    def headers() -> list:
        return [
            "#", "Date", "Item / Description", "Category",
            "Customer", "Amount", "Invoice #", "Payment Method", "Notes",
        ]


# ─────────────────────────── Sales detection ──────────────────────────────────

# Matches "sales", "sale", Arabic "مبيعات" (sales), or "بيع" (sale/selling)
_SALES_RE = re.compile(r"\bsales?\b|مبيعات|بيع", re.IGNORECASE)


def is_sales_message(text: str) -> bool:
    """Return True if the text signals a sales record (not an expense)."""
    return bool(_SALES_RE.search(text))


# ─────────────────────────── Category keywords ────────────────────────────────

CATEGORIES = {
    "Vegetables": ["vegetable", "veggies", "veg", "tomato", "potato", "onion",
                   "carrot", "خضار", "خضروات", "بطاطا", "بندورة"],
    "Meat":       ["meat", "beef", "lamb", "chicken", "poultry", "turkey",
                   "لحم", "دجاج", "خروف", "بقر"],
    "Dairy":      ["dairy", "milk", "cheese", "butter", "cream", "yogurt",
                   "حليب", "جبن", "زبدة"],
    "Seafood":    ["fish", "seafood", "shrimp", "salmon", "سمك", "جمبري"],
    "Fruit":      ["fruit", "apple", "banana", "orange", "grape",
                   "فاكهة", "تفاح", "موز", "برتقال"],
    "Bakery":     ["bread", "bakery", "pastry", "خبز", "مخبز", "معجنات"],
    "Cleaning":   ["clean", "soap", "detergent", "hygiene", "تنظيف", "صابون"],
    "Packaging":  ["packaging", "box", "bag", "plastic", "wrap", "تغليف"],
    "Utilities":  ["electric", "water", "gas", "internet", "phone",
                   "كهرباء", "ماء", "غاز", "انترنت"],
    "Rent":       ["rent", "lease", "إيجار"],
    "Groceries":  ["grocery", "supermarket", "market", "mall", "hypermarket",
                   "بقالة", "سوبرماركت", "هايبر"],
    "Salary":     ["salary", "wage", "employee", "راتب", "أجر"],
    "Transport":  ["transport", "delivery", "fuel", "petrol", "نقل", "توصيل", "وقود"],
    "Equipment":  ["equipment", "tools", "machine", "repair", "معدات", "أدوات"],
}

PAYMENT_METHODS = {
    "Cash":          ["cash", "نقد", "كاش"],
    "Card":          ["card", "visa", "mastercard", "بطاقة"],
    "Bank Transfer": ["transfer", "wire", "bank", "تحويل"],
    "Cheque":        ["cheque", "check", "شيك"],
}


# ─────────────────────────── Helpers ──────────────────────────────────────────

def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _extract_amount(text: str) -> Optional[float]:
    match = re.search(r"(\d[\d,]*(?:\.\d+)?)", text.replace(",", ""))
    return float(match.group(1).replace(",", "")) if match else None


def _extract_invoice_no(text: str) -> str:
    match = re.search(
        r"(?:invoice|inv|#|فاتورة|receipt)\s*[#\-]?\s*(\w+)",
        text, re.IGNORECASE
    )
    return f"#{match.group(1)}" if match else ""


def _detect_category(text: str) -> str:
    lower = text.lower()
    for category, keywords in CATEGORIES.items():
        for kw in keywords:
            if kw in lower:
                return category
    return "General"


def _detect_payment(text: str) -> str:
    lower = text.lower()
    for method, keywords in PAYMENT_METHODS.items():
        for kw in keywords:
            if kw in lower:
                return method
    return "Cash"


def _parse_date(text: str) -> str:
    match = re.search(r"(\d{1,2})[\/\-\.](\d{1,2})[\/\-\.](\d{2,4})", text)
    if match:
        d, m, y = match.groups()
        y = f"20{y}" if len(y) == 2 else y
        try:
            return f"{y}-{int(m):02d}-{int(d):02d}"
        except Exception:
            pass
    return _today()


# ─────────────────────────── Text message parsers ─────────────────────────────

def parse_expense(text: str) -> Optional[ExpenseRecord]:
    """Parse a Telegram text message into an ExpenseRecord."""
    text = text.strip()
    if not text or text.startswith("/"):
        return None

    parts = [p.strip() for p in re.split(r"\s*\|\s*", text)]

    if len(parts) >= 2:
        name     = parts[0]
        supplier = parts[1]
        amount   = _extract_amount(parts[2]) if len(parts) > 2 else _extract_amount(text)
        inv_no   = _extract_invoice_no(parts[3] if len(parts) > 3 else text)
        notes    = parts[4] if len(parts) > 4 else ""
    else:
        amount   = _extract_amount(text)
        name     = re.sub(r"\d[\d,]*(?:\.\d+)?", "", text).strip(" ,-|") or text[:80]
        supplier = ""
        inv_no   = _extract_invoice_no(text)
        notes    = ""

    return ExpenseRecord(
        date=_today(),
        name=name[:80],
        category=_detect_category(name + " " + notes),
        supplier=supplier,
        amount=amount or 0.0,
        invoice_no=inv_no,
        payment_method=_detect_payment(text),
        notes=notes,
    )


def parse_sale(text: str) -> Optional[SalesRecord]:
    """
    Parse a Telegram text message into a SalesRecord.

    Pipe format:   item | customer | amount | invoice | notes
    Free-form:     sales chicken 500  /  مبيعات لحم 300
    """
    text = text.strip()
    if not text or text.startswith("/"):
        return None

    parts = [p.strip() for p in re.split(r"\s*\|\s*", text)]

    if len(parts) >= 2:
        name     = parts[0]
        customer = parts[1]
        amount   = _extract_amount(parts[2]) if len(parts) > 2 else _extract_amount(text)
        inv_no   = _extract_invoice_no(parts[3] if len(parts) > 3 else text)
        notes    = parts[4] if len(parts) > 4 else ""
    else:
        # Strip the "sales / مبيعات" keyword before extracting name + amount
        clean  = _SALES_RE.sub("", text).strip()
        amount = _extract_amount(clean)
        name   = re.sub(r"\d[\d,]*(?:\.\d+)?", "", clean).strip(" ,-|") or clean[:80]
        customer, inv_no, notes = "", _extract_invoice_no(text), ""

    return SalesRecord(
        date=_today(),
        name=name[:80],
        category=_detect_category(name + " " + notes),
        customer=customer,
        amount=amount or 0.0,
        invoice_no=inv_no,
        payment_method=_detect_payment(text),
        notes=notes,
    )


# ─────────────────────────── PDF / OCR parsers ────────────────────────────────

def _ocr_extract(ocr_text: str, source: str):
    """
    Shared OCR extraction logic.
    Returns (receipt_date, inv_no, payment, name_hint, total_amount).
    """
    lines = [l.strip() for l in ocr_text.splitlines() if l.strip()]

    receipt_date = _parse_date(ocr_text)
    inv_no       = _extract_invoice_no(ocr_text)
    payment      = _detect_payment(ocr_text)

    # Name hint: first readable line near the top (store / customer name)
    name_hint = ""
    for line in lines[:8]:
        cleaned = re.sub(r"[^\w\s\u0600-\u06FF]", " ", line).strip()
        if re.search(r"[a-zA-Z\u0600-\u06FF]{3,}", cleaned):
            if not re.search(r"slip|trans|staff|sales.?tax|vat|#\d{4,}", cleaned, re.IGNORECASE):
                name_hint = cleaned[:60]
                break

    # Strip lines that contain GPS coordinates (خط الطول / خط العرض)
    # These look like decimal numbers but are lat/long, not amounts
    clean_text = "\n".join(
        line for line in ocr_text.splitlines()
        if not re.search(r"خط\s*(الطول|العرض)", line)
    )

    # Total amount: ordered from most specific to least specific
    total_patterns = [
        # Arabic: صافي القيمة / صافي المبلغ  (net value — most reliable on Arabic receipts)
        r"صافي\s*(?:القيمة|المبلغ|الإجمالي)?\s*[:\-]?\s*(\d[\d,]*\.\d{2,3})",
        # Arabic: اجمالي المطلوب / الإجمالي المطلوب
        r"(?:اجمالي|الإجمالي)\s*المطلوب\s*[:\-]?\s*(\d[\d,]*\.\d{2,3})",
        # Arabic: المجموع / مجموع / الإجمالي
        r"(?:المجموع|مجموع|الإجمالي)\s*[:\-]?\s*(\d[\d,]*\.\d{2,3})",
        # English: total / grand total / amount due / net total
        r"(?:^|\b)(?:grand\s*total|amount\s*due|net\s*total|total\s*due)\s*[:\-]?\s*(\d[\d,]*\.\d{2,3})",
        r"(?:^|\b)total\s*(?:jd|kd|aed|sar|egp|usd|eur)?\s*[:\-]?\s*(\d[\d,]*\.\d{2,3})",
        r"total[^\d]{0,20}(\d[\d,]*\.\d{2,3})",
    ]
    total_amount = None
    for pattern in total_patterns:
        match = re.search(pattern, clean_text, re.IGNORECASE | re.MULTILINE)
        if match:
            candidate = float(match.group(1).replace(",", ""))
            if 0 < candidate < 100_000:
                total_amount = candidate
                break

    # Fallback: largest decimal number on lines that look like totals
    # (lines containing total-like keywords, not coordinates or quantities)
    if total_amount is None:
        total_lines = []
        for line in clean_text.splitlines():
            # skip lines that are clearly quantities, coords, or item codes
            if re.search(r"(?:كمية|الكمية|خط|رمز|كود|qty|quantity)", line, re.IGNORECASE):
                continue
            nums = re.findall(r"\b(\d{1,6}\.\d{2,3})\b", line)
            total_lines.extend(nums)
        candidates = [float(a) for a in total_lines if 0 < float(a) < 100_000]
        if candidates:
            total_amount = max(candidates)

    return receipt_date, inv_no, payment, name_hint, total_amount


def parse_expenses_from_ocr(ocr_text: str, source: str = "PDF") -> list[ExpenseRecord]:
    """
    Extract ONE ExpenseRecord from a receipt / invoice.

    One clean record per receipt — we extract only the total, not line items.
    """
    receipt_date, inv_no, payment, supplier, total_amount = _ocr_extract(ocr_text, source)

    if total_amount is None:
        return []

    description = f"Invoice – {supplier}" if supplier else "Invoice"

    return [ExpenseRecord(
        date=receipt_date,
        name=description[:80],
        category=_detect_category(supplier + " " + ocr_text[:150]),
        supplier=supplier,
        amount=total_amount,
        invoice_no=inv_no,
        payment_method=payment,
        notes=f"From {source}",
    )]


def parse_sales_from_ocr(ocr_text: str, source: str = "PDF") -> list[SalesRecord]:
    """
    Extract ONE SalesRecord from a sales receipt / invoice.

    Same total-extraction logic as parse_expenses_from_ocr, but the result
    goes to the Sales sheet.
    """
    receipt_date, inv_no, payment, customer, total_amount = _ocr_extract(ocr_text, source)

    if total_amount is None:
        return []

    description = f"Sale – {customer}" if customer else "Sale"

    return [SalesRecord(
        date=receipt_date,
        name=description[:80],
        category=_detect_category(customer + " " + ocr_text[:150]),
        customer=customer,
        amount=total_amount,
        invoice_no=inv_no,
        payment_method=payment,
        notes=f"From {source}",
    )]
