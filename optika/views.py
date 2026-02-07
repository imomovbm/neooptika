import io
import json
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional, Tuple, Type

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.hashers import check_password, make_password
from django.db import transaction
from django.http import (
    HttpRequest,
    HttpResponse,
    JsonResponse,
)
from django.urls import reverse
from django.shortcuts import render, redirect
from django.utils import timezone
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_http_methods, require_POST, require_GET

from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

from .models import (
    Users, Order,
    Rangsiz, Rangli, Kapliya, Aksessuar, Antikompyuter, Oprava, Gatoviy,
    Archive, ArchiveItem,
    FeedBack, TelegramChat
)


# -----------------------------
# Session helpers
# -----------------------------

def _session_user_or_redirect(request: HttpRequest):
    if not request.session.get("UserId"):
        return redirect("login")
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
        return redirect("index")
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

_PDF_FONT_NAME = "Helvetica"


def _try_register_cyrillic_font() -> str:
    """
    Tries to register DejaVuSans for Cyrillic text.
    If not found, fall back to Helvetica.
    """
    global _PDF_FONT_NAME
    if _PDF_FONT_NAME != "Helvetica":
        return _PDF_FONT_NAME

    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSansCondensed.ttf",
    ]
    for path in candidates:
        try:
            pdfmetrics.registerFont(TTFont("DejaVuSans", path))
            _PDF_FONT_NAME = "DejaVuSans"
            return _PDF_FONT_NAME
        except Exception:
            continue

    _PDF_FONT_NAME = "Helvetica"
    return _PDF_FONT_NAME


def _truncate(text: str, max_len: int) -> str:
    text = text or ""
    return text if len(text) <= max_len else text[: max_len - 1] + "…"


def _build_table_pdf(
    title: str,
    header_lines: List[str],
    columns: List[Tuple[str, int]],  # (name, width)
    rows: List[List[str]],
) -> bytes:
    font = _try_register_cyrillic_font()
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    width, height = A4

    margin_x = 40
    y = height - 40

    def new_page():
        nonlocal y
        c.showPage()
        c.setFont(font, 10)
        y = height - 40

    # Title
    c.setFont(font, 14)
    c.drawString(margin_x, y, title)
    y -= 22

    # Header lines
    c.setFont(font, 10)
    for line in header_lines:
        c.drawString(margin_x, y, line)
        y -= 14
    y -= 8

    # Table header
    col_x = margin_x
    c.setFont(font, 10)
    c.setLineWidth(1)

    def draw_table_header():
        nonlocal y
        # If not enough space, go new page and redraw header
        if y < 80:
            new_page()
            # redraw title? not necessary; but redraw table header
        c.setFont(font, 10)
        x = margin_x
        c.rect(margin_x, y - 18, sum(w for _, w in columns), 18, stroke=1, fill=0)
        for name, w in columns:
            c.drawString(x + 3, y - 13, _truncate(name, 30))
            x += w
        y -= 18

    draw_table_header()

    # Rows
    for r in rows:
        if y < 60:
            new_page()
            draw_table_header()

        x = margin_x
        row_h = 18
        c.rect(margin_x, y - row_h, sum(w for _, w in columns), row_h, stroke=1, fill=0)
        for idx, (_, w) in enumerate(columns):
            cell_text = r[idx] if idx < len(r) else ""
            # per-cell truncation depending on width
            approx = max(10, int(w / 6))  # rough char fit
            c.drawString(x + 3, y - 13, _truncate(cell_text, approx))
            x += w
        y -= row_h

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
    """
    GET  -> render login page
    POST -> validate and set session, return JSON
    """
    if request.method == "GET":
        return render(request, "optika/login.html")

    user_id = _clean_str(request.POST.get("userId"))
    password = _clean_str(request.POST.get("password"))
    branch = _clean_str(request.POST.get("branch"))

    if not user_id or not password:
        return JsonResponse({"success": False, "message": "ID va parolni kiriting!"})

    try:
        user = Users.objects.get(user_id=user_id)
    except Users.DoesNotExist:
        return JsonResponse({"success": False, "message": "Login yoki parol noto‘g‘ri!"})

    # check hashed first; if DB has plain text, upgrade on first login
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
        return JsonResponse({"success": False, "message": "Login yoki parol noto‘g‘ri!"})

    request.session["UserId"] = user.user_id
    request.session["FullName"] = user.full_name
    request.session["Role"] = user.role
    if branch:
        request.session["Branch"] = branch

    return JsonResponse({"success": True})


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
    """
    Receives list of orders from frontend, generates PDF.
    """
    not_logged = _session_user_or_json_401(request)
    if not_logged:
        return not_logged

    payload = _parse_json_body(request)
    if not isinstance(payload, list) or not payload:
        return JsonResponse({"success": False, "message": "Order list bo‘sh."}, status=400)

    user_id = _get_user_id(request)
    branch = _get_branch(request)
    full_name = _get_full_name(request)

    # Try to use DB orders (more reliable)
    ids = []
    for it in payload:
        oid = _to_int(it.get("Id") or it.get("OrderId"), 0)
        if oid > 0:
            ids.append(oid)

    orders = list(Order.objects.filter(id__in=ids, user_id=user_id, is_sent=False)) if ids else []
    if not orders:
        # fallback: use payload directly
        rows = []
        for it in payload:
            rows.append([
                _clean_str(it.get("Category") or "-"),
                _clean_str(it.get("Model") or it.get("model") or "-"),
                _clean_str(it.get("Dioptriya") or it.get("dioptriya") or "-"),
                str(_to_int(it.get("Miqdor") or it.get("miqdor"), 0)),
                _clean_str(it.get("Izoh") or it.get("izoh") or "-"),
            ])
    else:
        # build from DB
        rows = []
        for o in orders:
            rows.append([
                o.category or "-",
                o.model or "-",
                o.dioptriya or "-",
                str(o.miqdor or 0),
                o.izoh or "-",
            ])

    pdf_bytes = _build_table_pdf(
        title="Buyurtma (Optika)",
        header_lines=[
            f"Ism: {full_name}",
            f"Filial: {branch}",
            f"Sana: {timezone.localtime(timezone.now()).strftime('%Y-%m-%d %H:%M')}",
        ],
        columns=[
            ("Kategoriya", 95),
            ("Model", 170),
            ("Dioptriya", 70),
            ("Miqdor", 55),
            ("Izoh", 125),
        ],
        rows=rows,
    )

    resp = HttpResponse(pdf_bytes, content_type="application/pdf")
    resp["Content-Disposition"] = 'attachment; filename="order.pdf"'
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


