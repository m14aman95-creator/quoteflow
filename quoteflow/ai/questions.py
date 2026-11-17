"""Deterministic missing-detail detection. Used to guarantee core clarification questions even if the
language model forgets them, and as the whole question engine of the offline extractor.
Each question is bilingual so the owner can paste it into WhatsApp in the customer's language."""
import re
from .text import norm_lp

Q = {
    "name": ("May I have your name, please?", "ممكن أعرف اسمك الكريم؟"),
    "location": ("Which area (and building/block) is the job in?", "في أي منطقة (ورقم المبنى/المجمع) الموقع؟"),
    "date": ("When would you like us to come? Any preferred time?", "متى تحب نجي؟ وأي وقت يناسبك؟"),
    "quantity": ("How many {thing} should we include?", "كم عدد {thing_ar} المطلوب؟"),
    "ac_type": ("What type are the AC units (split, window, cassette, central)?",
                "ما نوع المكيفات (سبلت، شباك، كاسيت، مركزي)؟"),
    "ac_leak": ("Is the water leaking from the indoor or the outdoor unit, and is it still cooling?",
                "التسريب من الوحدة الداخلية أو الخارجية؟ وهل المكيف لا يزال يبرّد؟"),
    "ac_gas": ("Do you know the gas type (R410A / R22) or when it was last refilled?",
               "هل تعرف نوع الغاز (R410A / R22) أو متى آخر تعبئة؟"),
    "parts": ("If a spare part is needed, should we quote it separately for your approval?",
              "إذا احتاج الأمر قطعة غيار، هل نرسل لك سعرها بشكل منفصل للموافقة؟"),
    "area_size": ("What is the size of the place (bedrooms / approximate m2)?",
                  "ما حجم المكان (عدد الغرف / المساحة التقريبية بالمتر المربع)؟"),
    "frequency": ("How often do you need the service and for how many hours per visit?",
                  "كم مرة تحتاج الخدمة وكم ساعة في كل زيارة؟"),
    "supplies": ("Should cleaning materials and equipment be included?", "هل تريد أن تكون مواد ومعدات التنظيف مشمولة؟"),
    "seats": ("How many seats are on the sofa(s) and what is the fabric?", "كم عدد مقاعد الكنب ونوع القماش؟"),
    "move_route": ("Where are we moving from and to (area, building and floor)?", "من أين إلى أين سننقل (المنطقة والمبنى والطابق)؟"),
    "lift": ("Is there a working lift at both addresses, and is there easy parking for the truck?", "هل يوجد مصعد شغال في العنوانين، وهل المواقف متاحة للشاحنة؟"),
    "inventory": ("What needs to be moved (number of rooms, and any large items like wardrobes, fridge or piano)?", "ما الذي سيتم نقله (عدد الغرف وأي قطع كبيرة مثل الدواليب أو الثلاجة أو البيانو)؟"),
    "packing": ("Do you need packing (boxes and wrapping) or will you pack yourself?", "هل تحتاج خدمة التغليف (كراتين وتغليف) أم ستقوم بالتغليف بنفسك؟"),
    "dismantle": ("Should we dismantle and reassemble beds, wardrobes or other furniture?", "هل تريد منا فك وتركيب الأسرّة والدواليب والأثاث؟"),
    "issue": ("Could you describe the problem or send a photo so the technician comes prepared?", "ممكن توصف المشكلة أو ترسل صورة حتى يجي الفني جاهز؟"),
    "supply": ("Will you supply the fitting (tap, light, lock, bracket) or should we quote it separately?", "هل ستوفر القطعة (خلاط، إضاءة، قفل، حامل) أم نسعّرها بشكل منفصل؟"),
    "access": ("Will someone be at the property to give access, and is there parking nearby?", "هل سيكون أحد في العقار لفتح الباب، وهل تتوفر مواقف قريبة؟"),
    "windows": ("Roughly how many windows, and are any hard to reach?", "كم عدد النوافذ تقريباً وهل بعضها صعب الوصول؟"),
}

_PATTERNS = {
    "ac_type": r"split|window|cassette|central|duct|ducted|سبلت|شباك|كاسيت|مركزي|دكت|ستاند",
    "ac_leak_detail": r"indoor|outdoor|inside|outside|داخلي|خارجي|داخل|بره|برا",
    "gas_detail": r"r410|r22|r32|freon.*(?:type|r\d)|نوع الغاز",
    "parts": r"\bparts?\b|spare|قطع|قطعه|سبير",
    "size": r"m2|sqm|sq\.? ?m|square|bedroom|\bbr\b|bhk|\brooms?\b|متر|غرف|غرفه|غرفة|مساحه|sq ft|sqft",
    "frequency": r"weekly|daily|monthly|every|twice|once a|per week|times a|hours?|اسبوعي|يومي|شهري|كل |مرتين|ساعات|ساعه",
    "move_route": r"from .{2,40} to |من .{2,40} (?:الى|إلى) ",
    "lift": r"lift|elevator|stairs|ground floor|مصعد|درج|ارضي|أرضي",
    "inventory": r"bedroom|\bbr\b|studio|villa|sofa|bed\b|wardrobe|fridge|items|pieces|piano|غرف|غرفة|كنب|سرير|دولاب|ثلاجة|قطع|فيلا|استوديو|شقة",
    "packing": r"pack|boxes|wrap|تغليف|كراتين|تعبئة",
    "dismantle": r"dismantle|assemble|take apart|فك|تركيب",
    "issue": r"because|since|when|photo|picture|noise|smell|not working|broken|stuck|صورة|صوره|يطلع|ما يشتغل|خربان|مكسور",
    "supply": r"supply|supplied|provide|i have|i bought|will bring|عندي|اشتريت|وفرت|يوفر",
    "access": r"home|someone|key|parking|security|بيت|احد|مفتاح|مواقف",
    "supplies": r"material|suppl(?:y|ies)|equipment|detergent|مواد|معدات",
    "seats": r"seat|seater|مقعد|مقاعد",
}


