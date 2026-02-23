import io
import json
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional, Tuple, Type
from django.urls import reverse
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.hashers import check_password, make_password
from django.db import transaction
from django.http import (
    HttpRequest,
    HttpResponse,
    JsonResponse,
)
from django.shortcuts import render, redirect
from django.utils import timezone
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_http_methods, require_POST, require_GET

from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
import os
from .models import (
    Users, Order,
    Rangsiz, Rangli, Kapliya, Aksessuar, Antikompyuter, Oprava, Gatoviy,
    Archive, ArchiveItem,
    FeedBack, TelegramChat
)

from reportlab.lib.colors import HexColor, white
from datetime import datetime
import math

LINE_H   = 11   # height of one text line inside a cell (points)
CELL_PAD = 4    # top + bottom inner padding (points)

def _wrap_text(text: str, font_name: str, font_size: float, max_width: float) -> List[str]:
    """
    Word-wrap `text` so each line fits within `max_width` points.
    Returns a list of line strings (at least one).
    """
    usable = max_width - 6   # 3pt left + 3pt right padding
    words  = (text or "").split()
    if not words:
        return [""]

    lines, current = [], ""
    for word in words:
        candidate = (current + " " + word).strip() if current else word
        try:
            w = pdfmetrics.stringWidth(candidate, font_name, font_size)
        except Exception:
            w = len(candidate) * font_size * 0.6   # fallback estimate
        if w <= usable:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines or [""]


def _cell_h(n_lines: int) -> float:
    """Row height needed to fit n_lines of text."""
    return max(ROW_H, n_lines * LINE_H + CELL_PAD * 2)


# ─── colours matching QuestPDF / MudBlazor equivalents ───────────────────────
BLUE_DARKEN2   = HexColor("#1565C0")
HEADER_BG      = HexColor("#E0F7FA")   # #E0F7FA — same as order PDF
GREY_LIGHTEN3  = HexColor("#F5F5F5")   # Colors.Grey.Lighten3
BLUE_LIGHTEN5  = HexColor("#E3F2FD")   # Colors.Blue.Lighten5
GREEN_LIGHTEN5 = HexColor("#E8F5E9")   # Colors.Green.Lighten5
ORANGE_LIGHTEN4= HexColor("#FFE0B2")   # Colors.Orange.Lighten4
# Cycles exactly as the C# array does
FILIAL_COLORS = [GREY_LIGHTEN3, BLUE_LIGHTEN5, GREEN_LIGHTEN5, ORANGE_LIGHTEN4]

ROW_H    = 18   # row height in points (~18pt ≈ compact table row)
FONT_SZ  = 8   # body font size
HDR_SZ   = 10   # header font size

def _draw_cell(
    c: canvas.Canvas,
    x: float, y: float,
    w: float, h: float,
    text: str,
    font: str,
    font_size: float,
    bg: HexColor = None,
    text_color: HexColor = None,
    bold: bool = False,
):
    """Draw one table cell with word-wrapped text, background fill, and border."""
    active_font = (font + "-Bold") if bold else font
    try:
        pdfmetrics.stringWidth("x", active_font, font_size)
    except Exception:
        active_font = font

    # Background fill
    if bg is not None:
        c.setFillColor(bg)
        c.rect(x, y - h, w, h, stroke=0, fill=1)

    # Border
    c.setStrokeColor(HexColor("#000000"))
    c.rect(x, y - h, w, h, stroke=1, fill=0)

    # Word-wrap and draw each line
    lines = _wrap_text(str(text or ""), active_font, font_size, w)
    c.setFillColor(text_color if text_color else HexColor("#000000"))
    try:
        c.setFont(active_font, font_size)
    except Exception:
        c.setFont(font, font_size)

    # Start text from top of cell with padding
    text_y = y - CELL_PAD - LINE_H + 2
    for line in lines:
        if text_y > (y - h + 2):   # don't draw below cell bottom
            c.drawString(x + 3, text_y, line)
        text_y -= LINE_H
# -----------------------------
# Session helpers
# -----------------------------

def _session_user_or_redirect(request: HttpRequest):
    if not request.session.get("UserId"):
        return redirect("optika:login")
    return None


def _session_user_or_json_401(request: HttpRequest):
    if not request.session.get("UserId"):
        return JsonResponse({"success": False, "message": "Login qiling (session topilmadi)."}, status=401)
    return None


def _admin_or_403(request: HttpRequest) -> Optional[JsonResponse]:
    if request.session.get("Role") != "Admin":
        return JsonResponse({"success": False, "message": "Admin ruxsati kerak."}, status=403)
    return None


def _admin_or_redirect(request: HttpRequest):
    if request.session.get("Role") != "Admin":
        return redirect("optika:index")
    return None


def _get_branch(request: HttpRequest) -> str:
    return request.session.get("Branch") or "-"


def _get_user_id(request: HttpRequest) -> str:
    return request.session.get("UserId") or ""


def _get_full_name(request: HttpRequest) -> str:
    return request.session.get("FullName") or ""


# -----------------------------
# JSON helpers
# -----------------------------

def _parse_json_body(request: HttpRequest) -> Any:
    try:
        raw = request.body.decode("utf-8") if request.body else ""
        return json.loads(raw) if raw else None
    except json.JSONDecodeError:
        return None


def _to_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _to_decimal_or_none(value: Any) -> Optional[Decimal]:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _clean_str(value: Any) -> str:
    return (value or "").strip()


# -----------------------------
# PDF helpers (ReportLab)
# -----------------------------

def _try_register_cyrillic_font() -> str:
    font_path = os.path.join(
        settings.BASE_DIR,
        "static",
        "fonts",
        "DejaVuSans.ttf"
    )

    if os.path.exists(font_path):
        pdfmetrics.registerFont(TTFont("DejaVuSans", font_path))
        return "DejaVuSans"

    return "Helvetica"

def _truncate(text: str, max_len: int) -> str:
    text = text or ""
    return text if len(text) <= max_len else text[: max_len - 1] + "…"


def _build_table_pdf(
    full_name: str,
    branch: str,
    columns: List[Tuple[str, float]],   # (name, relative_weight)
    rows: List[List[str]],
    page_size: int = 36,
    title_line1: str = "Buyurtmalar ro'yxati",   # NEW — configurable title
    header_date: datetime = None,                 # NEW — use archive date if provided
) -> bytes:
    font = _try_register_cyrillic_font()
    buf  = io.BytesIO()
    now  = header_date or datetime.now()          # archive date OR current time

    page_w, page_h = A4
    margin = 28.35   # 10 mm — matches page.Margin(10)

    total_weight = sum(w for _, w in columns)
    available_w  = page_w - 2 * margin
    col_widths   = [available_w * w / total_weight for _, w in columns]
    col_names    = [n for n, _ in columns]

    total_pages = max(1, math.ceil(len(rows) / page_size))
    c = canvas.Canvas(buf, pagesize=A4)

    DATA_SZ = 8    # matches C# FontSize(12) on data spans
    HDR_SZ  = 10    # matches C# FontSize(12) on header spans

    def draw_page_header(page_num: int):
        y = page_h - margin

        # "Buyurtmalar ro'yxati" or "Buyurtma arxivi" — blue, bold, FontSize 12
        try:
            c.setFont(font + "-Bold", 12)
        except Exception:
            c.setFont(font, 12)
        c.setFillColor(BLUE_DARKEN2)
        c.drawString(margin, y, title_line1)
        y -= 14
        c.drawString(margin, y, f"{full_name} ({branch})")

        # Date right-aligned on same top line (archive date or now)
        c.setFont(font, 10)
        c.setFillColor(HexColor("#000000"))
        c.drawRightString(page_w - margin, page_h - margin,
                          now.strftime("%d/%m/%Y %H:%M"))

        # "Sahifa X / Y"
        y -= 13
        c.drawString(margin, y, f"Sahifa {page_num} / {total_pages}")
        y -= 10
        return y

    def draw_table_header(y: float) -> float:
        x = margin
        for name, w in zip(col_names, col_widths):
            _draw_cell(c, x, y, w, ROW_H, name, font, HDR_SZ,
                       bg=HEADER_BG, bold=True)
            x += w
        return y - ROW_H

    def draw_footer():
        c.setFont(font, 10)
        c.setFillColor(HexColor("#000000"))
        c.drawRightString(page_w - margin, margin,
                          f"© {datetime.now().year} neeoptika.uz")

    for page_idx in range(total_pages):
        if page_idx > 0:
            c.showPage()

        page_rows = rows[page_idx * page_size:(page_idx + 1) * page_size]

        y = draw_page_header(page_idx + 1)
        draw_footer()
        y = draw_table_header(y)

        for local_i, row in enumerate(page_rows):
            bg = white if local_i % 2 == 0 else GREY_LIGHTEN3

            # Pre-calculate dynamic row height
            row_height = ROW_H
            for col_i, cw in enumerate(col_widths):
                text = str(row[col_i]) if col_i < len(row) else ""
                lines = _wrap_text(text, font, DATA_SZ, cw)
                row_height = max(row_height, _cell_h(len(lines)))

            x = margin
            for col_i, cw in enumerate(col_widths):
                cell_text = row[col_i] if col_i < len(row) else ""
                _draw_cell(c, x, y, cw, row_height, str(cell_text), font, DATA_SZ, bg=bg)
                x += cw
            y -= row_height

    c.save()
    return buf.getvalue()