@require_POST
def download_archive_pdf(request: HttpRequest):
    """
    POST JSON: { id: archiveId }
    Used by templates/optika/archive.html (button calls /Home/DownloadPdf)
    """
    not_logged = _session_user_or_json_401(request)
    if not_logged:
        return not_logged

    data = _parse_json_body(request)
    if not isinstance(data, dict):
        return JsonResponse({"success": False, "message": "JSON xato."}, status=400)

    archive_id = _to_int(data.get("id"), 0)
    if archive_id <= 0:
        return JsonResponse({"success": False, "message": "archive id xato."}, status=400)

    role = request.session.get("Role")
    branch = _get_branch(request)
    full_name = _get_full_name(request)

    archive = Archive.objects.filter(id=archive_id).first()
    if not archive:
        return JsonResponse({"success": False, "message": "Arxiv topilmadi."}, status=404)

    if role != "Admin" and (archive.filial != branch or archive.user_full_name != full_name):
        return JsonResponse({"success": False, "message": "Ruxsat yo‘q."}, status=403)

    items = list(archive.items.all())

    rows = []
    for it in items:
        rows.append([
            it.category or "-",
            it.model or "-",
            it.dioptriya or "-",
            str(it.miqdor or 0),
            it.izoh or "-",
        ])

    pdf_bytes = _build_table_pdf(
        title="Arxiv Buyurtma (Optika)",
        header_lines=[
            f"Ism: {archive.user_full_name or '-'}",
            f"Filial: {archive.filial or '-'}",
            f"Sana: {timezone.localtime(archive.created_at).strftime('%Y-%m-%d %H:%M')}",
        ],
        columns=[
            ("Kategoriya", 95),
            ("Model", 170),
            ("Dioptriya", 70),
            ("Miqdor", 55),
            ("Izoh", 125),
        ],
        rows=rows,
    )

    Archive.objects.filter(id=archive.id).update(is_pdf_downloaded=True)

    resp = HttpResponse(pdf_bytes, content_type="application/pdf")
    resp["Content-Disposition"] = 'attachment; filename="archive.pdf"'
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


