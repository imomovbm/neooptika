from django.urls import path
from . import views

app_name = 'optika'

urlpatterns = [
    # Auth
    path("login/", views.login_view, name="login"),
    path("logout/", views.logout_view, name="logout"),
    path("", views.index_view, name="index"),

    # Profile & orders
    path("profile/", views.profile_view, name="profile"),   
    path("profile/save/", views.save_profile_row, name="save_profile_row"),
    path("profile/delete/", views.delete_rows, name="delete_rows"),
    path("profile/download-pdf/", views.download_orders_pdf, name="download_orders_pdf"),
    path("profile/send/", views.mark_as_sent, name="mark_as_sent"),

    # Archive (user-facing)
    path("archive/", views.archive_view, name="archive"),
    path("archive/download/", views.download_archive_pdf, name="download_archive_pdf"),

    # Admin panel
    path("admin-panel/", views.admin_page, name="admin_page"),
    path("admin-panel/archives/", views.get_archives, name="get_archives"),
    path("admin-panel/archives/items/", views.get_archive_items, name="get_archive_items"),
    path("admin-panel/archives/delete/", views.delete_archive, name="delete_archive"),
    path("admin-panel/archives/download-pdf/", views.download_all_archives_pdf, name="download_all_archives_pdf"),
    path("admin-panel/archives/telegram/", views.share_all_archives_telegram, name="share_all_archives_telegram"),
    path("admin-panel/archives/clear/", views.clear_all_archives, name="clear_all_archives"),

    # Feedback
    path("feedback/", views.feedback_page, name="feedback_page"),
    path("feedback/send/", views.send_feedback, name="send_feedback"),
    path("feedback/admin/", views.admin_feedback_page, name="admin_feedback_page"),
    path("feedback/admin/clear/", views.clear_all_feedback, name="clear_all_feedback"),
    path("feedback/admin/export-pdf/", views.export_feedback_pdf, name="export_feedback_pdf"),

    # User management
    path("users/", views.add_user_page_and_create, name="add_user"),
    path("users/edit/", views.edit_user, name="edit_user"),
    path("users/delete/", views.delete_user, name="delete_user"),

    # Telegram
    path("telegram/", views.telegram_chat_id_page, name="telegram_chat_id_page"),
    path("telegram/add/", views.add_chat, name="add_chat"),
    path("telegram/delete/", views.delete_chat, name="delete_chat"),

    # Product category pages
    path("products/rangsiz/", views.rangsiz_page, name="rangsiz_page"),
    path("products/rangli/", views.rangli_page, name="rangli_page"),
    path("products/kaplya/", views.kaplya_page, name="kaplya_page"),
    path("products/aksessuar/", views.aksessuar_page, name="aksessuar_page"),
    path("products/antikomp/", views.antikomp_page, name="antikomp_page"),
    path("products/gatoviy/", views.gatoviy_page, name="gatoviy_page"),
    path("products/oprava/", views.oprava_page, name="oprava_page"),

    # Product save endpoints
    path("products/rangsiz/save/", views.save_rangsiz, name="save_rangsiz"),
    path("products/rangli/save/", views.save_rangli, name="save_rangli"),
    path("products/kaplya/save/", views.save_kapliya, name="save_kapliya"),
    path("products/aksessuar/save/", views.save_aksessuar, name="save_aksessuar"),
    path("products/antikomp/save/", views.save_antik, name="save_antik"),
    path("products/gatoviy/save/", views.save_gatoviy, name="save_gatoviy"),
    path("products/oprava/save/", views.save_oprava, name="save_oprava"),
]