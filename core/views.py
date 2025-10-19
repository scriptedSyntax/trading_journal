from __future__ import annotations

import json
from decimal import Decimal, InvalidOperation
from datetime import date, datetime
from typing import Dict, List, Tuple
from calendar import monthrange

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse, HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.utils.dateparse import parse_date
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST
from django.db.models import QuerySet

from .models import Trade, Strategy

# ------------------------------
# Utilities
# ------------------------------

def _to_decimal(val, allow_none: bool = False) -> Decimal:
    if val is None and allow_none:
        return None  # type: ignore
    if isinstance(val, Decimal):
        return val
    try:
        return Decimal(str(val))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal("0")


def _safe_getattr(obj, name: str, default=None):
    return getattr(obj, name, default)


def _trade_r_multiple(trade) -> Decimal:
    """
    Compute R-multiple for a trade (pnl / initial_risk) safely.
    Uses object's r_multiple if present; otherwise computes on the fly.
    """
    rm = _safe_getattr(trade, "r_multiple", None)
    if rm is not None:
        try:
            return _to_decimal(rm)
        except Exception:
            pass
    pnl = _to_decimal(_safe_getattr(trade, "pnl", 0))
    risk = _to_decimal(_safe_getattr(trade, "initial_risk", 0))
    if risk == 0:
        return Decimal("0")
    return pnl / risk


def _accumulate(values: List[Decimal]) -> List[Decimal]:
    out: List[Decimal] = []
    running = Decimal("0")
    for v in values:
        running += v
        out.append(running)
    return out


def _compute_max_drawdown(cum_values: List[Decimal]) -> Decimal:
    """
    Max drawdown from a cumulative P/L series.
    Returns a negative number or 0 if no drawdown.
    """
    peak = Decimal("-1e999")
    max_dd = Decimal("0")
    for v in cum_values:
        if v > peak:
            peak = v
        dd = v - peak
        if dd < max_dd:
            max_dd = dd
    return max_dd


def _current_tenant(request: HttpRequest):
    """
    Helper to fetch the active tenant bound by middleware.
    May be None (e.g., before backfill). Views use it to narrow querysets and set FK.
    """
    return getattr(request, "tenant", None)


def _user_external_id(user):
    """
    Prefer profile.external_id (UUID) as the public-facing user id.
    Fall back to numeric user.id if profile/uuid is missing.
    """
    prof = getattr(user, "profile", None)
    ext = getattr(prof, "external_id", None)
    return str(ext) if ext else getattr(user, "id", "—")


# ------------------------------
# Navigation helpers
# ------------------------------

def root_redirect(request: HttpRequest) -> HttpResponse:
    if request.user.is_authenticated:
        return redirect("dashboard")
    return redirect("login")


# ------------------------------
# Core metrics + chart builder
# ------------------------------

def _get_user_trades(request: HttpRequest) -> QuerySet:
    """
    Base queryset for the authenticated user's trades, optionally narrowed by tenant.
    Keeps ordering stable for charting.
    """
    if Trade is None:
        raise RuntimeError("Trade model is not available. Ensure core.models.Trade exists.")

    user = request.user
    qs = Trade.objects.filter(user=user)

    # Narrow by tenant if we have one and the model supports it.
    tenant = _current_tenant(request)
    if tenant is not None and hasattr(Trade, "tenant"):
        qs = qs.filter(tenant=tenant)

    # Prefer ordering by trade_date then created_at/id for deterministic chart
    field_names = [f.name for f in Trade._meta.get_fields()]
    if "trade_date" in field_names:
        # Add a secondary key to keep same-day items stable
        if "created_at" in field_names:
            qs = qs.order_by("trade_date", "created_at", "id")
        else:
            qs = qs.order_by("trade_date", "id")
    else:
        qs = qs.order_by("id")

    return qs


