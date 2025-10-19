from django.contrib import admin
from django.urls import path, include
from django.contrib.auth import views as auth_views
from core import views as core_views
from django.views.generic import TemplateView

urlpatterns = [
    path("admin/", admin.site.urls),

    # Authentication
    path("accounts/login/", auth_views.LoginView.as_view(template_name="login.html"), name="login"),
    path("accounts/logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("accounts/", include("django.contrib.auth.urls")),

    # Pages
    path("dashboard/", core_views.dashboard_view, name="dashboard"),
    path("settings/", core_views.settings_view, name="settings"),

    # API
    path("api/metrics/", core_views.metrics_api, name="metrics_api"),
    path("api/trades/", core_views.trades_list_api, name="trades_list_api"),
    path("api/trades/add/", core_views.add_trade_view, name="trade_add"),

    # Robots.txt
    path("robots.txt", TemplateView.as_view(template_name="robots.txt", content_type="text/plain")),

    # Root redirect
    path("", core_views.root_redirect, name="root"),
]