@require_POST
def download_all_archives_pdf(request: HttpRequest):
    not_logged = _session_user_or_json_401(request)
    if not_logged:
        return not_logged
    not_admin = _admin_or_403(request)
    if not_admin:
        return not_admin

    archives = list(Archive.objects.all().order_by("-created_at"))
    rows = []
    for a in archives:
        rows.append(["---", "---", "---", "---", f"{a.filial or '-'} | {a.user_full_name or '-'} | {a.created_at:%Y-%m-%d %H:%M}"])
        for it in a.items.all():
            rows.append([
                it.category or "-",
                it.model or "-",
                it.dioptriya or "-",
                str(it.miqdor or 0),
                it.izoh or "-",
            ])

    pdf_bytes = _build_table_pdf(
        title="Barcha Arxiv Buyurtmalar (Optika)",
        header_lines=[f"Sana: {timezone.localtime(timezone.now()).strftime('%Y-%m-%d %H:%M')}"],
        columns=[
            ("Kategoriya", 95),
            ("Model", 170),
            ("Dioptriya", 70),
            ("Miqdor", 55),
            ("Izoh", 125),
        ],
        rows=rows,
    )

    Archive.objects.all().update(is_pdf_downloaded=True)

    resp = HttpResponse(pdf_bytes, content_type="application/pdf")
    resp["Content-Disposition"] = 'attachment; filename="all_archives.pdf"'
    return resp


@require_POST
def share_all_archives_telegram(request: HttpRequest):
    """
    Sends a single PDF of all archives to all TelegramChat.chat_id.
    Requires settings.TELEGRAM_BOT_TOKEN.
    """
    not_logged = _session_user_or_json_401(request)
    if not_logged:
        return not_logged
    not_admin = _admin_or_403(request)
    if not_admin:
        return not_admin

    token = getattr(settings, "TELEGRAM_BOT_TOKEN", None)
    if not token:
        return JsonResponse({
            "success": False,
            "message": "TELEGRAM_BOT_TOKEN topilmadi. settings.py ga TELEGRAM_BOT_TOKEN = 'xxxxx' qo‘shing."
        }, status=500)

    chats = list(TelegramChat.objects.all())
    if not chats:
        return JsonResponse({"success": False, "message": "Telegram chat IDlar yo‘q."}, status=400)

    # build PDF (same as download_all)
    archives = list(Archive.objects.all().order_by("-created_at"))
    rows = []
    for a in archives:
        rows.append(["---", "---", "---", "---", f"{a.filial or '-'} | {a.user_full_name or '-'} | {a.created_at:%Y-%m-%d %H:%M}"])
        for it in a.items.all():
            rows.append([
                it.category or "-",
                it.model or "-",
                it.dioptriya or "-",
                str(it.miqdor or 0),
                it.izoh or "-",
            ])

    pdf_bytes = _build_table_pdf(
        title="Arxiv Buyurtmalar (Optika)",
        header_lines=[f"Sana: {timezone.localtime(timezone.now()).strftime('%Y-%m-%d %H:%M')}"],
        columns=[
            ("Kategoriya", 95),
            ("Model", 170),
            ("Dioptriya", 70),
            ("Miqdor", 55),
            ("Izoh", 125),
        ],
        rows=rows,
    )

    # send via Telegram Bot API
    try:
        import requests
    except Exception:
        return JsonResponse({
            "success": False,
            "message": "requests kutubxonasi kerak: pip install requests"
        }, status=500)

    url = f"https://api.telegram.org/bot{token}/sendDocument"
    ok_count = 0

    for ch in chats:
        try:
            files = {"document": ("archives.pdf", io.BytesIO(pdf_bytes), "application/pdf")}
            data = {"chat_id": ch.chat_id, "caption": "Optika buyurtmalar (PDF)"}
            r = requests.post(url, data=data, files=files, timeout=30)
            if r.ok:
                j = r.json()
                if j.get("ok"):
                    ok_count += 1
        except Exception:
            continue

    if ok_count == 0:
        return JsonResponse({"success": False, "message": "Telegramga yuborilmadi."}, status=500)

    Archive.objects.all().update(is_telegram_shared=True)

    return JsonResponse({
        "success": True,
        "message": f"Telegramga yuborildi ({ok_count}/{len(chats)})"
    })


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
    return redirect("/Home/AdminFeedBack")