def _build_metrics_and_chart(qs: QuerySet) -> Tuple[Dict, Dict]:
    total_trades = qs.count()
    pnls: List[Decimal] = [_to_decimal(t.pnl) for t in qs]
    risks: List[Decimal] = [_to_decimal(_safe_getattr(t, "initial_risk", 0)) for t in qs]

    wins = sum(1 for p in pnls if p > 0)
    losses = sum(1 for p in pnls if p < 0)
    win_rate = Decimal(wins) / Decimal(total_trades) * 100 if total_trades else Decimal("0")

    gross_profit = sum((p for p in pnls if p > 0), start=Decimal("0"))
    gross_loss_abs = sum((-p for p in pnls if p < 0), start=Decimal("0"))
    profit_factor = (gross_profit / gross_loss_abs) if gross_loss_abs != 0 else Decimal("0")

    # Average R (risk-reward)
    r_list: List[Decimal] = [(p / r) if r != 0 else Decimal("0") for p, r in zip(pnls, risks)]
    avg_r = (sum(r_list, start=Decimal("0")) / Decimal(total_trades)) if total_trades else Decimal("0")

    # Expectancy in "R": (W% * AvgWin/R) - (L% * AvgLoss/R)
    avg_win_r = (sum((rm for rm in r_list if rm > 0), start=Decimal("0")) / Decimal(wins)) if wins else Decimal("0")
    avg_loss_r_abs = (sum((-rm for rm in r_list if rm < 0), start=Decimal("0")) / Decimal(losses)) if losses else Decimal("0")
    expectancy_r = (win_rate/Decimal(100))*avg_win_r - ((Decimal(100)-win_rate)/Decimal(100))*avg_loss_r_abs

    # Cumulative equity & drawdown
    cumulative = _accumulate(pnls)
    ordered_days = [(_safe_getattr(t, "trade_date", None) or date.today()) for t in qs]
    max_dd = _compute_max_drawdown(cumulative)

    account_balance = cumulative[-1] if cumulative else Decimal("0")

    metrics = {
        "trades": total_trades,
        "wins": wins,
        "losses": losses,
        "win_rate": float(win_rate),
        "net_pl": float(sum(pnls, start=Decimal("0"))),
        "avg_r": float(avg_r),
        "expectancy": float(expectancy_r),
        "profit_factor": float(profit_factor),
        "max_drawdown": float(max_dd),  # negative if drawdown exists
        "account_balance": float(account_balance),
    }
    chart = {
        "labels": [d.strftime("%Y-%m-%d") if isinstance(d, (date, datetime)) else str(d) for d in ordered_days],
        "values": [float(v) for v in cumulative],
    }
    return metrics, chart


def _build_strategy_edges(qs: QuerySet) -> List[Dict]:
    """
    Build per-strategy 'edge' metrics (expectancy, PF, avg R, win%, net P/L, MDD) + top assets.
    Returns a list of dicts sorted by expectancy desc.
    """
    buckets: Dict[str, Dict] = {}
    for t in qs:
        sname = (_safe_getattr(t, "strategy", "") or "").strip() or "Unspecified Strategy"
        rec = buckets.setdefault(sname, {"pnls": [], "risks": [], "symbols": {}, "trades": 0})
        pnl = _to_decimal(_safe_getattr(t, "pnl", 0))
        risk = _to_decimal(_safe_getattr(t, "initial_risk", 0))
        rec["pnls"].append(pnl)
        rec["risks"].append(risk)
        rec["trades"] += 1
        sym = (_safe_getattr(t, "symbol", "") or "").strip()
        if sym:
            srec = rec["symbols"].setdefault(sym, {"pnl": Decimal("0"), "wins": 0, "losses": 0, "count": 0})
            srec["pnl"] += pnl
            srec["count"] += 1
            if pnl > 0:
                srec["wins"] += 1
            elif pnl < 0:
                srec["losses"] += 1

    out: List[Dict] = []
    for name, d in buckets.items():
        pnls: List[Decimal] = d["pnls"]
        risks: List[Decimal] = d["risks"]
        n = len(pnls)
        wins = sum(1 for p in pnls if p > 0)
        losses = sum(1 for p in pnls if p < 0)
        win_rate = (Decimal(wins) / Decimal(n) * 100) if n else Decimal("0")

        gross_profit = sum((p for p in pnls if p > 0), start=Decimal("0"))
        gross_loss_abs = sum((-p for p in pnls if p < 0), start=Decimal("0"))
        profit_factor = (gross_profit / gross_loss_abs) if gross_loss_abs != 0 else Decimal("0")

        r_list: List[Decimal] = [(p / r) if r != 0 else Decimal("0") for p, r in zip(pnls, risks)]
        avg_r = (sum(r_list, start=Decimal("0")) / Decimal(n)) if n else Decimal("0")
        avg_win_r = (sum((rm for rm in r_list if rm > 0), start=Decimal("0")) / Decimal(wins)) if wins else Decimal("0")
        avg_loss_r_abs = (sum((-rm for rm in r_list if rm < 0), start=Decimal("0")) / Decimal(losses)) if losses else Decimal("0")
        expectancy_r = (win_rate/Decimal(100))*avg_win_r - ((Decimal(100)-win_rate)/Decimal(100))*avg_loss_r_abs

        cumulative = _accumulate(pnls)
        max_dd = _compute_max_drawdown(cumulative)

        # Top assets by absolute contribution
        assets = []
        for sym, sd in d["symbols"].items():
            wr = (Decimal(sd["wins"]) / Decimal(sd["count"]) * 100) if sd["count"] else Decimal("0")
            assets.append({"symbol": sym, "trades": sd["count"], "net_pl": float(sd["pnl"]), "win_rate": float(wr)})
        assets.sort(key=lambda a: abs(a["net_pl"]), reverse=True)

        out.append({
            "name": name,
            "trades": n,
            "net_pl": float(sum(pnls, start=Decimal("0"))),
            "win_rate": float(win_rate),
            "profit_factor": float(profit_factor),
            "avg_r": float(avg_r),
            "expectancy": float(expectancy_r),
            "max_drawdown": float(max_dd),
            "top_assets": assets[:5],
        })

    out.sort(key=lambda e: (e["expectancy"], e["profit_factor"], e["net_pl"]), reverse=True)
    return out

