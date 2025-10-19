import hashlib
import logging
from time import time
from ipaddress import ip_address, ip_network
from django.conf import settings
from django.contrib.auth import logout
from django.shortcuts import redirect
from django.utils.deprecation import MiddlewareMixin

logger = logging.getLogger("security")

def _client_ip(request):
    xff = request.META.get("HTTP_X_FORWARDED_FOR")
    if xff:
        return xff.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "")

# -------------------------------
# Existing Security Middleware(s)
# -------------------------------

class SecurityIPAllowlistMiddleware(MiddlewareMixin):
    """
    Optional example: allowlist by CIDR ranges via settings.SECURITY_IP_ALLOWLIST = ["127.0.0.1/32", ...]
    If not configured, it does nothing.
    """
    def process_request(self, request):
        cidrs = getattr(settings, "SECURITY_IP_ALLOWLIST", None)
        if not cidrs:
            return
        client = _client_ip(request)
        try:
            ip_obj = ip_address(client)
        except Exception:
            logger.warning("Invalid client IP: %s", client)
            return redirect("/accounts/login/")
        ok = any(ip_obj in ip_network(cidr.strip()) for cidr in cidrs)
        if not ok:
            logger.info("Blocked IP: %s", client)
            return redirect("/accounts/login/")

class SecurityIdleTimeoutMiddleware(MiddlewareMixin):
    """
    Logs out authenticated users after N seconds of inactivity.
    Configure seconds in settings.SECURITY_IDLE_TIMEOUT_SECONDS (default 1800).
    """
    LAST_SEEN_KEY = "_last_seen_ts"
    IDLE_SECONDS = getattr(settings, "SECURITY_IDLE_TIMEOUT_SECONDS", 1800)

    def process_request(self, request):
        if not request.user.is_authenticated:
            return
        now = int(time())
        last_seen = request.session.get(self.LAST_SEEN_KEY, now)
        if now - last_seen > self.IDLE_SECONDS:
            logger.info("Idle session timeout; logging out.")
            logout(request)
            try:
                request.session.flush()
            except Exception:
                pass
            return redirect("/accounts/login/?timeout=1")
        request.session[self.LAST_SEEN_KEY] = now

# -------------------------------
# NEW: Tenant Binding Middleware
# -------------------------------

class TenantBindingMiddleware(MiddlewareMixin):
    """
    Binds the active tenant to each authenticated request as `request.tenant`.

    Resolution strategy (simple, safe, no new files):
    - If user is authenticated and has a profile with a tenant -> use it.
    - If no profile/tenant exists -> set `request.tenant = None` (views/admin should guard).
      (You can add a redirect or hard 403 later once all users are assigned.)

    This middleware does not alter routing. It only sets request.tenant for use in views/admin.
    """

    def process_request(self, request):
        request.tenant = None
        user = getattr(request, "user", None)
        if not user or not user.is_authenticated:
            return

        # Lazy import to avoid circulars if this module is loaded early
        try:
            from core.models import UserProfile  # noqa
        except Exception:
            # If models not ready, fail open (request.tenant stays None)
            return

        profile = getattr(user, "profile", None)
        tenant = getattr(profile, "tenant", None)
        request.tenant = tenant


# -------------------------------
# NEW: Anti-crawler Header Middleware
# -------------------------------
from django.utils.deprecation import MiddlewareMixin

class AntiCrawlerHeaderMiddleware(MiddlewareMixin):
    """
    Adds X-Robots-Tag headers to every response to prevent indexing/crawling.
    """
    def process_response(self, request, response):
        response["X-Robots-Tag"] = "noindex, nofollow, nosnippet, noarchive"
        response["Referrer-Policy"] = "no-referrer"
        response["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
        return response