# -----------------------------
# Category -> model mapping (for profile edits/deletes)
# -----------------------------

CATEGORY_MODEL: Dict[str, Type[Any]] = {
    "Контакт линза": Rangsiz,
    "Цветная линза": Rangli,
    "Капля": Kapliya,
    "Аксессуар": Aksessuar,
    "Антикомп": Antikompyuter,
    "Оправа": Oprava,
    "Готовые": Gatoviy,
}


# -----------------------------
# AUTH: Login / Logout / Index
# -----------------------------

@ensure_csrf_cookie
@require_http_methods(["GET", "POST"])
def login_view(request: HttpRequest):
    if request.method == "GET":
        # If already logged in, redirect to index
        if request.session.get("UserId"):
            return redirect("optika:index")
        return render(request, "optika/login.html")

    user_id = _clean_str(request.POST.get("userId")).lower()
    password = _clean_str(request.POST.get("password"))
    branch = _clean_str(request.POST.get("branch"))

    if not user_id or not password:
        return JsonResponse({"success": False, "message": "ID va parolni kiriting!"})

    try:
        user = Users.objects.get(user_id=user_id)
    except Users.DoesNotExist:
        return JsonResponse({"success": False, "message": "Login yoki parol noto'g'ri!"})

    ok = False
    if user.parol:
        try:
            ok = check_password(password, user.parol)
        except Exception:
            ok = False

    if not ok and user.parol == password:
        ok = True
        user.parol = make_password(password)
        user.save(update_fields=["parol"])

    if not ok:
        return JsonResponse({"success": False, "message": "Login yoki parol noto'g'ri!"})

    request.session["UserId"] = user.user_id
    request.session["FullName"] = user.full_name
    request.session["Role"] = user.role
    if branch:
        request.session["Branch"] = branch

    request.session.save()  # ← ADD THIS

    return JsonResponse({
        "success": True,
        "redirectUrl": reverse("optika:index")
    })


def logout_view(request: HttpRequest):
    request.session.flush()
    return redirect("optika:login")


@ensure_csrf_cookie
def index_view(request: HttpRequest):
    redir = _session_user_or_redirect(request)
    if redir:
        return redir

    return render(request, "optika/index.html", {
        "full_name": _get_full_name(request),
        "branch": _get_branch(request),
        "role": request.session.get("Role"),
    })


# -----------------------------
# PAGES: Category pages
# -----------------------------

@ensure_csrf_cookie
def rangsiz_page(request: HttpRequest):
    redir = _session_user_or_redirect(request)
    if redir:
        return redir
    return render(request, "optika/rangsiz.html", {"full_name": _get_full_name(request), "branch": _get_branch(request)})


@ensure_csrf_cookie
def rangli_page(request: HttpRequest):
    redir = _session_user_or_redirect(request)
    if redir:
        return redir
    return render(request, "optika/rangli.html", {"full_name": _get_full_name(request), "branch": _get_branch(request)})


@ensure_csrf_cookie
def kaplya_page(request: HttpRequest):
    redir = _session_user_or_redirect(request)
    if redir:
        return redir
    return render(request, "optika/kaplya.html", {"full_name": _get_full_name(request), "branch": _get_branch(request)})


@ensure_csrf_cookie
def aksessuar_page(request: HttpRequest):
    redir = _session_user_or_redirect(request)
    if redir:
        return redir
    return render(request, "optika/aksessuar.html", {"full_name": _get_full_name(request), "branch": _get_branch(request)})


@ensure_csrf_cookie
def antikomp_page(request: HttpRequest):
    redir = _session_user_or_redirect(request)
    if redir:
        return redir
    return render(request, "optika/antikomp.html", {"full_name": _get_full_name(request), "branch": _get_branch(request)})


@ensure_csrf_cookie
def gatoviy_page(request: HttpRequest):
    redir = _session_user_or_redirect(request)
    if redir:
        return redir
    return render(request, "optika/gatoviy.html", {"full_name": _get_full_name(request), "branch": _get_branch(request)})


@ensure_csrf_cookie
def oprava_page(request: HttpRequest):
    redir = _session_user_or_redirect(request)
    if redir:
        return redir
    return render(request, "optika/oprava.html", {"full_name": _get_full_name(request), "branch": _get_branch(request)})


# -----------------------------
# Generic save helper
# -----------------------------

def _merge_save_product_and_order(
    *,
    user_id: str,
    branch: str,
    model_cls: Type[Any],
    category: str,
    nomi: str,
    miqdor: int,
    turi: Optional[str] = None,
    dioptriya: Optional[str] = None,
    narx: Optional[Decimal] = None,
    izoh: Optional[str] = None,
    rasm: Optional[str] = None,
    extra_fields: Optional[Dict[str, Any]] = None,
):
    """
    Create/merge in product table, then create/update Order row.
    Merge key: user_id + category + nomi + (dioptriya if provided) + (turi if provided)
    """
    extra_fields = extra_fields or {}

    filters: Dict[str, Any] = {
        "user_id": user_id,
        "category__iexact": category,
        "nomi__iexact": nomi,
    }

    # Some models have dioptriya as DecimalField (Rangli), but in our usage it's usually empty.
    # We'll only filter dioptriya if it's a string and the field exists & is not DecimalField.
    if dioptriya is not None and dioptriya != "":
        filters["dioptriya__iexact"] = dioptriya

    if turi is not None and turi != "":
        filters["turi__iexact"] = turi

    existing = model_cls.objects.filter(**filters).first()

    if existing:
        existing.miqdor = (existing.miqdor or 0) + (miqdor or 0)
        if turi is not None:
            existing.turi = turi
        if dioptriya is not None:
            existing.dioptriya = dioptriya
        if izoh is not None:
            existing.izoh = izoh
        if narx is not None:
            existing.narx = narx
        if rasm is not None and hasattr(existing, "rasm"):
            existing.rasm = rasm

        for k, v in extra_fields.items():
            if hasattr(existing, k) and v is not None:
                setattr(existing, k, v)

        existing.save()

        order = Order.objects.filter(
            user_id=user_id,
            product_id=existing.id,
            category__iexact=category,
            is_sent=False,
        ).first()

        if order:
            order.miqdor = existing.miqdor
            order.izoh = existing.izoh or "-"
            order.narx = existing.narx
            order.dioptriya = getattr(existing, "dioptriya", None)
            order.filial = branch
            order.save()
        else:
            Order.objects.create(
                user_id=user_id,
                product_id=existing.id,
                category=category,
                model=getattr(existing, "nomi", "") or getattr(existing, "model", ""),
                narx=getattr(existing, "narx", None),
                dioptriya=getattr(existing, "dioptriya", None),
                miqdor=getattr(existing, "miqdor", 0),
                izoh=getattr(existing, "izoh", "-") or "-",
                filial=branch,
                created_at=timezone.now(),
                is_sent=False,
            )
        return

    # Create new product row
    create_kwargs: Dict[str, Any] = {
        "order_id": 0,
        "user_id": user_id,
        "nomi": nomi,
        "turi": turi,
        "dioptriya": dioptriya,
        "miqdor": miqdor,
        "narx": narx,
        "izoh": izoh,
        "category": category,
    }

    if rasm is not None and "rasm" in [f.name for f in model_cls._meta.fields]:
        create_kwargs["rasm"] = rasm

    # Remove keys that model doesn't have (safe guard)
    safe_kwargs = {}
    field_names = {f.name for f in model_cls._meta.fields}
    for k, v in create_kwargs.items():
        if k in field_names:
            safe_kwargs[k] = v

    for k, v in (extra_fields or {}).items():
        if k in field_names and v is not None:
            safe_kwargs[k] = v

    new_item = model_cls.objects.create(**safe_kwargs)

    Order.objects.create(
        user_id=user_id,
        product_id=new_item.id,
        category=category,
        model=getattr(new_item, "nomi", "") or getattr(new_item, "model", ""),
        narx=getattr(new_item, "narx", None),
        dioptriya=getattr(new_item, "dioptriya", None),
        miqdor=getattr(new_item, "miqdor", 0),
        izoh=getattr(new_item, "izoh", "-") or "-",
        filial=branch,
        created_at=timezone.now(),
        is_sent=False,
    )


