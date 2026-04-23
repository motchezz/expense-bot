"""
bot.py — Single-user Expense & Sales Tracker Bot
--------------------------------------------------
No authentication, no database lookups, no link codes.
Credentials come from .env / environment variables.

.env required:
  TELEGRAM_BOT_TOKEN=...
  GOOGLE_CREDENTIALS_PATH=credentials.json   (or GOOGLE_CREDENTIALS_JSON=base64...)
  SPREADSHEET_ID=...

Routing:
  "sales" or "مبيعات" in message/caption  →  "2026 Sales April"
  everything else                          →  "2026 Expenses April"
"""

import asyncio
import logging
import os
import re
import tempfile

import pdfplumber
from dotenv import load_dotenv
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from image_processor import extract_text_from_image, extract_text_from_pil_image, ocr_available
from message_parser import (
    is_sales_message,
    parse_expense,
    parse_expenses_from_ocr,
    parse_sale,
    parse_sales_from_ocr,
)
from sheets_manager import SheetsManager

# ─────────────────────────── Setup ────────────────────────────────────────────

load_dotenv()

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


def _sheets() -> SheetsManager:
    """Build SheetsManager from env vars (no user lookup needed)."""
    return SheetsManager()


# ─────────────────────────── Message formatters ───────────────────────────────

def _fmt_expense(record, result: dict) -> str:
    return (
        "✅ *Expense saved!*\n\n"
        f"📅 `{record.date}`\n"
        f"🛒 *{record.name}*\n"
        f"📦 Category: `{record.category}`\n"
        f"🏪 Supplier: `{record.supplier or '—'}`\n"
        f"💵 Amount: `{record.amount:,.3f}`\n"
        f"📋 Sheet: `{result['tab']}` · Row #{result['row']}\n"
        f"[Open spreadsheet]({result['url']})"
    )


def _fmt_sale(record, result: dict) -> str:
    return (
        "💰 *Sale saved!*\n\n"
        f"📅 `{record.date}`\n"
        f"🏷 *{record.name}*\n"
        f"📦 Category: `{record.category}`\n"
        f"👤 Customer: `{record.customer or '—'}`\n"
        f"💵 Amount: `{record.amount:,.3f}`\n"
        f"📋 Sheet: `{result['tab']}` · Row #{result['row']}\n"
        f"[Open spreadsheet]({result['url']})"
    )


def _fmt_bulk(result: dict, records: list, source: str, is_sales: bool = False) -> str:
    icon  = "💰" if is_sales else "✅"
    label = "sales" if is_sales else "expenses"
    lines   = [f"  • {r.name[:30]} — `{r.amount:,.3f}`" for r in records]
    preview = "\n".join(lines[:15])
    if len(records) > 15:
        preview += f"\n  … and {len(records) - 15} more"
    return (
        f"{icon} *{result['count']} {label} saved from {source}!*\n\n"
        f"{preview}\n\n"
        f"📋 Sheet: `{result['tab']}`\n"
        f"[Open spreadsheet]({result['url']})"
    )


HELP_TEXT = """
📖 *How to record expenses & sales:*

*Expense — simple text:*
`vegetables 150`
`electricity bill 450`

*Expense — with supplier:*
`meat | Hassan Market | 300`
`vegetables | Al Baraka | 250 | Invoice #12`

*Sale — add "sales" or "مبيعات":*
`sales chicken 500`
`مبيعات لحم | Customer Name | 300`

*📸 Photo of a receipt:*
Send any photo — total extracted automatically.
Add "sales" in the caption to route to the Sales sheet.

*📄 PDF invoices:*
Upload a PDF — even 40+ invoices at once.
Add "sales" in the caption to route to the Sales sheet.

*Commands:*
/summary — this month's expenses + sales
/summary April 2026 — specific month
/sheet — open your spreadsheet
/help — this guide
"""

