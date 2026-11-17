"""Tiny UI translation layer. English text is the key; Arabic is looked up if the UI is Arabic.
Quotation output (PDF/preview) has its own language setting, independent of the UI."""

AR = {
    "Dashboard": "الرئيسية",
    "New enquiry": "استفسار جديد",
    "Quotes": "عروض الأسعار",
    "Catalogue": "الخدمات",
    "Customers": "العملاء",
    "Settings": "الإعدادات",
    "Log out": "تسجيل الخروج",
    "Log in": "تسجيل الدخول",
    "Create account": "إنشاء حساب",
    "Email": "البريد الإلكتروني",
    "Username": "اسم المستخدم",
    "Account": "الحساب",
    "Password": "كلمة المرور",
    "Save": "حفظ",
    "Company profile": "ملف الشركة",
    "Quotes this month": "عروض هذا الشهر",
    "Recent quotes": "أحدث العروض",
    "Plan": "الباقة",
    "Search": "بحث",
    "Draft": "مسودة",
    "Sent": "مرسل",
    "Follow-up": "متابعة",
    "Accepted": "مقبول",
    "Rejected": "مرفوض",
    "Expired": "منتهي",
}


def make_t(lang: str):
    def t(s: str) -> str:
        if lang == "ar":
            return AR.get(s, s)
        return s
    return t