# -----------------------------
# SAVE endpoints (JSON)
# -----------------------------

@require_POST
def save_rangsiz(request: HttpRequest):
    not_logged = _session_user_or_json_401(request)
    if not_logged:
        return not_logged

    payload = _parse_json_body(request)
    if not isinstance(payload, list) or not payload:
        return JsonResponse({"success": False, "message": "Hech narsa tanlanmadi!"}, status=400)

    user_id = _get_user_id(request)
    branch = _get_branch(request)

    with transaction.atomic():
        for item in payload:
            nomi = _clean_str(item.get("nomi") or item.get("Nomi"))
            dioptriya = _clean_str(item.get("dioptriya") or item.get("Dioptriya"))
            turi = _clean_str(item.get("turi") or item.get("Turi"))
            category = _clean_str(item.get("category") or item.get("Category") or "Контакт линза") or "Контакт линза"
            izoh = item.get("izoh") or item.get("Izoh") or ""
            miqdor = _to_int(item.get("miqdor") or item.get("Miqdor"), 0)
            narx = _to_decimal_or_none(item.get("narx") or item.get("Narx"))
            rasm = item.get("rasm") or item.get("Rasm")

            if not nomi or miqdor <= 0:
                continue

            _merge_save_product_and_order(
                user_id=user_id,
                branch=branch,
                model_cls=Rangsiz,
                category=category,
                nomi=nomi,
                miqdor=miqdor,
                dioptriya=dioptriya or None,
                turi=turi or None,
                narx=narx,
                izoh=izoh,
                rasm=rasm,
            )

    return JsonResponse({"success": True, "message": "Rangsiz linzalar saqlandi", "redirectUrl": reverse("optika:index")})


@require_POST
def save_rangli(request: HttpRequest):
    not_logged = _session_user_or_json_401(request)
    if not_logged:
        return not_logged

    payload = _parse_json_body(request)
    if not isinstance(payload, list) or not payload:
        return JsonResponse({"success": False, "message": "Hech narsa tanlanmadi!"}, status=400)

    user_id = _get_user_id(request)
    branch = _get_branch(request)

    with transaction.atomic():
        for item in payload:
            nomi = _clean_str(item.get("nomi"))
            miqdor = _to_int(item.get("miqdor"), 0)
            rasm = item.get("rasm")

            if not nomi or miqdor <= 0:
                continue

            _merge_save_product_and_order(
                user_id=user_id,
                branch=branch,
                model_cls=Rangli,
                category="Цветная линза",
                nomi=nomi,
                miqdor=miqdor,
                rasm=rasm,
                izoh=item.get("izoh") or "",
                turi=item.get("turi"),
            )

    return JsonResponse({"success": True, "message": "Rangli linzalar saqlandi", "redirectUrl": reverse("optika:index")})


@require_POST
def save_kapliya(request: HttpRequest):
    not_logged = _session_user_or_json_401(request)
    if not_logged:
        return not_logged

    payload = _parse_json_body(request)
    if not isinstance(payload, list) or not payload:
        return JsonResponse({"success": False, "message": "Hech narsa tanlanmadi!"}, status=400)

    user_id = _get_user_id(request)
    branch = _get_branch(request)

    with transaction.atomic():
        for item in payload:
            nomi = _clean_str(item.get("nomi"))
            turi = _clean_str(item.get("turi"))
            miqdor = _to_int(item.get("miqdor"), 0)
            rasm = item.get("rasm")

            if not nomi or miqdor <= 0:
                continue

            _merge_save_product_and_order(
                user_id=user_id,
                branch=branch,
                model_cls=Kapliya,
                category="Капля",
                nomi=nomi,
                turi=turi or None,
                miqdor=miqdor,
                rasm=rasm,
                izoh=item.get("izoh") or "",
            )

    return JsonResponse({"success": True, "message": "Kaplyalar saqlandi", "redirectUrl": reverse("optika:index")})


@require_POST
def save_aksessuar(request: HttpRequest):
    not_logged = _session_user_or_json_401(request)
    if not_logged:
        return not_logged

    payload = _parse_json_body(request)
    if not isinstance(payload, list) or not payload:
        return JsonResponse({"success": False, "message": "Hech narsa tanlanmadi!"}, status=400)

    user_id = _get_user_id(request)
    branch = _get_branch(request)

    with transaction.atomic():
        for item in payload:
            nomi = _clean_str(item.get("nomi"))
            turi = _clean_str(item.get("turi"))
            miqdor = _to_int(item.get("miqdor"), 0)
            narx = _to_decimal_or_none(item.get("narx"))
            izoh = item.get("izoh") or ""
            rasm = item.get("rasm")

            if not nomi or miqdor <= 0:
                continue

            _merge_save_product_and_order(
                user_id=user_id,
                branch=branch,
                model_cls=Aksessuar,
                category="Аксессуар",
                nomi=nomi,
                turi=turi or None,
                miqdor=miqdor,
                narx=narx,
                izoh=izoh,
                rasm=rasm,
            )

    return JsonResponse({"success": True, "message": "Aksessuarlar saqlandi", "redirectUrl": reverse("optika:index")})


@require_POST
def save_antik(request: HttpRequest):
    not_logged = _session_user_or_json_401(request)
    if not_logged:
        return not_logged

    payload = _parse_json_body(request)
    if not isinstance(payload, list) or not payload:
        return JsonResponse({"success": False, "message": "Hech narsa tanlanmadi!"}, status=400)

    user_id = _get_user_id(request)
    branch = _get_branch(request)

    with transaction.atomic():
        for item in payload:
            nomi = _clean_str(item.get("nomi"))
            miqdor = _to_int(item.get("miqdor"), 0)
            narx = _to_decimal_or_none(item.get("narx"))
            izoh = item.get("izoh") or ""
            turi = _clean_str(item.get("turi"))

            if not nomi or miqdor <= 0:
                continue

            _merge_save_product_and_order(
                user_id=user_id,
                branch=branch,
                model_cls=Antikompyuter,
                category="Антикомп",
                nomi=nomi,
                miqdor=miqdor,
                narx=narx,
                izoh=izoh,
                turi=turi or None,
            )

    return JsonResponse({"success": True, "message": "Antikompyuterlar saqlandi", "redirectUrl": reverse("optika:index")})


@require_POST
def save_gatoviy(request: HttpRequest):
    not_logged = _session_user_or_json_401(request)
    if not_logged:
        return not_logged

    payload = _parse_json_body(request)
    if not isinstance(payload, list) or not payload:
        return JsonResponse({"success": False, "message": "Hech narsa tanlanmadi!"}, status=400)

    user_id = _get_user_id(request)
    branch = _get_branch(request)

    with transaction.atomic():
        for item in payload:
            model_name = _clean_str(item.get("nomi"))  # from template: "nomi"
            dioptriya = _clean_str(item.get("dioptriya"))
            miqdor = _to_int(item.get("miqdor"), 0)
            izoh = item.get("izoh") or ""

            if not model_name or miqdor <= 0:
                continue

            # Gatoviy has both "model" and "nomi" – store the same name in both.
            _merge_save_product_and_order(
                user_id=user_id,
                branch=branch,
                model_cls=Gatoviy,
                category="Готовые",
                nomi=model_name,   # Gatoviy also has nomi field
                miqdor=miqdor,
                dioptriya=dioptriya or None,
                izoh=izoh,
                extra_fields={
                    "model": model_name,
                    "filial": branch,
                    "created_at": timezone.now(),
                },
            )

    return JsonResponse({"success": True, "message": "Gatoviylar saqlandi", "redirectUrl": reverse("optika:index")})