# ------------------------------
# Views
# ------------------------------

@login_required
def dashboard_view(request: HttpRequest) -> HttpResponse:
    """
    Render dashboard with computed metrics, chart data, calendar, streaks, and breakdown.
    All numbers are rendered server-side (no humanize).
    Tenant-aware: reads only current user's trades within request.tenant (if set).
    """
    qs = _get_user_trades(request)
    metrics, chart = _build_metrics_and_chart(qs)

    # ---- Calendar (selected month via ?year=&month=) ----
    today = date.today()
    try:
        year = int(request.GET.get("year", today.year))
        month = int(request.GET.get("month", today.month))
        if not (1 <= month <= 12):
            raise ValueError
    except Exception:
        year, month = today.year, today.month

    days_in_month = monthrange(year, month)[1]
    # Python weekday: Mon=0..Sun=6 ; we want Sun=0 start offset
    first_weekday = date(year, month, 1).weekday()
    cal_start_offset = (first_weekday + 1) % 7  # Sun-based grid

    # Aggregate P/L and trade counts by day for this month
    daily = {}
    for t in qs:
        td = _safe_getattr(t, "trade_date", None)
        if isinstance(td, datetime):
            td = td.date()
        if isinstance(td, date) and td.year == year and td.month == month:
            k = td.day
            if k not in daily:
                daily[k] = {"trades": 0, "pnl": Decimal("0")}
            daily[k]["trades"] += 1
            daily[k]["pnl"] += _to_decimal(_safe_getattr(t, "pnl", 0))
    cal_days = []
    for d in range(1, days_in_month + 1):
        rec = daily.get(d, {"trades": 0, "pnl": Decimal("0")})
        cal_days.append({"day": d, "trades": rec["trades"], "pnl": float(rec["pnl"])})

    cal_title = date(year, month, 1).strftime("%B %Y")

    # Prev/Next month navigation values
    if month == 1:
        cal_prev_year, cal_prev_month = year - 1, 12
    else:
        cal_prev_year, cal_prev_month = year, month - 1

    if month == 12:
        cal_next_year, cal_next_month = year + 1, 1
    else:
        cal_next_year, cal_next_month = year, month + 1

    # ---- Streaks & max consecutive risk on losing streak ----
    longest_win = 0
    longest_loss = 0
    cur_win = 0
    cur_loss = 0
    cur_loss_risk = Decimal("0")
    max_consec_risk = Decimal("0")
    for t in qs:
        pnl = _to_decimal(_safe_getattr(t, "pnl", 0))
        risk = _to_decimal(_safe_getattr(t, "initial_risk", 0))
        if pnl > 0:
            cur_win += 1
            longest_win = max(longest_win, cur_win)
            # reset loss counters
            cur_loss = 0
            cur_loss_risk = Decimal("0")
        elif pnl < 0:
            cur_loss += 1
            longest_loss = max(longest_loss, cur_loss)
            cur_loss_risk += risk
            if cur_loss_risk > max_consec_risk:
                max_consec_risk = cur_loss_risk
            # reset win counter
            cur_win = 0
        else:
            # pnl == 0 breaks both streaks
            cur_win = 0
            cur_loss = 0
            cur_loss_risk = Decimal("0")

    streaks = {
        "longest_win": longest_win,
        "longest_loss": longest_loss,
        "max_consec_risk": float(max_consec_risk),
    }

    # ---- Strategy & asset breakdown (top combined) ----
    by_strategy: Dict[str, Decimal] = {}
    by_symbol: Dict[str, Decimal] = {}
    for t in qs:
        s = (_safe_getattr(t, "strategy", "") or "").strip() or "Unspecified Strategy"
        by_strategy[s] = by_strategy.get(s, Decimal("0")) + _to_decimal(_safe_getattr(t, "pnl", 0))
        sym = (_safe_getattr(t, "symbol", "") or "").strip()
        if sym:
            by_symbol[sym] = by_symbol.get(sym, Decimal("0")) + _to_decimal(_safe_getattr(t, "pnl", 0))

    items = [{"label": k, "pl": float(v)} for k, v in by_strategy.items()]
    items += [{"label": f"Asset: {k}", "pl": float(v)} for k, v in by_symbol.items()]
    # Sort by absolute contribution and cap a handful
    items.sort(key=lambda x: abs(x["pl"]), reverse=True)
    strategy_breakdown = items[:6] if items else []

    # ---- Strategy options (for the select) — use Strategy records, not past trades ----
    strategy_qs = Strategy.objects.filter(user=request.user)
    tenant = _current_tenant(request)
    if tenant is not None and hasattr(Strategy, "tenant"):
        strategy_qs = strategy_qs.filter(tenant=tenant)
    strategy_options = list(strategy_qs.order_by("name").values_list("name", flat=True))
    trade_date_default = today.strftime("%Y-%m-%d")

    # ---- Strategy Edge Overview (expectancy-first) ----
    strategy_edges = _build_strategy_edges(qs)

    context = {
        # Header / identity
        "user_external_id": _user_external_id(request.user),

        # Cards
        "expectancy_r": metrics["expectancy"],
        "balance": metrics["account_balance"],
        "net_pl": metrics["net_pl"],
        "max_dd": metrics["max_drawdown"],
        "profit_factor": metrics["profit_factor"],
        "win_rate": metrics["win_rate"],
        "avg_rrr": metrics["avg_r"],

        # Chart
        "equity_labels_json": json.dumps(chart["labels"]),
        "equity_values_json": json.dumps(chart["values"]),

        # Calendar
        "cal_title": cal_title,
        "cal_start_offset": cal_start_offset,
        "cal_days": cal_days,

        # Strategy Edge
        "strategy_edges": strategy_edges,

        # Calendar nav helpers
        "cal_prev_year": cal_prev_year,
        "cal_prev_month": cal_prev_month,
        "cal_next_year": cal_next_year,
        "cal_next_month": cal_next_month,

        # Streaks + breakdown
        "streaks": streaks,
        "strategy_breakdown": strategy_breakdown,

        # Form helpers
        "strategy_options": strategy_options,
        "trade_date": trade_date_default,
    }
    return render(request, "dashboard.html", context)


