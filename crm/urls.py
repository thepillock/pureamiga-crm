from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_not_required
from django.urls import include, path

from repairs import system_views

admin.site.site_header = "Pure Amiga CRM admin"
admin.site.site_title = "Pure Amiga CRM"

urlpatterns = [
    path("healthz", system_views.healthz, name="healthz"),
    path("setup/", system_views.setup, name="setup"),
    path("accounts/login/", login_not_required(system_views.CRMLoginView.as_view()), name="login"),
    path("accounts/logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("accounts/password/", auth_views.PasswordChangeView.as_view(success_url="/"), name="password_change"),
    path("admin/", admin.site.urls),
    path("", include("repairs.urls")),
]