@require_POST
def save_oprava(request: HttpRequest):
    not_logged = _session_user_or_json_401(request)
    if not_logged:
        return not_logged

    payload = _parse_json_body(request)
    if not isinstance(payload, list) or not payload:
        return JsonResponse({"success": False, "message": "Hech narsa tanlanmadi!"}, status=400)

    user_id = _get_user_id(request)
    branch = _get_branch(request)

    with transaction.atomic():
        for item in payload:
            nomi = _clean_str(item.get("nomi"))
            turi = _clean_str(item.get("turi"))  # gender
            miqdor = _to_int(item.get("miqdor"), 0)
            izoh = item.get("izoh") or ""

            if not nomi or miqdor <= 0:
                continue

            # Important: include turi in merge key so "Ayol/Erkak" doesn't overwrite each other
            _merge_save_product_and_order(
                user_id=user_id,
                branch=branch,
                model_cls=Oprava,
                category="Оправа",
                nomi=nomi,
                turi=turi or None,
                miqdor=miqdor,
                izoh=izoh,
            )

    return JsonResponse({"success": True, "message": "Opravalar saqlandi", "redirectUrl": reverse("optika:index")})


# -----------------------------
# PROFILE page + edit/delete/send/pdf
# -----------------------------
@ensure_csrf_cookie
def profile_view(request):
    redir = _session_user_or_redirect(request)
    if redir:
        return redir

    user_id = _get_user_id(request)

    orders = Order.objects.filter(user_id=user_id, is_sent=False).order_by("-created_at")

    # Convert Orders -> DTO-style dicts so template behaves like ASP.NET
    profile_orders = []
    for o in orders:
        profile_orders.append({
            "id": o.product_id,          # IMPORTANT: product id (like ASP.NET item.Id)
            "order_id": o.id,            # IMPORTANT: order id (like ASP.NET item.OrderId)
            "category": o.category or "",
            "model": o.model or "",
            "dioptriya": o.dioptriya or "",
            "miqdor": o.miqdor or 0,
            "izoh": o.izoh or "",
            "created_at": o.created_at,
        })

    return render(request, "optika/profile.html", {
        "profile_orders": profile_orders,
        "full_name": _get_full_name(request),
        "branch": _get_branch(request),
        "role": request.session.get("Role"),
    })



@require_POST
def save_profile_row(request: HttpRequest):
    not_logged = _session_user_or_json_401(request)
    if not_logged:
        return not_logged

    data = _parse_json_body(request)
    if not isinstance(data, dict):
        return JsonResponse({"success": False, "message": "JSON xato formatda."}, status=400)

    row_id = _to_int(data.get("Id"), 0)
    miqdor = _to_int(data.get("Miqdor"), 0)
    izoh = data.get("Izoh") or "-"
    category = _clean_str(data.get("Category"))

    if row_id <= 0:
        return JsonResponse({"success": False, "message": "Id noto‘g‘ri."}, status=400)

    user_id = _get_user_id(request)

    order = Order.objects.filter(id=row_id, user_id=user_id, is_sent=False).first()
    if not order:
        return JsonResponse({"success": False, "message": "Buyurtma topilmadi."}, status=404)

    order.miqdor = max(0, miqdor)
    order.izoh = izoh
    order.save(update_fields=["miqdor", "izoh"])

    # Update product table too
    cat = category or (order.category or "")
    model_cls = CATEGORY_MODEL.get(cat)
    if model_cls:
        model_cls.objects.filter(id=order.product_id).update(miqdor=order.miqdor, izoh=order.izoh)

    return JsonResponse({"success": True})


@require_POST
def delete_rows(request: HttpRequest):
    not_logged = _session_user_or_json_401(request)
    if not_logged:
        return not_logged

    payload = _parse_json_body(request)
    if not isinstance(payload, list) or not payload:
        return JsonResponse({"success": False, "message": "Hech narsa tanlanmadi."}, status=400)

    user_id = _get_user_id(request)

    with transaction.atomic():
        for item in payload:
            row_id = _to_int(item.get("Id"), 0)
            if row_id <= 0:
                continue

            order = Order.objects.filter(id=row_id, user_id=user_id, is_sent=False).first()
            if not order:
                continue

            cat = order.category or _clean_str(item.get("Category"))
            model_cls = CATEGORY_MODEL.get(cat)

            # delete product row
            if model_cls:
                model_cls.objects.filter(id=order.product_id).delete()

            # delete order row
            order.delete()

    return JsonResponse({"success": True})


@require_POST
def download_orders_pdf(request: HttpRequest):
    not_logged = _session_user_or_json_401(request)
    if not_logged:
        return not_logged

    payload = _parse_json_body(request)
    if not isinstance(payload, list) or not payload:
        return JsonResponse({"success": False, "message": "Order list bo'sh."}, status=400)

    full_name = _get_full_name(request)
    branch    = _get_branch(request)

    # Build rows — № is first column (mirrors index = pageIndex * pageSize + 1 in C#)
    rows = []
    for idx, it in enumerate(payload, start=1):
        rows.append([
            str(idx),
            _clean_str(it.get("Category") or it.get("category") or "-") or "-",
            _clean_str(it.get("Model")    or it.get("model")    or ""),
            _clean_str(it.get("Dioptriya") or it.get("dioptriya") or ""),
            str(_to_int(it.get("Miqdor") or it.get("miqdor"), 0)),
            _clean_str(it.get("Izoh")    or it.get("izoh")    or ""),
        ])

    # Columns mirror C# RelativeColumn(0.5, 2, 3, 2, 1, 3)
    pdf_bytes = _build_table_pdf(
        full_name=full_name,
        branch=branch,
        columns=[
            ("№",        0.5),
            ("Category", 2),
            ("Model",    3),
            ("Dioptriya",2),
            ("Miqdor",   1),
            ("Izoh",     3),
        ],
        rows=rows,
        title_line1="Buyurtmalar ro'yxati",
    )

    now = datetime.now()
    filename = f"{branch}_{now.strftime('%d_%m_%Y')}.pdf"
    resp = HttpResponse(pdf_bytes, content_type="application/pdf")
    resp["Content-Disposition"] = f'attachment; filename="{filename}"'
    return resp


@require_POST
def mark_as_sent(request: HttpRequest):
    """
    Creates Archive + ArchiveItems from current orders, then clears them.
    Frontend sends: [orderId, orderId, ...]
    """
    not_logged = _session_user_or_json_401(request)
    if not_logged:
        return not_logged

    payload = _parse_json_body(request)
    if not isinstance(payload, list) or not payload:
        return JsonResponse({"success": False, "message": "Bo‘sh ro‘yxat."}, status=400)

    user_id = _get_user_id(request)
    branch = _get_branch(request)
    full_name = _get_full_name(request)

    order_ids = [i for i in [_to_int(x, 0) for x in payload] if i > 0]
    if not order_ids:
        return JsonResponse({"success": False, "message": "OrderId noto‘g‘ri."}, status=400)

    orders = list(Order.objects.filter(id__in=order_ids, user_id=user_id, is_sent=False))
    if not orders:
        return JsonResponse({"success": False, "message": "Buyurtmalar topilmadi."}, status=404)

    with transaction.atomic():
        archive = Archive.objects.create(
            filial=branch,
            user_full_name=full_name,
            created_at=timezone.now(),
            is_pdf_downloaded=True,       # user downloads before calling MarkAsSent in your UI
            is_telegram_shared=False,
        )

        # create archive items
        items = []
        for o in orders:
            items.append(ArchiveItem(
                archive=archive,
                category=o.category,
                model=o.model,
                dioptriya=o.dioptriya,
                miqdor=o.miqdor,
                izoh=o.izoh,
            ))
        ArchiveItem.objects.bulk_create(items)

        # delete product rows + delete orders (clear cart)
        for o in orders:
            model_cls = CATEGORY_MODEL.get(o.category or "")
            if model_cls:
                model_cls.objects.filter(id=o.product_id).delete()
            o.delete()

    return JsonResponse({"success": True, "message": "Buyurtmalar arxivlandi."})


# -----------------------------
# ARCHIVE page + download
# -----------------------------