@login_required
def settings_view(request: HttpRequest) -> HttpResponse:
    """
    User-specific settings page.
    GET -> render settings page with current profile preferences + strategies.
    POST -> update settings or create strategies (expects JSON).
    """
    profile = getattr(request.user, "profile", None)
    if not profile:
        return JsonResponse({"error": "Profile not found"}, status=404)

    if request.method == "POST":
        try:
            data = json.loads(request.body.decode("utf-8"))
        except Exception:
            data = {}

        # Update only known sections (no fallbacks)
        action_type = data.get("type")
        if action_type == "general":
            # Leave theme behavior as-is per your request
            profile.preferred_currency = data.get("currency", profile.preferred_currency)
            profile.save()
            return JsonResponse({"status": "success", "message": "Settings updated"})
        elif action_type == "strategy":
            # Create or upsert a Strategy for this user
            name = (data.get("name") or "").strip()
            notes = (data.get("notes") or data.get("desc") or "").strip()
            if not name:
                return JsonResponse({"error": "Strategy name is required"}, status=400)

            tenant = _current_tenant(request)
            defaults = {"notes": notes}
            kwargs = {"user": request.user, "name": name}
            if tenant is not None and hasattr(Strategy, "tenant"):
                kwargs["tenant"] = tenant

            # get_or_create by (user, name[, tenant])
            st, created = Strategy.objects.get_or_create(defaults=defaults, **kwargs)
            if not created and notes:
                st.notes = notes
                st.save()

            return JsonResponse({"status": "success", "strategy": {"id": st.id, "name": st.name, "notes": getattr(st, "notes", "")}})

        return JsonResponse({"error": "Unknown settings type"}, status=400)

    # GET — render template with profile + list of user strategies
    strategy_qs = Strategy.objects.filter(user=request.user)
    tenant = _current_tenant(request)
    if tenant is not None and hasattr(Strategy, "tenant"):
        strategy_qs = strategy_qs.filter(tenant=tenant)
    strategies = list(strategy_qs.order_by("name").values("id", "name", "notes"))

    context = {
        "user": request.user,
        "currency": profile.preferred_currency,
        "themePref": profile.preferred_theme,                 # left untouched
        "goal": profile.trading_goal,                         # left as-is
        "notifications_enabled": profile.notifications_enabled,
        "strategies": strategies,                             # <— used by template
    }
    return render(request, "settings.html", context)


