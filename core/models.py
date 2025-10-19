from uuid import uuid4
from django.db import models
from django.contrib.auth import get_user_model

User = get_user_model()


class Tenant(models.Model):
    """
    Lightweight organization / tenant container.
    """
    name = models.CharField(max_length=150, unique=True)
    slug = models.SlugField(max_length=160, unique=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("name",)

    def __str__(self):
        return self.name


class UserProfile(models.Model):
    """
    Per-user profile tying the user to a tenant and exposing a random/UUID external id.
    This gives you a random public/user-facing id without replacing Django's user PK.
    """
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="profile")
    tenant = models.ForeignKey(Tenant, on_delete=models.PROTECT, related_name="users", null=True, blank=True)
    external_id = models.UUIDField(default=uuid4, unique=True, editable=False)
    preferred_theme = models.CharField(
        max_length=20,
        choices=[("system", "System"), ("light", "Light"), ("dark", "Dark")],
        default="system",
    )
    preferred_currency = models.CharField(max_length=10, default="USD")
    trading_goal = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    notifications_enabled = models.BooleanField(default=True)    
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "User Profile"
        verbose_name_plural = "User Profiles"

    def __str__(self):
        return f"{self.user.username} • {self.tenant or 'No tenant'}"


class Trade(models.Model):
    """
    Minimal trade model to store exactly what's entered on the dashboard form.
    """
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="trades")
    tenant = models.ForeignKey(Tenant, on_delete=models.PROTECT, related_name="trades", null=True, blank=True)

    symbol = models.CharField(max_length=50)
    trade_date = models.DateField()
    initial_risk = models.DecimalField(max_digits=12, decimal_places=2)
    pnl = models.DecimalField(max_digits=12, decimal_places=2)
    strategy = models.CharField(max_length=100, blank=True)
    note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-trade_date", "-created_at")
        indexes = [
            models.Index(fields=["tenant", "trade_date"]),
            models.Index(fields=["tenant", "user"]),
        ]

    def __str__(self):
        return f"{self.symbol} {self.trade_date} ({self.pnl})"

class Strategy(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="strategies")
    # keep tenant optional so your current single-tenant use works; future-ready if you keep tenants
    tenant = models.ForeignKey("Tenant", on_delete=models.PROTECT, related_name="strategies", null=True, blank=True)
    name = models.CharField(max_length=100)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("name",)
        # Enforce unique strategy names per user (and per-tenant if you use tenants)
        unique_together = (("user", "name", "tenant"),)

    def __str__(self):
        return f"{self.name} • {self.user}"