@ensure_csrf_cookie
def archive_view(request: HttpRequest):
    redir = _session_user_or_redirect(request)
    if redir:
        return redir

    # Admin sees all, users see only their own full_name+branch (best-effort)
    role = request.session.get("Role")
    branch = _get_branch(request)
    full_name = _get_full_name(request)

    qs = Archive.objects.all()
    if role != "Admin":
        qs = qs.filter(filial=branch, user_full_name=full_name)

    archives = qs.order_by("-created_at")
    return render(request, "optika/archive.html", {"archives": archives})


def _sort_orders_like_csharp(items):
    """
    Mirrors HomeController.SortOrders:
      OrderBy category → OrderBy model
      → ThenBy: negatives group (0) before positives (1), unparseable last (2)
      → ThenBy: within negatives ascending by -d (= -1, -2, -3),
                within positives ascending by d (= 0.5, 1, 2)
    """
    def primary_key(it):
        cat   = it.get("category") or it.get("Category") or ""
        model = it.get("model")    or it.get("Model")    or ""
        d_str = it.get("dioptriya") or it.get("Dioptriya") or ""
        try:
            d = float(d_str)
            group  = 0 if d < 0 else 1
            within = -d if d < 0 else d   # negatives: -(-1)=1 < -(-2)=2 → -1,-2,-3
                                           # positives: 0.5 < 1 < 2
        except (ValueError, TypeError):
            group  = 2
            within = 0
        return (cat, model, group, within)

    return sorted(items, key=primary_key)


@require_POST
def download_archive_pdf(request: HttpRequest):
    not_logged = _session_user_or_json_401(request)
    if not_logged:
        return not_logged

    data = _parse_json_body(request)
    if not isinstance(data, dict):
        return JsonResponse({"success": False, "message": "JSON xato."}, status=400)

    archive_id = _to_int(data.get("id"), 0)
    if archive_id <= 0:
        return JsonResponse({"success": False, "message": "archive id xato."}, status=400)

    role      = request.session.get("Role")
    branch    = _get_branch(request)
    full_name = _get_full_name(request)

    archive = Archive.objects.filter(id=archive_id).first()
    if not archive:
        return JsonResponse({"success": False, "message": "Arxiv topilmadi."}, status=404)

    if role != "Admin" and (archive.filial != branch or archive.user_full_name != full_name):
        return JsonResponse({"success": False, "message": "Ruxsat yo'q."}, status=403)

    # Sort items — mirrors SortOrders() call in C#
    raw_items = [
        {
            "category": it.category or "",
            "model":    it.model    or "",
            "dioptriya": it.dioptriya or "",
            "miqdor":   it.miqdor   or 0,
            "izoh":     it.izoh     or "",
        }
        for it in archive.items.all()
    ]
    sorted_items = _sort_orders_like_csharp(raw_items)

    # Build rows with 1-based № (mirrors index = pageIndex * pageSize + 1)
    rows = []
    for idx, it in enumerate(sorted_items, start=1):
        rows.append([
            str(idx),
            it["category"] or "-",
            it["model"]    or "",
            it["dioptriya"] or "",
            str(it["miqdor"]),
            it["izoh"]     or "",
        ])

    # Header date = archive.created_at (NOT datetime.now() — mirrors archive.CreatedAt in C#)
    archive_dt = archive.created_at
    if hasattr(archive_dt, "tzinfo") and archive_dt.tzinfo:
        from django.utils import timezone as tz
        archive_dt = tz.localtime(archive_dt).replace(tzinfo=None)

    pdf_bytes = _build_table_pdf(
        full_name=archive.user_full_name or "-",
        branch=archive.filial or "-",
        columns=[
            ("№",        0.5),
            ("Category", 2),
            ("Model",    3),
            ("Dioptriya",2),
            ("Miqdor",   1),
            ("Izoh",     3),
        ],
        rows=rows,
        title_line1="Buyurtma arxivi",    # C#: "Buyurtma arxivi\n{UserFullName} ({Filial})"
        header_date=archive_dt,           # C#: archive.CreatedAt, not DateTime.Now
    )

    Archive.objects.filter(id=archive.id).update(is_pdf_downloaded=True)

    # filename mirrors C#: {Filial}_{CreatedAt:dd_MM_yyyy}.pdf
    filename = f"{archive.filial or 'archive'}_{archive_dt.strftime('%d_%m_%Y')}.pdf"
    resp = HttpResponse(pdf_bytes, content_type="application/pdf")
    resp["Content-Disposition"] = f'attachment; filename="{filename}"'
    return resp

# -----------------------------
# ADMIN custom panel endpoints (admin.html)
# -----------------------------

@ensure_csrf_cookie
def admin_page(request: HttpRequest):
    redir = _session_user_or_redirect(request)
    if redir:
        return redir
    redir2 = _admin_or_redirect(request)
    if redir2:
        return redir2
    return render(request, "optika/admin.html")


@require_GET
def get_archives(request: HttpRequest):
    not_logged = _session_user_or_json_401(request)
    if not_logged:
        return not_logged
    not_admin = _admin_or_403(request)
    if not_admin:
        return not_admin

    archives = Archive.objects.all().order_by("-created_at")
    out = []
    for a in archives:
        out.append({
            "id": a.id,
            "filial": a.filial,
            "userFullName": a.user_full_name,
            "createdAt": a.created_at.isoformat(),
            "isTelegramShared": a.is_telegram_shared,
            "isPdfDownloaded": a.is_pdf_downloaded,
        })
    return JsonResponse(out, safe=False)


@require_GET
def get_archive_items(request: HttpRequest):
    not_logged = _session_user_or_json_401(request)
    if not_logged:
        return not_logged
    not_admin = _admin_or_403(request)
    if not_admin:
        return not_admin

    archive_id = _to_int(request.GET.get("archiveId"), 0)
    if archive_id <= 0:
        return JsonResponse([], safe=False)

    items = ArchiveItem.objects.filter(archive_id=archive_id).order_by("id")
    out = []
    for it in items:
        out.append({
            "category": it.category,
            "model": it.model,
            "dioptriya": it.dioptriya,
            "miqdor": it.miqdor,
            "izoh": it.izoh,
        })
    return JsonResponse(out, safe=False)


@require_POST
def delete_archive(request: HttpRequest):
    not_logged = _session_user_or_json_401(request)
    if not_logged:
        return not_logged
    not_admin = _admin_or_403(request)
    if not_admin:
        return not_admin

    data = _parse_json_body(request)
    if not isinstance(data, dict):
        return JsonResponse({"success": False, "message": "JSON xato."}, status=400)

    archive_id = _to_int(data.get("ArchiveId"), 0)
    if archive_id <= 0:
        return JsonResponse({"success": False, "message": "ArchiveId xato."}, status=400)

    Archive.objects.filter(id=archive_id).delete()
    return JsonResponse({"success": True})


@require_POST
def clear_all_archives(request: HttpRequest):
    not_logged = _session_user_or_json_401(request)
    if not_logged:
        return not_logged
    not_admin = _admin_or_403(request)
    if not_admin:
        return not_admin

    Archive.objects.all().delete()
    return JsonResponse({"success": True, "message": "Barcha arxivlar o‘chirildi."})


def _dioptriya_sort_key(d_str: str):
    """
    Mirrors the C# double ThenBy/ThenByDescending dioptriya sort:
      positives first  → ascending  (0, 0.25, 0.5 …)
      negatives after  → ascending by absolute value  (-0.25, -0.5, -1.0 …)
    """
    try:
        d = float(d_str)
        return (0, d) if d >= 0 else (1, abs(d))
    except (ValueError, TypeError):
        return (2, 0)