WELCOME_TEXT = (
    "👋 *Welcome to your Expense & Sales Tracker!*\n\n"
    "Send me an expense or sale and I'll save it to your Google Sheet.\n\n"
    + HELP_TEXT
)


# ─────────────────────────── PDF helpers ──────────────────────────────────────

def _extract_pdf_pages(pdf_path: str) -> list[str]:
    pages = []
    with pdfplumber.open(pdf_path) as pdf:
        total = len(pdf.pages)
        logger.info("PDF has %d pages", total)
        for i, page in enumerate(pdf.pages):
            text = page.extract_text() or ""
            for table in page.extract_tables():
                for row in table:
                    if row:
                        text += "\n" + " | ".join(str(c) for c in row if c)
            if text.strip():
                pages.append(text)
                continue
            if ocr_available():
                try:
                    pil_img  = page.to_image(resolution=200).original
                    ocr_text = extract_text_from_pil_image(pil_img)
                    if ocr_text.strip():
                        pages.append(ocr_text)
                except Exception as e:
                    logger.warning("Page %d/%d OCR failed: %s", i + 1, total, e)
    return pages


_TOTAL_RE = re.compile(
    r"(?:^|\b)"
    r"(?:total|grand\s*total|amount\s*due|net\s*total|مجموع|الإجمالي|المجموع)"
    r"\s*(?:jd|kd|aed|sar|egp|usd|eur)?\s*[:\-]?\s*\d",
    re.IGNORECASE | re.MULTILINE,
)


def _invoice_number(text: str) -> str:
    m = re.search(
        r"(?:invoice|inv|slip|trans|receipt|فاتورة)\s*[#:\-]?\s*(\w{4,})",
        text, re.IGNORECASE,
    )
    return m.group(1).lower() if m else ""


def _group_invoices(pages: list[str]) -> list[str]:
    if not pages:
        return []
    groups, current = [], [pages[0]]
    for page in pages[1:]:
        last            = current[-1]
        group_has_total = bool(_TOTAL_RE.search(last))
        same_inv        = _invoice_number(page) and _invoice_number(page) == _invoice_number(current[0])
        if same_inv or not group_has_total:
            current.append(page)
        else:
            groups.append(current)
            current = [page]
    groups.append(current)
    merged = ["\n\n".join(g) for g in groups]
    logger.info("Invoice grouping: %d pages → %d invoices", len(pages), len(merged))
    return merged


# ─────────────────────────── Command handlers ─────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(WELCOME_TEXT, parse_mode=ParseMode.MARKDOWN)


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(HELP_TEXT, parse_mode=ParseMode.MARKDOWN)