# ------------------------------
# Trade APIs
# ------------------------------

@login_required
@require_POST
def add_trade_view(request: HttpRequest) -> HttpResponse:
    """
    Save a trade in DB. Accepts JSON or form POST.
    Expected fields: symbol, tradeDate (YYYY-MM-DD), pnl, initialRisk, strategy, note
    Tenant-aware: new trades get request.tenant if model has `tenant`.
    """
    if Trade is None:
        return JsonResponse({"error": "Trade model not found. Define core.models.Trade."}, status=500)

    # Parse input
    is_json = "application/json" in (request.headers.get("Content-Type") or "")
    if is_json:
        try:
            payload = json.loads(request.body.decode("utf-8"))
        except Exception:
            payload = {}
        symbol = (payload.get("symbol") or "").strip().upper()
        trade_date_str = (payload.get("tradeDate") or "").strip()
        pnl = _to_decimal(payload.get("pnl"))
        initial_risk = _to_decimal(payload.get("initialRisk"))
        strategy = (payload.get("strategy") or "").strip()
        note = (payload.get("note") or "").strip()
    else:
        symbol = (request.POST.get("symbol") or "").strip().upper()
        trade_date_str = (request.POST.get("tradeDate") or "").strip()
        pnl = _to_decimal(request.POST.get("pnl"))
        initial_risk = _to_decimal(request.POST.get("initialRisk"))
        strategy = (request.POST.get("strategy") or "").strip()
        note = (request.POST.get("tradeNote") or request.POST.get("note") or "").strip()

    # Validate
    td = parse_date(trade_date_str) or date.today()

    # Create instance robustly
    trade = Trade(user=request.user)

    # Attach tenant if supported
    tenant = _current_tenant(request)
    if hasattr(trade, "tenant") and tenant is not None:
        trade.tenant = tenant  # type: ignore

    if hasattr(trade, "symbol"):
        trade.symbol = symbol
    if hasattr(trade, "trade_date"):
        trade.trade_date = td
    if hasattr(trade, "pnl"):
        trade.pnl = pnl
    if hasattr(trade, "initial_risk"):
        trade.initial_risk = initial_risk
    if hasattr(trade, "r_multiple"):
        trade.r_multiple = (pnl / initial_risk) if initial_risk != 0 else Decimal("0")
    if hasattr(trade, "strategy"):
        trade.strategy = strategy
    if hasattr(trade, "note"):
        trade.note = note

    trade.save()

    if is_json:
        return JsonResponse({"status": "ok", "id": trade.id})

    # If form POST, go back to dashboard
    return redirect("dashboard")


@login_required
@require_GET
def trades_list_api(request: HttpRequest) -> JsonResponse:
    """Return user's trades as JSON (tenant-aware)."""
    if Trade is None:
        return JsonResponse({"trades": []})
    qs = _get_user_trades(request)
    data = []
    for t in qs:
        td = _safe_getattr(t, "trade_date", None)
        if isinstance(td, datetime):
            td = td.date()
        data.append({
            "id": t.id,
            "symbol": _safe_getattr(t, "symbol", ""),
            "trade_date": (td or date.today()).strftime("%Y-%m-%d"),
            "pnl": float(_to_decimal(_safe_getattr(t, "pnl", 0))),
            "initial_risk": float(_to_decimal(_safe_getattr(t, "initial_risk", 0))),
            "r_multiple": float(_trade_r_multiple(t)),
            "strategy": _safe_getattr(t, "strategy", ""),
            "note": _safe_getattr(t, "note", ""),
        })
    return JsonResponse({"trades": data})


@login_required
@require_GET
def metrics_api(request: HttpRequest) -> JsonResponse:
    """Return computed metrics + chart as JSON (tenant-aware)."""
    qs = _get_user_trades(request)
    metrics, chart = _build_metrics_and_chart(qs)
    return JsonResponse({"metrics": metrics, "chart": chart})


# ------------------------------
# Settings helpers (placeholder)
# ------------------------------

@csrf_exempt
@login_required
def save_strategy(request: HttpRequest) -> JsonResponse:
    if request.method != "POST":
        return JsonResponse({"error": "invalid method"}, status=400)
    try:
        data = json.loads(request.body.decode("utf-8"))
    except Exception:
        data = {}
    # Persist later when you add a Strategy model.
    return JsonResponse({"status": "ok", "strategy": data})