def _build_archives_pdf(
    umumiy_rows: list,        # already sorted/grouped summary rows  [cat, model, diop, jami, izoh]
    filial_groups: dict,      # { filial_name: [[cat, model, diop, miqdor, izoh], ...] }
    now: datetime,
) -> bytes:
    """
    Two-section PDF mirroring the two container.Page() blocks in C#:
      Section 1 — Umumiy Jamlanma   (6 columns)
      Section 2 — Filial kesimida   (7 columns, colour-coded per filial)
    """
    font = _try_register_cyrillic_font()
    buf  = io.BytesIO()
    page_w, page_h = A4
    margin = 56.7          # 20 mm — matches page.Margin(20)
    c = canvas.Canvas(buf, pagesize=A4)

    available_w = page_w - 2 * margin

    # ── shared helpers ────────────────────────────────────────────────────────

    def resolve_widths(weights):
        total = sum(weights)
        return [available_w * w / total for w in weights]

    def draw_shared_header():
        """Mirrors the identical Header() on both pages."""
        y = page_h - margin
        try:
            c.setFont(font + "-Bold", 14)
        except Exception:
            c.setFont(font, 14)
        c.setFillColor(BLUE_DARKEN2)
        c.drawString(margin, y, "Barcha Buyurtmalar")

        c.setFont(font, FONT_SZ)
        c.setFillColor(HexColor("#000000"))
        c.drawRightString(page_w - margin, y, now.strftime("%d/%m/%Y %H:%M"))
        return y - 20   # gap below header before content starts

    def draw_footer():
        c.setFont(font, FONT_SZ)
        c.setFillColor(HexColor("#000000"))
        c.drawRightString(page_w - margin, margin * 0.5,
                          f"© {now.year} neeoptika.uz")

    def draw_col_headers(y, col_names, col_widths):
        """Header row — fixed height ROW_H, bold, #E0F7FA background."""
        x = margin
        for name, w in zip(col_names, col_widths):
            _draw_cell(c, x, y, w, ROW_H, name, font, FONT_SZ,
                       bg=HEADER_BG, bold=True)
            x += w
        return y - ROW_H

    def draw_row(y, values, col_widths, bg):
        """
        Draw one data row with dynamic height based on the tallest cell.
        Returns new y (y minus the row height used).
        """
        active_font = font   # non-bold for data rows

        # Pre-calculate height needed for every cell in this row
        row_height = ROW_H
        for idx, w in enumerate(col_widths):
            text = str(values[idx]) if idx < len(values) else ""
            lines = _wrap_text(text, active_font, FONT_SZ, w)
            row_height = max(row_height, _cell_h(len(lines)))

        # Now draw all cells using the agreed row_height
        x = margin
        for idx, w in enumerate(col_widths):
            text = str(values[idx]) if idx < len(values) else ""
            _draw_cell(c, x, y, w, row_height, text, font, FONT_SZ, bg=bg)
            x += w

        return y - row_height

    def ensure_space(y, needed=ROW_H + 4):
        """Start a fresh page if there isn't enough vertical room."""
        if y < margin + needed:
            c.showPage()
            draw_footer()
            return page_h - margin   # fresh y at top (no shared header on continuation pages)
        return y

    # ═══════════════════════════════════════════════════════════════════════════
    # PAGE 1 — Umumiy Jamlanma
    # ═══════════════════════════════════════════════════════════════════════════
    # Columns: №(1) | Kategoriya(2.5) | Model(3.5) | Dioptriya(1.5) | Jami(1.5) | Izoh(4)
    weights_1  = [1, 2.5, 3.5, 1.5, 1.5, 4]
    col_w_1    = resolve_widths(weights_1)
    col_names_1 = ["№", "Kategoriya", "Model", "Dioptriya", "Jami miqdor", "Izoh"]

    y = draw_shared_header()
    draw_footer()

    # Sub-title: "📊 Umumiy Jamlanma"
    try:
        c.setFont(font + "-Bold", 13)
    except Exception:
        c.setFont(font, 13)
    c.setFillColor(HexColor("#000000"))
    c.drawString(margin, y, "Umumiy Jamlanma")
    y -= 18   # PaddingBottom(10) equivalent

    y = draw_col_headers(y, col_names_1, col_w_1)

    for idx, row in enumerate(umumiy_rows, start=1):
        y = ensure_space(y)
        # C# uses index % 2 == 0 → white, else grey (1-based index)
        bg = white if idx % 2 == 0 else GREY_LIGHTEN3
        y = draw_row(y, [str(idx)] + row, col_w_1, bg)

# ═══════════════════════════════════════════════════════════════════════════
    # PAGE 2+ — Filial kesimida  (one page per filial)
    # ═══════════════════════════════════════════════════════════════════════════
    weights_2   = [1, 2.5, 2.5, 4, 1.5, 1.5, 3.5]
    col_w_2     = resolve_widths(weights_2)
    col_names_2 = ["№", "Filial", "Kategoriya", "Model", "Dioptriya", "Miqdor", "Izoh"]

    global_idx  = 1
    color_cycle = 0

    for filial_idx, (filial_name, filial_rows) in enumerate(filial_groups.items()):
        bg = FILIAL_COLORS[color_cycle % len(FILIAL_COLORS)]
        color_cycle += 1

        # ── Every filial starts on a fresh page ───────────────────────────────
        c.showPage()                          # always — first filial also gets its own page
        y = draw_shared_header()
        draw_footer()

        # Sub-title "🏬 Filial kesimida" on every filial page for clarity
        try:
            c.setFont(font + "-Bold", 13)
        except Exception:
            c.setFont(font, 13)
        c.setFillColor(HexColor("#000000"))
        c.drawString(margin, y, "Filial kesimida")
        y -= 18

        # Filial name label — blue bold
        try:
            c.setFont(font + "-Bold", 12)
        except Exception:
            c.setFont(font, 12)
        c.setFillColor(BLUE_DARKEN2)
        c.drawString(margin, y, f"{filial_name}")
        y -= 16   # PaddingBottom(5)

        y = draw_col_headers(y, col_names_2, col_w_2)

        for row in filial_rows:
            # Estimate height before drawing to check for overflow
            row_height = ROW_H
            for idx, cw in enumerate(col_w_2):
                text = str(row[idx]) if idx < len(row) else ""
                lines = _wrap_text(text, font, FONT_SZ, cw)
                row_height = max(row_height, _cell_h(len(lines)))

            if y < margin + row_height + 4:
                c.showPage()
                draw_footer()
                y = page_h - margin
                try:
                    c.setFont(font + "-Bold", 12)
                except Exception:
                    c.setFont(font, 12)
                c.setFillColor(BLUE_DARKEN2)
                c.drawString(margin, y, f"{filial_name} (davomi)")
                y -= 16
                y = draw_col_headers(y, col_names_2, col_w_2)

            y = draw_row(y, [str(global_idx)] + row, col_w_2, bg)
            global_idx += 1

    c.save()
    return buf.getvalue()

@require_POST
def download_all_archives_pdf(request: HttpRequest):
    not_logged = _session_user_or_json_401(request)
    if not_logged:
        return not_logged
    not_admin = _admin_or_403(request)
    if not_admin:
        return not_admin

    # ── fetch all items with their archive (mirrors .Include(a => a.Archive)) ──
    all_items = list(
        ArchiveItem.objects
        .select_related("archive")
        .all()
    )

    # lastCategory — mirrors C# OrderByDescending(x => x.Archive.CreatedAt).FirstOrDefault()?.Category
    last_item = max(all_items, key=lambda x: x.archive.created_at, default=None)
    last_category = last_item.category if last_item else None

    def base_sort_key(item):
        """Mirrors the shared ordering applied before both GroupBy calls."""
        return (
            0 if item.category == last_category else 1,  # lastCategory first
            item.category or "",
            item.model or "",
            _dioptriya_sort_key(item.dioptriya or ""),
        )

    sorted_items = sorted(all_items, key=base_sort_key)

    # ── Umumiy Jamlanma — mirrors first GroupBy + Select ─────────────────────
    from itertools import groupby
    from collections import defaultdict

    umumiy_rows = []
    # group by (Category, Model, Dioptriya)
    for key, group_iter in groupby(
        sorted_items,
        key=lambda x: (x.category or "", x.model or "", x.dioptriya or "")
    ):
        group = list(group_iter)
        category, model, dioptriya = key
        jami  = sum(i.miqdor or 0 for i in group)
        izoh  = ", ".join(
            {i.izoh for i in group if i.izoh and i.izoh.strip()}
        ) or "-"
        umumiy_rows.append([
            category or "-",
            model    or "-",
            dioptriya or "-",
            str(jami),
            izoh,
        ])

    # ── Filial kesimi — mirrors second GroupBy + Select + OrderBy(Filial) ────
    # group by (Filial, Category, Model, Dioptriya)
    filial_flat = []
    for key, group_iter in groupby(
        sorted_items,
        key=lambda x: (
            x.archive.filial or "",
            x.category or "",
            x.model or "",
            x.dioptriya or "",
        )
    ):
        group = list(group_iter)
        filial, category, model, dioptriya = key
        miqdor = sum(i.miqdor or 0 for i in group)
        izoh   = ", ".join(
            {i.izoh for i in group if i.izoh and i.izoh.strip()}
        ) or "-"
        filial_flat.append({
            "filial":    filial,
            "category":  category or "-",
            "model":     model    or "-",
            "dioptriya": dioptriya or "-",
            "miqdor":    str(miqdor),
            "izoh":      izoh,
        })

    # OrderBy(x => x.Filial) at the end
    filial_flat.sort(key=lambda x: x["filial"])

    # Build {filial: [rows]} dict preserving order (mirrors GroupBy(x => x.Filial))
    filial_groups: dict[str, list] = {}
    for item in filial_flat:
        filial_groups.setdefault(item["filial"], []).append([
            item["category"],
            item["model"],
            item["dioptriya"],
            item["miqdor"],
            item["izoh"],
        ])

    # ── generate PDF ──────────────────────────────────────────────────────────
    now = datetime.now()
    pdf_bytes = _build_archives_pdf(
        umumiy_rows=umumiy_rows,
        filial_groups=filial_groups,
        now=now,
    )

    # Mark all archives as downloaded — mirrors C# block at the end
    Archive.objects.all().update(is_pdf_downloaded=True)

    resp = HttpResponse(pdf_bytes, content_type="application/pdf")
    resp["Content-Disposition"] = 'attachment; filename="Barcha_Buyurtmalar.pdf"'
    return resp

