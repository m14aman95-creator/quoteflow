"""Resolve relative dates in English / Gulf Arabic. Code does the calendar maths, not the model."""
import re
from datetime import date, timedelta
from typing import Optional, Tuple
from .text import prep, norm_lp

_WEEKDAYS_EN = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
_WEEKDAYS_AR = ["الاثنين", "الثلاثاء", "الاربعاء", "الخميس", "الجمعه", "السبت", "الاحد"]
_MONTHS = {m: i + 1 for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november",
     "december"])}
_MONTHS.update({m[:3]: i for m, i in list(_MONTHS.items())})

# (regex on length-preserving normalised text, offset in days)
_REL = [
    (r"day after tomorrow|بعد بكر[هة]|بعد باكر|بعد غد", 2),
    (r"tomorrow|tmrw|tomorow|بكر[هة]|باكر|غدا|غدًا|\bgda\b", 1),
    (r"today|tonight|this evening|right now|\bnow\b|اليوم|الليله|الحين|هالليله|هاليوم", 0),
]


def find_date_phrase(raw: str, today: date) -> Tuple[Optional[str], Optional[date]]:
    """Return (phrase as the customer wrote it, resolved date or None)."""
    t = prep(raw)
    n = norm_lp(t)
    for pat, off in _REL:
        m = re.search(pat, n)
        if m:
            return t[m.start():m.end()], today + timedelta(days=off)
    # explicit numeric date: 25/11, 25-11-2026
    m = re.search(r"(?<!\d)(\d{1,2})[/\-.](\d{1,2})(?:[/\-.](\d{2,4}))?(?![\d:])", n)
    if m:
        d_, mo = int(m.group(1)), int(m.group(2))
        y = int(m.group(3)) if m.group(3) else today.year
        y = y + 2000 if y < 100 else y
        try:
            dt = date(y, mo, d_)
            if not m.group(3) and dt < today:
                dt = date(y + 1, mo, d_)
            return t[m.start():m.end()], dt
        except ValueError:
            pass
    # "25 november" / "november 25"
    m = re.search(r"(?<!\d)(\d{1,2})(?:st|nd|rd|th)?\s+(?:of\s+)?([a-z]{3,9})\b", n)
    if m and m.group(2) in _MONTHS:
        try:
            dt = date(today.year, _MONTHS[m.group(2)], int(m.group(1)))
            if dt < today:
                dt = date(today.year + 1, dt.month, dt.day)
            return t[m.start():m.end()], dt
        except ValueError:
            pass
    # weekday names -> next occurrence (never today)
    for i, w in enumerate(_WEEKDAYS_EN):
        m = re.search(rf"\b{w}\b", n)
        if m:
            d = _next_weekday(today, i)
            # "next Wednesday" said on a Tuesday is ambiguous (tomorrow, or a week later): do not guess
            if re.search(rf"\bnext\s+{w}\b", n) and (d - today).days <= 2:
                return t[m.start():m.end()], None
            return t[m.start():m.end()], d
    for i, w in enumerate(_WEEKDAYS_AR):
        m = re.search(w, n)
        if m:
            return t[m.start():m.end()], _next_weekday(today, i)
    # vague, no resolvable date
    m = re.search(r"next week|this week|next month|الاسبوع (?:الجاي|القادم|الياي|الجاى)|اسبوع الجاي|الشهر الجاي|asap|as soon as possible|"
                  r"في اقرب وقت|باقرب وقت|اقرب وقت", n)
    if m:
        return t[m.start():m.end()], None
    return None, None


def _next_weekday(today: date, weekday: int) -> date:
    delta = (weekday - today.weekday()) % 7
    return today + timedelta(days=delta or 7)


def pretty(d: date) -> str:
    return d.strftime("%a %d %b %Y")
