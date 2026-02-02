from django.db import models
from django.utils import timezone
from django.contrib.auth.hashers import make_password, check_password


class Users(models.Model):
    ROLE_CHOICES = [
        ("Admin", "Admin"),
        ("User", "User"),
    ]

    full_name = models.CharField(max_length=255, default="")
    phone = models.CharField(max_length=50, default="", blank=True)
    user_id = models.CharField(max_length=50, unique=True, default="")
    # In ASP.NET you stored plain text. In Django we SHOULD hash it:
    parol = models.CharField(max_length=128, default="")  # hashed password
    role = models.CharField(max_length=10, choices=ROLE_CHOICES, default="User")

    def set_password(self, raw_password: str) -> None:
        self.parol = make_password(raw_password)

    def check_password(self, raw_password: str) -> bool:
        return check_password(raw_password, self.parol)

    def __str__(self):
        return f"{self.full_name} ({self.user_id})"


class Order(models.Model):
    user_id = models.CharField(max_length=50)  # matches ASP.NET usage
    model = models.CharField(max_length=255)
    product_id = models.IntegerField()
    category = models.CharField(max_length=100, null=True, blank=True)
    narx = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    dioptriya = models.CharField(max_length=50, null=True, blank=True)
    miqdor = models.IntegerField(default=0)
    izoh = models.TextField(default="-", blank=True)
    filial = models.CharField(max_length=100, default="-")
    is_sent = models.BooleanField(default=False)
    created_at = models.DateTimeField(default=timezone.now)

    def __str__(self):
        return f"{self.category} | {self.model} | {self.miqdor}"


# --- Product tables (kept separate like your original DB) ---

class Aksessuar(models.Model):
    order_id = models.IntegerField(default=0)
    user_id = models.CharField(max_length=50, default="", blank=True)
    rasm = models.CharField(max_length=255, null=True, blank=True)
    nomi = models.CharField(max_length=255)
    turi = models.CharField(max_length=255, default="", blank=True)
    dioptriya = models.CharField(max_length=50, null=True, blank=True)
    miqdor = models.IntegerField(default=0)
    narx = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    izoh = models.TextField(null=True, blank=True)
    category = models.CharField(max_length=100, default="Аксессуар")


class Antikompyuter(models.Model):
    order_id = models.IntegerField(default=0)
    user_id = models.CharField(max_length=50, default="", blank=True)
    rasm = models.CharField(max_length=255, null=True, blank=True)
    nomi = models.CharField(max_length=255)
    turi = models.CharField(max_length=255, null=True, blank=True)
    dioptriya = models.CharField(max_length=50, null=True, blank=True)
    miqdor = models.IntegerField(default=0)
    narx = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    izoh = models.TextField(null=True, blank=True)
    category = models.CharField(max_length=100, default="Антикомп")


class Kapliya(models.Model):
    order_id = models.IntegerField(default=0)
    user_id = models.CharField(max_length=50, default="", blank=True)
    rasm = models.CharField(max_length=255, null=True, blank=True)
    nomi = models.CharField(max_length=255)
    turi = models.CharField(max_length=255, null=True, blank=True)
    dioptriya = models.CharField(max_length=50, null=True, blank=True)
    miqdor = models.IntegerField(default=0)
    narx = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    izoh = models.TextField(null=True, blank=True)
    category = models.CharField(max_length=100, default="Капля")


class Oprava(models.Model):
    rasm = models.CharField(max_length=255, null=True, blank=True)
    order_id = models.IntegerField(default=0)
    user_id = models.CharField(max_length=50, default="", blank=True)
    nomi = models.CharField(max_length=255)
    turi = models.CharField(max_length=255, default="", blank=True)
    dioptriya = models.CharField(max_length=50, null=True, blank=True)
    miqdor = models.IntegerField(default=0)
    narx = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    izoh = models.TextField(null=True, blank=True)
    category = models.CharField(max_length=100, default="Оправа")


class Rangli(models.Model):
    rasm = models.CharField(max_length=255, null=True, blank=True)
    order_id = models.IntegerField(default=0)
    user_id = models.CharField(max_length=50, default="", blank=True)
    nomi = models.CharField(max_length=255)
    turi = models.CharField(max_length=255, null=True, blank=True)
    dioptriya = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    miqdor = models.IntegerField(default=0)
    narx = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    izoh = models.TextField(null=True, blank=True)
    category = models.CharField(max_length=100, default="Цветная линза")


class Rangsiz(models.Model):
    rasm = models.CharField(max_length=255, null=True, blank=True)
    order_id = models.IntegerField(default=0)
    user_id = models.CharField(max_length=50, default="", blank=True)
    nomi = models.CharField(max_length=255)
    turi = models.CharField(max_length=255, null=True, blank=True)
    dioptriya = models.CharField(max_length=50, null=True, blank=True)
    miqdor = models.IntegerField(default=0)
    narx = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    izoh = models.TextField(null=True, blank=True)
    category = models.CharField(max_length=100, default="Контакт линза")


class Gatoviy(models.Model):
    order_id = models.IntegerField(default=0)
    user_id = models.CharField(max_length=50, default="", blank=True)
    model = models.CharField(max_length=255, default="")
    narx = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    nomi = models.CharField(max_length=255, null=True, blank=True)
    dioptriya = models.CharField(max_length=50, null=True, blank=True)
    miqdor = models.IntegerField(default=0)
    izoh = models.TextField(null=True, blank=True)
    filial = models.CharField(max_length=100, default="-")
    created_at = models.DateTimeField(default=timezone.now)
    category = models.CharField(max_length=100, default="Готовые")


# --- Archive tables ---

class Archive(models.Model):
    filial = models.CharField(max_length=100, null=True, blank=True)
    user_full_name = models.CharField(max_length=255, null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    is_pdf_downloaded = models.BooleanField(default=False)
    is_telegram_shared = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.user_full_name} | {self.filial} | {self.created_at:%Y-%m-%d}"


class ArchiveItem(models.Model):
    archive = models.ForeignKey(Archive, related_name="items", on_delete=models.CASCADE)
    category = models.CharField(max_length=100, null=True, blank=True)
    model = models.CharField(max_length=255, null=True, blank=True)
    dioptriya = models.CharField(max_length=50, null=True, blank=True)
    miqdor = models.IntegerField(default=0)
    izoh = models.TextField(null=True, blank=True)


class FeedBack(models.Model):
    full_name = models.CharField(max_length=255, default="")
    phone = models.CharField(max_length=50, null=True, blank=True)
    message = models.TextField(default="")
    created_at = models.DateTimeField(default=timezone.now)


class TelegramChat(models.Model):
    full_name = models.CharField(max_length=255)
    chat_id = models.CharField(max_length=50, unique=True)

    def __str__(self):
        return f"{self.full_name} ({self.chat_id})"