@require_POST
def share_all_archives_telegram(request: HttpRequest):
    not_logged = _session_user_or_json_401(request)
    if not_logged:
        return not_logged
    not_admin = _admin_or_403(request)
    if not_admin:
        return not_admin

    token = getattr(settings, "TELEGRAM_BOT_TOKEN", None)
    if not token:
        return JsonResponse({"success": False, "message": "TELEGRAM_BOT_TOKEN topilmadi."}, status=500)

    all_items = list(ArchiveItem.objects.select_related("archive").all())
    if not all_items:
        return JsonResponse({"success": False, "message": "Arxiv bo'sh."}, status=400)

    chats = list(TelegramChat.objects.all())
    if not chats:
        return JsonResponse({"success": False, "message": "Telegram chat IDlar yo'q."}, status=400)

    # ── Build PDF using SAME logic as download_all_archives_pdf ──────────────
    last_item     = max(all_items, key=lambda x: x.archive.created_at, default=None)
    last_category = last_item.category if last_item else None

    def base_sort_key(item):
        return (
            0 if item.category == last_category else 1,
            item.category or "",
            item.model    or "",
            _dioptriya_sort_key(item.dioptriya or ""),
        )

    sorted_items = sorted(all_items, key=base_sort_key)

    from itertools import groupby

    umumiy_rows = []
    for key, group_iter in groupby(
        sorted_items,
        key=lambda x: (x.category or "", x.model or "", x.dioptriya or "")
    ):
        group = list(group_iter)
        category, model, dioptriya = key
        jami = sum(i.miqdor or 0 for i in group)
        izoh = ", ".join(
            {i.izoh for i in group if i.izoh and i.izoh.strip()}
        ) or "-"
        umumiy_rows.append([category or "-", model or "-", dioptriya or "-", str(jami), izoh])

    filial_flat = []
    for key, group_iter in groupby(
        sorted_items,
        key=lambda x: (x.archive.filial or "", x.category or "", x.model or "", x.dioptriya or "")
    ):
        group = list(group_iter)
        filial, category, model, dioptriya = key
        miqdor = sum(i.miqdor or 0 for i in group)
        izoh   = ", ".join(
            {i.izoh for i in group if i.izoh and i.izoh.strip()}
        ) or "-"
        filial_flat.append({
            "filial": filial, "category": category or "-", "model": model or "-",
            "dioptriya": dioptriya or "-", "miqdor": str(miqdor), "izoh": izoh,
        })

    filial_flat.sort(key=lambda x: x["filial"])
    filial_groups: dict = {}
    for item in filial_flat:
        filial_groups.setdefault(item["filial"], []).append([
            item["category"], item["model"], item["dioptriya"], item["miqdor"], item["izoh"],
        ])

    now = datetime.now()
    pdf_bytes = _build_archives_pdf(           # same function as download_all_archives_pdf
        umumiy_rows=umumiy_rows,
        filial_groups=filial_groups,
        now=now,
    )

    # ── Send to Telegram ──────────────────────────────────────────────────────
    try:
        import requests as req_lib
    except ImportError:
        return JsonResponse({"success": False, "message": "pip install requests"}, status=500)

    url      = f"https://api.telegram.org/bot{token}/sendDocument"
    ok_count = 0
    filename = f"Buyurtmalar_{now.strftime('%Y-%m-%d_%H-%M')}.pdf"

    for ch in chats:
        try:
            r = req_lib.post(
                url,
                data={"chat_id": ch.chat_id, "caption": "📦 Barcha buyurtmalar PDF fayli"},
                files={"document": (filename, io.BytesIO(pdf_bytes), "application/pdf")},
                timeout=30,
            )
            if r.ok and r.json().get("ok"):
                ok_count += 1
        except Exception:
            continue

    if ok_count == 0:
        return JsonResponse({"success": False, "message": "Telegramga yuborilmadi."}, status=500)

    Archive.objects.all().update(is_telegram_shared=True)
    return JsonResponse({"success": True, "message": f"Yuborildi ({ok_count}/{len(chats)})"})

# -----------------------------
# FEEDBACK: user + admin feedback
# -----------------------------

@ensure_csrf_cookie
def feedback_page(request: HttpRequest):
    redir = _session_user_or_redirect(request)
    if redir:
        return redir
    return render(request, "optika/feedback.html")


@require_POST
def send_feedback(request: HttpRequest):
    not_logged = _session_user_or_json_401(request)
    if not_logged:
        return not_logged

    data = _parse_json_body(request)
    if not isinstance(data, dict):
        return JsonResponse({"success": False, "message": "JSON xato."}, status=400)

    message_text = _clean_str(data.get("message"))
    phone = _clean_str(data.get("phone"))

    if not message_text:
        return JsonResponse({"success": False, "message": "Xabar bo‘sh bo‘lmasin."}, status=400)

    FeedBack.objects.create(
        full_name=_get_full_name(request),
        phone=phone or None,
        message=message_text,
        created_at=timezone.now(),
    )

    return JsonResponse({"success": True})


@ensure_csrf_cookie
def admin_feedback_page(request: HttpRequest):
    redir = _session_user_or_redirect(request)
    if redir:
        return redir
    redir2 = _admin_or_redirect(request)
    if redir2:
        return redir2

    feedbacks = FeedBack.objects.all().order_by("-created_at")
    return render(request, "optika/admin_feedback.html", {"feedbacks": feedbacks})


@require_POST
def clear_all_feedback(request: HttpRequest):
    not_logged = _session_user_or_json_401(request)
    if not_logged:
        return not_logged
    not_admin = _admin_or_403(request)
    if not_admin:
        return not_admin

    FeedBack.objects.all().delete()
    messages.success(request, "Barcha feedbacklar o‘chirildi.")
    return redirect("optika:admin_feedback_page")


