from django.contrib import admin
from django.db.models import QuerySet
from .models import Trade, Tenant, UserProfile, Strategy

# Branding tweaks (affects admin header & browser title)
admin.site.site_header = "Professional Trading Journal"
admin.site.site_title = "Admin Console"
admin.site.index_title = ""  # remove extra subtitle on the index

@admin.register(Tenant)
class TenantAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "is_active", "created_at")
    list_filter = ("is_active",)
    search_fields = ("name", "slug")
    ordering = ("name",)


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    # includes preferences so you can view/edit in admin
    list_display = (
        "user",
        "tenant",
        "external_id",
        "preferred_theme",
        "preferred_currency",
        "trading_goal",
        "notifications_enabled",
        "created_at",
    )
    list_filter = ("tenant", "preferred_theme", "notifications_enabled")
    search_fields = ("user__username", "user__email", "external_id", "preferred_currency")
    readonly_fields = ("external_id", "created_at")

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs
        tenant = getattr(getattr(request.user, "profile", None), "tenant", None)
        if tenant:
            return qs.filter(tenant=tenant)
        return qs.none()


@admin.register(Trade)
class TradeAdmin(admin.ModelAdmin):
    list_display = ("user", "tenant", "symbol", "trade_date", "pnl", "initial_risk", "strategy")
    list_filter = ("tenant", "strategy", "trade_date")
    search_fields = ("user__username", "symbol", "note")
    ordering = ("-trade_date", "-created_at")

    def get_queryset(self, request):
        qs: QuerySet = super().get_queryset(request)
        if request.user.is_superuser:
            return qs
        tenant = getattr(getattr(request.user, "profile", None), "tenant", None)
        if tenant:
            return qs.filter(tenant=tenant)
        # If staff has no tenant, show nothing (safest default)
        return qs.none()

    def save_model(self, request, obj, form, change):
        # Auto-attach tenant for staff if missing
        if not getattr(obj, "tenant", None):
            tenant = getattr(getattr(request.user, "profile", None), "tenant", None)
            if tenant:
                obj.tenant = tenant
        super().save_model(request, obj, form, change)

@admin.register(Strategy)
class StrategyAdmin(admin.ModelAdmin):
    list_display = ("user", "name", "created_at")
    search_fields = ("user__username", "name")
    list_filter = ("user",)
    ordering = ("user", "name")
