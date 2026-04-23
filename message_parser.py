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
_SALES_RE = re.compile(r"\bsales?\b|\u0645\u0628\u064a\u0639\u0627\u062a|\u0628\u064a\u0639", re.IGNORECASE)


def is_sales_message(text: str) -> bool:
    """Return True if the text signals a sales record (not an expense)."""
    return bool(_SALES_RE.search(text))


# ─────────────────────────── Category keywords ────────────────────────────────

CATEGORIES = {
    "Vegetables": ["vegetable", "veggies", "veg", "tomato", "potato", "onion",
                   "carrot", "\u062e\u0636\u0627\u0631", "\u062e\u0636\u0631\u0648\u0627\u062a", "\u0628\u0637\u0627\u0637\u0627", "\u0628\u0646\u062f\u0648\u0631\u0629"],
    "Meat":       ["meat", "beef", "lamb", "chicken", "poultry", "turkey",
                   "\u0644\u062d\u0645", "\u062f\u062c\u0627\u062c", "\u062e\u0631\u0648\u0641", "\u0628\u0642\u0631"],
    "Dairy":      ["dairy", "milk", "cheese", "butter", "cream", "yogurt",
                   "\u062d\u0644\u064a\u0628", "\u062c\u0628\u0646", "\u0632\u0628\u062f\u0629"],
    "Seafood":    ["fish", "seafood", "shrimp", "salmon", "\u0633\u0645\u0643", "\u062c\u0645\u0628\u0631\u064a"],
    "Fruit":      ["fruit", "apple", "banana", "orange", "grape",
                   "\u0641\u0627\u0643\u0647\u0629", "\u062a\u0641\u0627\u062d", "\u0645\u0648\u0632", "\u0628\u0631\u062a\u0642\u0627\u0644"],
    "Bakery":     ["bread", "bakery", "pastry", "\u062e\u0628\u0632", "\u0645\u062e\u0628\u0632", "\u0645\u0639\u062c\u0646\u0627\u062a"],
    "Cleaning":   ["clean", "soap", "detergent", "hygiene", "\u062a\u0646\u0638\u064a\u0641", "\u0635\u0627\u0628\u0648\u0646"],
    "Packaging":  ["packaging", "box", "bag", "plastic", "wrap", "\u062a\u063a\u0644\u064a\u0641"],
    "Utilities":  ["electric", "water", "gas", "internet", "phone",
                   "\u0643\u0647\u0631\u0628\u0627\u0621", "\u0645\u0627\u0621", "\u063a\u0627\u0632", "\u0627\u0646\u062a\u0631\u0646\u062a"],
    "Rent":       ["rent", "lease", "\u0625\u064a\u062c\u0627\u0631"],
    "Groceries":  ["grocery", "supermarket", "market", "mall", "hypermarket",
                   "\u0628\u0642\u0627\u0644\u0629", "\u0633\u0648\u0628\u0631\u0645\u0627\u0631\u0643\u062a", "\u0647\u0627\u064a\u0628\u0631"],
    "Salary":     ["salary", "wage", "employee", "\u0631\u0627\u062a\u0628", "\u0623\u062c\u0631"],
    "Transport":  ["transport", "delivery", "fuel", "petrol", "\u0646\u0642\u0644", "\u062a\u0648\u0635\u064a\u0644", "\u0648\u0642\u0648\u062f"],
    "Equipment":  ["equipment", "tools", "machine", "repair", "\u0645\u0639\u062f\u0627\u062a", "\u0623\u062f\u0648\u0627\u062a"],
}

PAYMENT_METHODS = {
    "Cash":          ["cash", "\u0646\u0642\u062f", "\u0643\u0627\u0634"],
    "Card":          ["card", "visa", "mastercard", "\u0628\u0637\u0627\u0642\u0629"],
    "Bank Transfer": ["transfer", "wire", "bank", "\u062a\u062d\u0648\u064a\u0644"],
    "Cheque":        ["cheque", "check", "\u0634\u064a\u0643"],
}


# ─────────────────────────── Helpers ──────────────────────────────────────────

def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _extract_amount(text: str) -> Optional[float]:
    match = re.search(r"(\d[\d,]*(?:\.\d+)?)", text.replace(",", ""))
    return float(match.group(1).replace(",", "")) if match else None


def _extract_invoice_no(text: str) -> str:
    match = re.search(
        r"(?:invoice|inv|#|\u0641\u0627\u062a\u0648\u0631\u0629|receipt)\s*[#\-]?\s*(\w+)",
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
    # Try YYYY-MM-DD first (most precise)
    match = re.search(r"(\d{4})[\/\-\.](\d{1,2})[\/\-\.](\d{1,2})", text)
    if match:
        y, m, d = match.groups()
        try:
            return f"{y}-{int(m):02d}-{int(d):02d}"
        except Exception:
            pass
    # Fallback: DD/MM/YYYY
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
        # Strip the sales keyword before extracting name + amount
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

    # Strip lines with GPS coordinates (خط الطول / خط العرض) — they contain
    # decimal numbers that look like amounts but are lat/long values
    clean_text = "\n".join(
        line for line in ocr_text.splitlines()
        if not re.search(r"\u062e\u0637\s*(\u0627\u0644\u0637\u0648\u0644|\u0627\u0644\u0639\u0631\u0636)", line)
    )

    # Total amount: ordered from most specific to least specific
    total_patterns = [
        # Arabic: صافي القيمة / صافي المبلغ — most reliable on Arabic receipts
        r"\u0635\u0627\u0641\u064a\s*(?:\u0627\u0644\u0642\u064a\u0645\u0629|\u0627\u0644\u0645\u0628\u0644\u063a|\u0627\u0644\u0625\u062c\u0645\u0627\u0644\u064a)?\s*[:\-]?\s*(\d[\d,]*\.\d{2,3})",
        # Arabic: اجمالي المطلوب / الإجمالي المطلوب
        r"(?:\u0627\u062c\u0645\u0627\u0644\u064a|\u0627\u0644\u0625\u062c\u0645\u0627\u0644\u064a)\s*\u0627\u0644\u0645\u0637\u0644\u0648\u0628\s*[:\-]?\s*(\d[\d,]*\.\d{2,3})",
        # Arabic: المجموع / مجموع / الإجمالي
        r"(?:\u0627\u0644\u0645\u062c\u0645\u0648\u0639|\u0645\u062c\u0645\u0648\u0639|\u0627\u0644\u0625\u062c\u0645\u0627\u0644\u064a)\s*[:\-]?\s*(\d[\d,]*\.\d{2,3})",
        # English: grand total / amount due / net total / total due
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

    # Fallback: largest decimal number, skipping lines with quantities/coords/codes
    if total_amount is None:
        total_lines = []
        for line in clean_text.splitlines():
            if re.search(
                r"(?:\u0643\u0645\u064a\u0629|\u0627\u0644\u0643\u0645\u064a\u0629|\u062e\u0637|\u0631\u0645\u0632|\u0643\u0648\u062f|qty|quantity)",
                line, re.IGNORECASE
            ):
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

    description = f"Invoice \u2013 {supplier}" if supplier else "Invoice"

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
    Same total-extraction logic as parse_expenses_from_ocr.
    """
    receipt_date, inv_no, payment, customer, total_amount = _ocr_extract(ocr_text, source)

    if total_amount is None:
        return []

    description = f"Sale \u2013 {customer}" if customer else "Sale"

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