def _build_feedback_pdf(feedbacks) -> bytes:
    """
    Mirrors HomeController.ExportToPdf exactly:
    - Margin 30, centered bold title FontSize 18
    - Header BG #DDEEFF (not #E0F7FA)
    - Data border 0.5 (not 1), zebra #FFFFFF / #F8F9FA
    - Footer: "Sahifa yaratilgan: dd.MM.yyyy HH:mm", color #777
    - Columns: Ism(2) | Telefon(2) | Taklif matni(5) | Sana(3)
    """
    font   = _try_register_cyrillic_font()
    buf    = io.BytesIO()
    now    = datetime.now()
    page_w, page_h = A4
    margin = 85.05   # 30 mm in points — matches page.Margin(30)
    available_w = page_w - 2 * margin

    weights    = [2, 2, 5, 3]
    total_w    = sum(weights)
    col_widths = [available_w * w / total_w for w in weights]
    col_names  = ["Ism Familiya", "Telefon", "Taklif matni", "Sana"]

    HEADER_BG_FB  = HexColor("#DDEEFF")   # feedback-specific header colour
    ZEBRA_WHITE   = HexColor("#FFFFFF")
    ZEBRA_GREY_FB = HexColor("#F8F9FA")   # feedback-specific zebra colour
    FOOTER_GREY   = HexColor("#777777")
    BORDER_THIN   = 0.5

    c = canvas.Canvas(buf, pagesize=A4)

    def draw_cell_fb(x, y, w, h, text, bg, bold=False, border=BORDER_THIN):
        if bg:
            c.setFillColor(bg)
            c.rect(x, y - h, w, h, stroke=0, fill=1)
        c.setStrokeColor(HexColor("#000000"))
        c.setLineWidth(border)
        c.rect(x, y - h, w, h, stroke=1, fill=0)
        c.setLineWidth(1)  # reset
        c.setFillColor(HexColor("#000000"))
        try:
            c.setFont(font + ("-Bold" if bold else ""), 10)
        except Exception:
            c.setFont(font, 10)
        max_chars = max(5, int(w / (10 * 0.55)))
        c.drawString(x + 5, y - h + 5, _truncate(text, max_chars))

    # ── Title — Bold, FontSize 18, centered ──────────────────────────────────
    y = page_h - margin
    try:
        c.setFont(font + "-Bold", 18)
    except Exception:
        c.setFont(font, 18)
    c.setFillColor(HexColor("#000000"))
    c.drawCentredString(page_w / 2, y, "Foydalanuvchi Takliflari")
    y -= 28   # PaddingVertical(10) equivalent gap

    # ── Table header ─────────────────────────────────────────────────────────
    x = margin
    for name, w in zip(col_names, col_widths):
        draw_cell_fb(x, y, w, ROW_H, name, HEADER_BG_FB, bold=True, border=1)
        x += w
    y -= ROW_H

    # ── Data rows ─────────────────────────────────────────────────────────────
    for idx, fb in enumerate(feedbacks, start=1):
        # Page overflow check
        if y < margin + ROW_H + 20:
            c.showPage()
            y = page_h - margin

        bg = ZEBRA_WHITE if idx % 2 == 0 else ZEBRA_GREY_FB

        # Column order mirrors C#: FullName | Phone | Message | CreatedAt
        values = [
            fb.full_name or "-",
            fb.phone     or "-",
            fb.message   or "-",
            fb.created_at.strftime("%d.%m.%Y %H:%M"),
        ]

        x = margin
        for val, w in zip(values, col_widths):
            draw_cell_fb(x, y, w, ROW_H, val, bg, border=BORDER_THIN)
            x += w
        y -= ROW_H

    # ── Footer — right-aligned, color #777 ───────────────────────────────────
    c.setFont(font, 10)
    c.setFillColor(FOOTER_GREY)
    c.drawRightString(page_w - margin, margin * 0.5,
                      f"Sahifa yaratilgan: {now.strftime('%d.%m.%Y %H:%M')}")

    c.save()
    return buf.getvalue()


@require_GET
def export_feedback_pdf(request: HttpRequest):
    redir = _session_user_or_redirect(request)
    if redir:
        return redir
    if request.session.get("Role") != "Admin":
        return redirect("optika:index")

    feedbacks = list(FeedBack.objects.all().order_by("-created_at"))
    if not feedbacks:
        messages.error(request, "PDF yaratish uchun takliflar topilmadi.")
        return redirect("optika:admin_feedback_page")

    pdf_bytes = _build_feedback_pdf(feedbacks)

    now = datetime.now()
    resp = HttpResponse(pdf_bytes, content_type="application/pdf")
    resp["Content-Disposition"] = f'attachment; filename="Takliflar_{now.strftime("%Y_%m_%d")}.pdf"'
    return resp

# -----------------------------
# USERS management + Telegram chat IDs (admin)
# -----------------------------

@ensure_csrf_cookie
@require_http_methods(["GET", "POST"])
def add_user_page_and_create(request: HttpRequest):
    """
    GET  -> render add_user.html with list
    POST -> create user
    """
    redir = _session_user_or_redirect(request)
    if redir:
        return redir
    redir2 = _admin_or_redirect(request)
    if redir2:
        return redir2

    if request.method == "POST":
        full_name = _clean_str(request.POST.get("FullName"))
        phone = _clean_str(request.POST.get("Phone"))
        user_id = _clean_str(request.POST.get("UserId")).lower()
        parol = _clean_str(request.POST.get("Parol"))
        role = _clean_str(request.POST.get("Role")) or "User"

        if not full_name or not user_id or not parol:
            messages.error(request, "FullName, UserId, Parol majburiy.")
            return redirect("optika:add_user")

        if Users.objects.filter(user_id=user_id).exists():
            messages.error(request, "Bunday UserId mavjud.")
            return redirect("optika:add_user")

        u = Users(full_name=full_name, phone=phone, user_id=user_id, role=role)
        u.set_password(parol)
        u.save()
        messages.success(request, "Foydalanuvchi qo‘shildi.")
        return redirect("optika:add_user")

    users = Users.objects.all().order_by("role", "full_name")
    return render(request, "optika/add_user.html", {"users": users})


@require_POST
def edit_user(request: HttpRequest):
    redir = _session_user_or_redirect(request)
    if redir:
        return redir
    if request.session.get("Role") != "Admin":
        return redirect("optika:index")

    uid = _to_int(request.POST.get("Id"), 0)
    user = Users.objects.filter(id=uid).first()
    if not user:
        messages.error(request, "User topilmadi.")
        return redirect("optika:add_user")

    full_name = _clean_str(request.POST.get("FullName"))
    phone = _clean_str(request.POST.get("Phone"))
    user_id_val = _clean_str(request.POST.get("UserId")).lower()
    new_pass = _clean_str(request.POST.get("Parol"))
    role = _clean_str(request.POST.get("Role")) or "User"

    if user_id_val and user_id_val != user.user_id:
        if Users.objects.filter(user_id=user_id_val).exclude(id=user.id).exists():
            messages.error(request, "Bunday UserId mavjud.")
            return redirect("optika:add_user")
        user.user_id = user_id_val

    user.full_name = full_name or user.full_name
    user.phone = phone
    user.role = role

    if new_pass:
        user.set_password(new_pass)

    user.save()
    messages.success(request, "User yangilandi.")
    return redirect("optika:add_user")


@require_GET
def delete_user(request: HttpRequest):
    redir = _session_user_or_redirect(request)
    if redir:
        return redir
    if request.session.get("Role") != "Admin":
        return redirect("optika:index")

    uid = _to_int(request.GET.get("id"), 0)
    if uid > 0:
        Users.objects.filter(id=uid).delete()
        messages.success(request, "User o‘chirildi.")
    return redirect("optika:add_user")


@ensure_csrf_cookie
@require_http_methods(["GET"])
def telegram_chat_id_page(request: HttpRequest):
    redir = _session_user_or_redirect(request)
    if redir:
        return redir
    redir2 = _admin_or_redirect(request)
    if redir2:
        return redir2

    chats = TelegramChat.objects.all().order_by("full_name")
    return render(request, "optika/telegram_chat_id.html", {"chats": chats})


@require_POST
def add_chat(request: HttpRequest):
    redir = _session_user_or_redirect(request)
    if redir:
        return redir
    if request.session.get("Role") != "Admin":
        return redirect("optika:index")

    full_name = _clean_str(request.POST.get("FullName"))
    chat_id = _clean_str(request.POST.get("ChatId"))

    if not full_name or not chat_id:
        messages.error(request, "FullName va ChatId majburiy.")
        return redirect("optika:telegram_chat_id_page")

    if TelegramChat.objects.filter(chat_id=chat_id).exists():
        messages.error(request, "Bu ChatId mavjud.")
        return redirect("optika:telegram_chat_id_page")

    TelegramChat.objects.create(full_name=full_name, chat_id=chat_id)
    messages.success(request, "Chat ID qo‘shildi.")
    return redirect("optika:telegram_chat_id_page")


@require_POST
def delete_chat(request: HttpRequest):
    redir = _session_user_or_redirect(request)
    if redir:
        return redir
    if request.session.get("Role") != "Admin":
        return redirect("optika:index")

    cid = _to_int(request.POST.get("id"), 0)
    if cid > 0:
        TelegramChat.objects.filter(id=cid).delete()
        messages.success(request, "Chat ID o‘chirildi.")
    return redirect("optika:telegram_chat_id_page")