def _has(key, text_n):
    return re.search(_PATTERNS[key], text_n) is not None


def build_questions(text: str, result: dict, services_by_id: dict):
    """Return [{'field','question_en','question_ar'}, ...] for details that are missing.
    `result` is a dict shaped like ai.schema.RawExtraction (already validated)."""
    t = norm_lp(text)
    qs = []

    def add(key, field=None, **fmt):
        en, ar = Q[key]
        qs.append({"field": field or key, "question_en": en.format(**fmt) if fmt else en,
                   "question_ar": ar.format(**fmt) if fmt else ar})

    matched = [services_by_id[i["matched_service_id"]] for i in result["items"]
               if i.get("matched_service_id") in services_by_id]
    names = " ".join((m["name_en"] or "").lower() for m in matched)
    unmatched = any(i.get("matched_service_id") is None for i in result["items"])

    if not (result["location"]["value"]):
        add("location")
    if not (result["requested_date"]["value"]):
        add("date")
    for it in result["items"]:
        if it.get("quantity") in (None, 0) and it.get("matched_service_id") in services_by_id:
            svc = services_by_id[it["matched_service_id"]]
            add("quantity", "quantity", thing=svc["name_en"].lower(), thing_ar=svc["name_ar"] or svc["name_en"])
    if not result["items"] or unmatched:
        qs.append({"field": "service", "question_en": "Could you describe exactly what service you need?",
                   "question_ar": "ممكن توضح لي بالضبط ما هي الخدمة المطلوبة؟"})

    is_ac = bool(re.search(r"\bac\b|air.?condition|split|aircon", names)) or bool(re.search(r"\bac\b|مكيف|سبلت|تكييف", t))
    if is_ac:
        if not _has("ac_type", t):
            add("ac_type")
        if "leak" in names and not _has("ac_leak_detail", t):
            add("ac_leak")
        if "gas" in names and not _has("gas_detail", t):
            add("ac_gas")
        if re.search(r"leak|repair|inspection|diagnos|fault|install", names) and not _has("parts", t):
            add("parts")
    clean_names = bool(re.search(r"clean", names))
    is_moving = (bool(re.search(r"\bmove\b|mover|packing|storage|dismantle|furniture|no-lift|removal|heavy item", names)) and not clean_names) or \
        (not matched and bool(re.search(r"\bmov(?:e|ing)\b|shift|relocat|نقل|عفش|اثاث|أثاث", t)) and not re.search(r"clean|تنظيف", t))
    is_household = bool(re.search(r"plumb|tap, mixer|water heater|electrical|light fixture|ceiling fan|handyman|door lock|painting|pest|curtain|tv wall|furniture assembly|water tank", names))
    if is_moving and not is_ac:
        if not _has("move_route", t):
            add("move_route")
        if not _has("inventory", t):
            add("inventory")
        if not _has("lift", t):
            add("lift")
        if not _has("packing", t):
            add("packing")
        if not _has("dismantle", t):
            add("dismantle")
    if is_household and not is_ac and not is_moving:
        if re.search(r"plumb|heater|electrical|lock|handyman", names) and not _has("issue", t):
            add("issue")
        if re.search(r"tap, mixer|light fixture|ceiling fan|door lock|tv wall|curtain|water heater|plumb|electrical", names) and not _has("supply", t):
            add("supply")
        if re.search(r"painting|pest|water tank", names) and not _has("size", t):
            add("area_size")
        if not _has("access", t):
            add("access")
    is_cleaning = (clean_names or bool(re.search(r"clean|deep|villa|apartment|office|move|sofa|carpet|window|hour", names) and not (is_moving or is_household))) or \
        bool(re.search(r"تنظيف|نظافه|clean", t))
    if is_cleaning and not is_ac and not is_moving and not is_household:
        if re.search(r"deep|villa|apartment|office|move|regular", names) and not _has("size", t):
            add("area_size")
        if re.search(r"regular|office|hour|month", names) and not _has("frequency", t):
            add("frequency")
        if re.search(r"sofa", names) and not _has("seats", t):
            add("seats")
        if re.search(r"window", names) and not any(i.get("quantity") for i in result["items"]):
            add("windows")
        if not _has("supplies", t):
            add("supplies")
    if not result["customer_name"]["value"]:
        add("name")

    seen, out = set(), []
    for q in qs:
        k = (q["field"], q["question_en"])
        if k not in seen:
            seen.add(k)
            out.append(q)
    return out[:8]