async def cmd_sheet(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        url = _sheets().url
        await update.message.reply_text(
            f"📊 [Open your spreadsheet]({url})",
            parse_mode=ParseMode.MARKDOWN,
        )
    except Exception as e:
        await update.message.reply_text(f"⚠️ Could not connect to sheet: `{e}`",
                                        parse_mode=ParseMode.MARKDOWN)


async def cmd_summary(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    month_arg = " ".join(context.args).strip() if context.args else None
    try:
        s = _sheets().get_monthly_summary(month_arg)
        await update.message.reply_text(
            f"📊 *{s['month']} Summary*\n\n"
            f"💸 *Expenses*\n"
            f"   Total: `{s['exp_total']:,.3f}`  ·  Entries: `{s['exp_count']}`\n"
            f"   Tab: `{s['exp_tab']}`\n\n"
            f"💰 *Sales*\n"
            f"   Total: `{s['sale_total']:,.3f}`  ·  Entries: `{s['sale_count']}`\n"
            f"   Tab: `{s['sale_tab']}`",
            parse_mode=ParseMode.MARKDOWN,
        )
    except Exception as e:
        logger.error("Summary error: %s", e)
        await update.message.reply_text("⚠️ Could not fetch summary.")


# ─────────────────────────── Text handler ─────────────────────────────────────

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text     = update.message.text or ""
    is_sales = is_sales_message(text)

    if is_sales:
        record = parse_sale(text)
        if not record or record.amount == 0.0:
            await update.message.reply_text(
                "❓ Couldn't read that sale.\n\n"
                "Try: `sales chicken 500`\n"
                "or:  `مبيعات لحم | Customer | 300`\n\n"
                "/help for more examples.",
                parse_mode=ParseMode.MARKDOWN,
            )
            return
        try:
            result = _sheets().add_sale(record)
            await update.message.reply_text(
                _fmt_sale(record, result), parse_mode=ParseMode.MARKDOWN
            )
        except Exception as e:
            logger.error("Sheets sale error: %s", e)
            await update.message.reply_text(f"⚠️ Could not save: `{e}`",
                                            parse_mode=ParseMode.MARKDOWN)
    else:
        record = parse_expense(text)
        if not record or record.amount == 0.0:
            await update.message.reply_text(
                "❓ Couldn't read that expense.\n\n"
                "Try: `vegetables 150`\n"
                "or:  `meat | Hassan Market | 300`\n\n"
                "/help for more examples.",
                parse_mode=ParseMode.MARKDOWN,
            )
            return
        try:
            result = _sheets().add_expense(record)
            await update.message.reply_text(
                _fmt_expense(record, result), parse_mode=ParseMode.MARKDOWN
            )
        except Exception as e:
            logger.error("Sheets expense error: %s", e)
            await update.message.reply_text(f"⚠️ Could not save: `{e}`",
                                            parse_mode=ParseMode.MARKDOWN)


# ─────────────────────────── Photo handler ────────────────────────────────────

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not ocr_available():
        await update.message.reply_text(
            "⚠️ OCR is not installed. Please send expenses as text.\n"
            "Install Tesseract: https://github.com/UB-Mannheim/tesseract/wiki"
        )
        return

    caption  = update.message.caption or ""
    is_sales = is_sales_message(caption)

    if update.message.photo:
        tg_file = await update.message.photo[-1].get_file()
        suffix  = ".jpg"
    else:
        doc     = update.message.document
        suffix  = os.path.splitext(doc.file_name)[1].lower() or ".jpg"
        tg_file = await doc.get_file()

    status = await update.message.reply_text("📸 Photo received — running OCR…")

    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        await tg_file.download_to_drive(tmp.name)
        img_path = tmp.name

    try:
        ocr_text = extract_text_from_image(img_path)
    except Exception as e:
        logger.error("OCR error: %s", e)
        await status.edit_text(f"⚠️ Could not read image: `{e}`",
                               parse_mode=ParseMode.MARKDOWN)
        return
    finally:
        os.unlink(img_path)

    if not ocr_text.strip():
        await status.edit_text(
            "⚠️ No text found.\n\n"
            "Tips: good lighting, hold phone straight above receipt, printed receipts work best."
        )
        return

    # Fall back to OCR text if caption didn't flag as sales
    if not is_sales:
        is_sales = is_sales_message(ocr_text)

    records = parse_sales_from_ocr(ocr_text, source="Photo") if is_sales \
              else parse_expenses_from_ocr(ocr_text, source="Photo")

    if not records:
        preview = ocr_text[:400].replace("`", "'")
        await status.edit_text(
            f"⚠️ Read text but no amounts found.\n\n*Saw:*\n```\n{preview}\n```\n\n"
            "Type the expense manually if needed.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    try:
        sm = _sheets()
        result = sm.add_sales_bulk(records) if is_sales else sm.add_expenses_bulk(records)
        await status.edit_text(
            _fmt_bulk(result, records, "photo", is_sales=is_sales),
            parse_mode=ParseMode.MARKDOWN,
        )
    except Exception as e:
        logger.error("Sheets photo error: %s", e)
        await status.edit_text(f"⚠️ Could not save: `{e}`", parse_mode=ParseMode.MARKDOWN)


# ─────────────────────────── Document / PDF handler ───────────────────────────

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    doc   = update.message.document
    fname = doc.file_name.lower()

    # Image files sent as documents → treat as photos
    if fname.endswith((".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tiff")):
        await handle_photo(update, context)
        return

    if not fname.endswith(".pdf"):
        await update.message.reply_text(
            "📎 Please send a *PDF* or a *photo* of a receipt.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    caption  = update.message.caption or ""
    is_sales = is_sales_message(caption)

    status = await update.message.reply_text(
        "📄 PDF received — reading pages…", parse_mode=ParseMode.MARKDOWN
    )

    tg_file = await doc.get_file()
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        await tg_file.download_to_drive(tmp.name)
        pdf_path = tmp.name

    try:
        pages = _extract_pdf_pages(pdf_path)
    except Exception as e:
        logger.error("PDF read error: %s", e)
        await status.edit_text(f"⚠️ Could not read PDF: `{e}`",
                               parse_mode=ParseMode.MARKDOWN)
        return
    finally:
        os.unlink(pdf_path)

    if not pages:
        await status.edit_text(
            "⚠️ No text found — even after OCR.\nTry sending a photo instead.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    await status.edit_text(
        f"📄 {len(pages)} page(s) read. Grouping invoices…",
        parse_mode=ParseMode.MARKDOWN,
    )
    invoices = _group_invoices(pages)

    await status.edit_text(
        f"📄 *{len(invoices)} invoice(s)* across {len(pages)} page(s). Saving…",
        parse_mode=ParseMode.MARKDOWN,
    )

    all_records = []
    for i, inv_text in enumerate(invoices):
        if is_sales:
            all_records.extend(parse_sales_from_ocr(inv_text, source=f"Invoice {i+1}"))
        else:
            all_records.extend(parse_expenses_from_ocr(inv_text, source=f"Invoice {i+1}"))

    if not all_records:
        await status.edit_text("⚠️ Found text but no expense totals. Try sending as text.")
        return

    try:
        sm = _sheets()
        result = sm.add_sales_bulk(all_records) if is_sales else sm.add_expenses_bulk(all_records)
        await status.edit_text(
            _fmt_bulk(result, all_records,
                      f"PDF ({len(invoices)} invoices, {len(pages)} pages)",
                      is_sales=is_sales),
            parse_mode=ParseMode.MARKDOWN,
        )
    except Exception as e:
        logger.error("Sheets PDF error: %s", e)
        await status.edit_text(f"⚠️ Could not save: `{e}`", parse_mode=ParseMode.MARKDOWN)


# ─────────────────────────── Error handler ────────────────────────────────────

async def handle_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error("Unhandled exception", exc_info=context.error)
    if isinstance(update, Update) and update.message:
        try:
            await update.message.reply_text("⚠️ Something went wrong. Please try again.")
        except Exception:
            pass


# ─────────────────────────── Bot runner ───────────────────────────────────────

async def run_bot() -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise ValueError("TELEGRAM_BOT_TOKEN is not set in .env")

    app = Application.builder().token(token).build()

    app.add_handler(CommandHandler("start",   cmd_start))
    app.add_handler(CommandHandler("help",    cmd_help))
    app.add_handler(CommandHandler("sheet",   cmd_sheet))
    app.add_handler(CommandHandler("summary", cmd_summary))
    app.add_handler(MessageHandler(filters.PHOTO,                        handle_photo))
    app.add_handler(MessageHandler(filters.Document.ALL,                 handle_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND,      handle_text))
    app.add_error_handler(handle_error)

    logger.info("🤖 Bot started (single-user mode)")
    await app.initialize()
    await app.start()
    await app.updater.start_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=False,
        timeout=30,
    )
    await asyncio.Event().wait()


# ─────────────────────────── Entry point ──────────────────────────────────────

if __name__ == "__main__":
    asyncio.run(run_bot())
