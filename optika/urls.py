from django.urls import path
from . import views

app_name='optika'

urlpatterns = [
    # Home
    path("login/", views.login_view, name="login"),
    path("", views.index_view, name="index"),
    path("logout/", views.logout_view, name="logout"),

    path("profile/", views.profile_view, name="profile"),
    path("Home/Archive", views.archive_view, name="archive"),
    path("Home/DownloadPdf", views.download_archive_pdf, name="download_archive_pdf"),

    # Admin custom panel
    path("Home/Admin", views.admin_page, name="admin_page"),
    path("Home/GetArchives", views.get_archives, name="get_archives"),
    path("Home/GetArchiveItems", views.get_archive_items, name="get_archive_items"),
    path("Home/DeleteArchive", views.delete_archive, name="delete_archive"),
    path("Home/DownloadAllArchivesPdf", views.download_all_archives_pdf, name="download_all_archives_pdf"),
    path("Home/ShareAllArchivesTelegram", views.share_all_archives_telegram, name="share_all_archives_telegram"),
    path("Home/ClearAllArchives", views.clear_all_archives, name="clear_all_archives"),

    # Feedback
    path("Home/Feedback", views.feedback_page, name="feedback_page"),
    path("Home/SendFeedback", views.send_feedback, name="send_feedback"),
    path("Home/AdminFeedBack", views.admin_feedback_page, name="admin_feedback_page"),
    path("Home/ClearAllFeedBack", views.clear_all_feedback, name="clear_all_feedback"),
    path("Home/ExportToPdf", views.export_feedback_pdf, name="export_feedback_pdf"),

    # Users management
    path("Home/AddUser", views.add_user_page_and_create, name="add_user"),
    path("Home/EditUser", views.edit_user, name="edit_user"),
    path("Home/DeleteUser", views.delete_user, name="delete_user"),

    # Telegram chat IDs
    path("Home/TelegramChatId", views.telegram_chat_id_page, name="telegram_chat_id_page"),
    path("Home/AddChat", views.add_chat, name="add_chat"),
    path("Home/DeleteChat", views.delete_chat, name="delete_chat"),

    # Linza pages
    path("Linza/Rangsiz", views.rangsiz_page, name="rangsiz_page"),
    path("Linza/Rangli", views.rangli_page, name="rangli_page"),
    path("Linza/Kaplya", views.kaplya_page, name="kaplya_page"),
    path("Linza/Aksessuar", views.aksessuar_page, name="aksessuar_page"),
    path("Linza/Antikomp", views.antikomp_page, name="antikomp_page"),
    path("Linza/Gatoviy", views.gatoviy_page, name="gatoviy_page"),
    path("Linza/Oprava", views.oprava_page, name="oprava_page"),

    # Save endpoints
    path("Linza/SaveRangsiz", views.save_rangsiz, name="save_rangsiz"),
    path("Linza/SaveRangli", views.save_rangli, name="save_rangli"),
    path("Linza/SaveKapliya", views.save_kapliya, name="save_kapliya"),
    path("Linza/SaveAksessuar", views.save_aksessuar, name="save_aksessuar"),
    path("Linza/SaveAntik", views.save_antik, name="save_antik"),
    path("Linza/SaveGot", views.save_gatoviy, name="save_gatoviy"),
    path("Linza/SaveOprava", views.save_oprava, name="save_oprava"),

    # Profile API endpoints (used by profile.html JS)
    path("Linza/Save", views.save_profile_row, name="save_profile_row"),
    path("Linza/DeleteRows", views.delete_rows, name="delete_rows"),
    path("Linza/DownloadPdf", views.download_orders_pdf, name="download_orders_pdf"),
    path("Linza/MarkAsSent", views.mark_as_sent, name="mark_as_sent"),
]
