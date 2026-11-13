from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path

admin.site.site_header = "Pure Amiga CRM admin"
admin.site.site_title = "Pure Amiga CRM"

urlpatterns = [
    path("accounts/login/", auth_views.LoginView.as_view(), name="login"),
    path("accounts/logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("accounts/password/", auth_views.PasswordChangeView.as_view(success_url="/"), name="password_change"),
    path("admin/", admin.site.urls),
    path("", include("repairs.urls")),
]
