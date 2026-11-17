"""Quotation document: bilingual HTML, PDF export (headless Chrome), and WhatsApp share text."""
import base64
import os
import shutil
import subprocess
import tempfile
from flask import render_template
from .money import format_bhd, format_quantity, compute_quote, LineInput

LBL = {
    "quotation": ("Quotation", "عرض سعر"), "number": ("Quote no.", "رقم العرض"), "date": ("Date", "التاريخ"),
    "valid": ("Valid until", "صالح حتى"), "to": ("Prepared for", "مقدم إلى"), "item": ("Description", "البيان"),
    "qty": ("Qty", "الكمية"), "unit_price": ("Unit price", "سعر الوحدة"), "vat": ("VAT", "الضريبة"),
    "amount": ("Amount", "المبلغ"), "subtotal": ("Subtotal", "المجموع الفرعي"), "discount": ("Discount", "الخصم"),
    "vat_total": ("VAT", "ضريبة القيمة المضافة"), "total": ("Total", "الإجمالي"), "terms": ("Terms & conditions", "الشروط والأحكام"),
    "notes": ("Notes", "ملاحظات"), "cr": ("CR No.", "السجل التجاري"), "vat_no": ("VAT No.", "الرقم الضريبي"),
    "currency": ("BHD", "د.ب"), "phone": ("Tel", "هاتف"), "exempt": ("Exempt", "معفى"), "zero": ("0%", "0%"),
    "not_reg": ("VAT not applicable", "لا تنطبق ضريبة القيمة المضافة"), "thanks": ("Thank you for your business.", "نشكركم على ثقتكم."),
    "accept": ("Customer acceptance", "موافقة العميل"), "sign": ("Signature", "التوقيع"), "name_l": ("Name", "الاسم"),
    "details": ("Quotation details", "تفاصيل العرض"), "accept_note": ("By signing, the customer accepts this quotation and its terms.", "بالتوقيع يوافق العميل على عرض السعر وشروطه."),
    "optional": ("Optional add-ons", "إضافات اختيارية"), "not_incl": ("Not included in the total above", "غير مشمولة في الإجمالي أعلاه"),
    "chosen": ("Selected by the customer", "اختارها العميل"), "accepted_on": ("Accepted online by", "تمت الموافقة إلكترونياً من"),
    "taxable": ("Taxable amount", "المبلغ الخاضع للضريبة"), "brand": ("Created with QuoteFlow AI", "أُنشئ بواسطة QuoteFlow AI"),
}
UNIT_AR = {"each": "قطعة", "unit": "وحدة", "visit": "زيارة", "hour": "ساعة", "day": "يوم", "job": "عمل", "month": "شهر",
           "seat": "مقعد", "window": "نافذة", "room": "غرفة", "m2": "م²", "m": "م",
           "item": "قطعة", "trip": "رحلة", "box": "كرتون", "floor": "طابق"}


def _logo_data_uri(path):
    if path and os.path.exists(path):
        with open(path, "rb") as f:
            return "data:image/png;base64," + base64.b64encode(f.read()).decode()
    return None


def _selected(quote):
    raw = (quote["selected_optional"] if "selected_optional" in quote.keys() else "") or ""
    return {int(x) for x in raw.split(",") if x.strip().isdigit()}


def render_document(company, quote, items, totals, customer, lang):
    if lang not in ("en", "ar", "both"):
        lang = quote["language"]
    selected = _selected(quote)
    rows, optional_rows, n = [], [], 0
    for it, r in zip(items, totals.lines):
        if not it.get("optional") or it["id"] in selected:
            n += 1
            rows.append({"n": n, "it": it, "r": r, "chosen": bool(it.get("optional"))})
        else:
            one = compute_quote([LineInput(it["quantity_milli"], it["unit_price_fils"], it["tax_class"])], "none", 0,
                                bool(company["vat_registered"]), company["vat_rate_bp"])
            optional_rows.append({"it": it, "amount": one.lines[0].line_total_fils})

    def lab(key):
        en, ar = LBL[key]
        return en if lang == "en" else (ar if lang == "ar" else f"{en} / {ar}")

    def unit(u):
        ar = UNIT_AR.get(u, u)
        return u if lang == "en" else (ar if lang == "ar" else f"{u} / {ar}")

    return render_template(
        "quote_doc.html", company=company, q=quote, items=items, rows=rows, optional_rows=optional_rows, tot=totals, cust=customer, lang=lang, lab=lab,
        unit=unit, logo=_logo_data_uri(company.get("logo_path")), fmt_qty=format_quantity,
        direction="rtl" if lang == "ar" else "ltr", show_brand=company["plan"] == "free")


