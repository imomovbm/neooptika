from django.contrib import admin
from .models import (
    Users, Order,
    Rangsiz, Rangli, Kapliya, Aksessuar, Antikompyuter, Oprava, Gatoviy,
    Archive, ArchiveItem,
    FeedBack, TelegramChat,
)

@admin.register(Users)
class UsersAdmin(admin.ModelAdmin):
    list_display = ("id", "full_name", "user_id", "phone", "role")
    search_fields = ("full_name", "user_id", "phone")
    list_filter = ("role",)

@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ("id", "filial", "category", "model", "dioptriya", "miqdor", "user_id", "created_at")
    search_fields = ("model", "category", "filial", "user_id")
    list_filter = ("category", "filial", "created_at")

@admin.register(Archive)
class ArchiveAdmin(admin.ModelAdmin):
    list_display = ("id", "filial", "user_full_name", "created_at", "is_pdf_downloaded", "is_telegram_shared")
    list_filter = ("filial", "is_pdf_downloaded", "is_telegram_shared", "created_at")
    search_fields = ("filial", "user_full_name")

@admin.register(ArchiveItem)
class ArchiveItemAdmin(admin.ModelAdmin):
    list_display = ("id", "archive", "category", "model", "dioptriya", "miqdor")
    search_fields = ("category", "model", "dioptriya")
    list_filter = ("category",)

@admin.register(FeedBack)
class FeedBackAdmin(admin.ModelAdmin):
    list_display = ("id", "full_name", "phone", "created_at")
    search_fields = ("full_name", "phone", "message")
    list_filter = ("created_at",)

@admin.register(TelegramChat)
class TelegramChatAdmin(admin.ModelAdmin):
    list_display = ("id", "full_name", "chat_id")
    search_fields = ("full_name", "chat_id")

# Product tables
admin.site.register(Rangsiz)
admin.site.register(Rangli)
admin.site.register(Kapliya)
admin.site.register(Aksessuar)
admin.site.register(Antikompyuter)
admin.site.register(Oprava)
admin.site.register(Gatoviy)