@require_GET
def export_feedback_pdf(request: HttpRequest):
    redir = _session_user_or_redirect(request)
    if redir:
        return redir
    if request.session.get("Role") != "Admin":
        return redirect("index")

    feedbacks = list(FeedBack.objects.all().order_by("-created_at"))
    rows = []
    for f in feedbacks:
        rows.append([
            f.full_name or "-",
            f.phone or "-",
            f.created_at.strftime("%Y-%m-%d %H:%M"),
            f.message or "-",
        ])

    pdf_bytes = _build_table_pdf(
        title="Feedbacklar (Optika)",
        header_lines=[f"Sana: {timezone.localtime(timezone.now()).strftime('%Y-%m-%d %H:%M')}"],
        columns=[
            ("Ism", 130),
            ("Telefon", 90),
            ("Sana", 110),
            ("Xabar", 185),
        ],
        rows=rows,
    )

    resp = HttpResponse(pdf_bytes, content_type="application/pdf")
    resp["Content-Disposition"] = 'attachment; filename="feedback.pdf"'
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
        user_id = _clean_str(request.POST.get("UserId"))
        parol = _clean_str(request.POST.get("Parol"))
        role = _clean_str(request.POST.get("Role")) or "User"

        if not full_name or not user_id or not parol:
            messages.error(request, "FullName, UserId, Parol majburiy.")
            return redirect("/Home/AddUser")

        if Users.objects.filter(user_id=user_id).exists():
            messages.error(request, "Bunday UserId mavjud.")
            return redirect("/Home/AddUser")

        u = Users(full_name=full_name, phone=phone, user_id=user_id, role=role)
        u.set_password(parol)
        u.save()
        messages.success(request, "Foydalanuvchi qo‘shildi.")
        return redirect("/Home/AddUser")

    users = Users.objects.all().order_by("role", "full_name")
    return render(request, "optika/add_user.html", {"users": users})


@require_POST
def edit_user(request: HttpRequest):
    redir = _session_user_or_redirect(request)
    if redir:
        return redir
    if request.session.get("Role") != "Admin":
        return redirect("index")

    uid = _to_int(request.POST.get("Id"), 0)
    user = Users.objects.filter(id=uid).first()
    if not user:
        messages.error(request, "User topilmadi.")
        return redirect("/Home/AddUser")

    full_name = _clean_str(request.POST.get("FullName"))
    phone = _clean_str(request.POST.get("Phone"))
    user_id_val = _clean_str(request.POST.get("UserId"))
    new_pass = _clean_str(request.POST.get("Parol"))
    role = _clean_str(request.POST.get("Role")) or "User"

    if user_id_val and user_id_val != user.user_id:
        if Users.objects.filter(user_id=user_id_val).exclude(id=user.id).exists():
            messages.error(request, "Bunday UserId mavjud.")
            return redirect("/Home/AddUser")
        user.user_id = user_id_val

    user.full_name = full_name or user.full_name
    user.phone = phone
    user.role = role

    if new_pass:
        user.set_password(new_pass)

    user.save()
    messages.success(request, "User yangilandi.")
    return redirect("/Home/AddUser")


@require_GET
def delete_user(request: HttpRequest):
    redir = _session_user_or_redirect(request)
    if redir:
        return redir
    if request.session.get("Role") != "Admin":
        return redirect("index")

    uid = _to_int(request.GET.get("id"), 0)
    if uid > 0:
        Users.objects.filter(id=uid).delete()
        messages.success(request, "User o‘chirildi.")
    return redirect("/Home/AddUser")


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
        return redirect("index")

    full_name = _clean_str(request.POST.get("FullName"))
    chat_id = _clean_str(request.POST.get("ChatId"))

    if not full_name or not chat_id:
        messages.error(request, "FullName va ChatId majburiy.")
        return redirect("/Home/TelegramChatId")

    if TelegramChat.objects.filter(chat_id=chat_id).exists():
        messages.error(request, "Bu ChatId mavjud.")
        return redirect("/Home/TelegramChatId")

    TelegramChat.objects.create(full_name=full_name, chat_id=chat_id)
    messages.success(request, "Chat ID qo‘shildi.")
    return redirect("/Home/TelegramChatId")


@require_POST
def delete_chat(request: HttpRequest):
    redir = _session_user_or_redirect(request)
    if redir:
        return redir
    if request.session.get("Role") != "Admin":
        return redirect("index")

    cid = _to_int(request.POST.get("id"), 0)
    if cid > 0:
        TelegramChat.objects.filter(id=cid).delete()
        messages.success(request, "Chat ID o‘chirildi.")
    return redirect("/Home/TelegramChatId")