def find_chrome():
    env = os.environ.get("QF_CHROME_BIN")
    if env and shutil.which(env):
        return shutil.which(env)
    for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "chrome"):
        p = shutil.which(name)
        if p:
            return p
    return None


class PdfUnavailable(Exception):
    pass


def html_to_pdf(html: str, timeout=45) -> bytes:
    chrome = find_chrome()
    if not chrome:
        raise PdfUnavailable("No Chrome/Chromium found on this server (set QF_CHROME_BIN).")
    with tempfile.TemporaryDirectory() as tmp:
        src, out = os.path.join(tmp, "q.html"), os.path.join(tmp, "q.pdf")
        fonts = os.path.join(os.path.dirname(__file__), "static", "fonts")
        html = html.replace("url(/static/fonts/", "url(file://" + fonts + "/")
        with open(src, "w", encoding="utf-8") as f:
            f.write(html)
        cmd = [chrome, "--headless=new", "--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage",
               "--no-pdf-header-footer", f"--user-data-dir={os.path.join(tmp, 'profile')}",
               f"--print-to-pdf={out}", "file://" + src]
        try:
            subprocess.run(cmd, check=True, timeout=timeout, capture_output=True)
        except (subprocess.SubprocessError, OSError) as e:
            raise PdfUnavailable(f"PDF engine failed: {type(e).__name__}")
        if not os.path.exists(out):
            raise PdfUnavailable("PDF engine produced no file.")
        with open(out, "rb") as f:
            return f.read()


def share_text(company, quote, items, totals, customer, lang, link=None):
    """Plain text for the owner to paste into WhatsApp (manual; no WhatsApp API)."""
    name = (customer or {}).get("name") or ""
    cur = "BHD"

    def block(lg):
        ar = lg == "ar"
        cname = company["name_ar"] if (ar and company["name_ar"]) else company["name_en"]
        lines = [(f"السلام عليكم {name}،" if ar else f"Hello {name},").replace("  ", " ").replace(" ،", "،").replace(" ,", ","),
                 (f"عرض السعر رقم {quote['number']} من {cname}:" if ar else f"Your quotation {quote['number']} from {cname}:"), ""]
        sel = _selected(quote)
        shown = [(it, r) for it, r in zip(items, totals.lines) if not it.get("optional") or it["id"] in sel]
        for i, (it, r) in enumerate(shown, 1):
            title = (it["title_ar"] or it["title_en"]) if ar else (it["title_en"] or it["title_ar"])
            lines.append(f"{i}. {title} × {format_quantity(it['quantity_milli'])} = {format_bhd(r.line_total_fils)} {cur}")
        lines.append("")
        if totals.discount_fils:
            lines.append((f"الخصم: -{format_bhd(totals.discount_fils)} {cur}" if ar else f"Discount: -{format_bhd(totals.discount_fils)} {cur}"))
        if totals.vat_applied:
            lines.append((f"ضريبة القيمة المضافة: {format_bhd(totals.vat_fils)} {cur}" if ar else f"VAT: {format_bhd(totals.vat_fils)} {cur}"))
        lines.append((f"*الإجمالي: {format_bhd(totals.total_fils)} {cur}*" if ar else f"*Total: {format_bhd(totals.total_fils)} {cur}*"))
        if quote["valid_until"]:
            lines.append((f"صالح حتى {quote['valid_until']}" if ar else f"Valid until {quote['valid_until']}"))
        lines.append("")
        if link:
            lines.append(("اعرض العرض واختر الإضافات ووافق عليه إلكترونياً:" if ar else "View, choose add-ons and accept online:"))
            lines.append(link)
            lines.append("")
        lines.append("يسعدنا خدمتكم. المرفق عرض السعر بصيغة PDF." if ar else "We would be happy to serve you. The PDF quotation is attached.")
        return "\n".join(lines)

    if lang == "both":
        return block("en") + "\n\n――――――\n\n" + block("ar")
    return block("ar" if lang == "ar" else "en")
