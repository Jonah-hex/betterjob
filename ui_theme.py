"""Professional Streamlit UI theme for BetterJob."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable, Optional

import streamlit as st

CUSTOM_CSS = """
<style>
    .bj-hero {
        background: linear-gradient(135deg, #0f172a 0%, #1e3a5f 50%, #0d9488 100%);
        padding: 1.5rem 2rem;
        border-radius: 12px;
        color: #f8fafc;
        margin-bottom: 1.5rem;
        box-shadow: 0 4px 20px rgba(15, 23, 42, 0.15);
    }
    .bj-hero h1 { color: #f8fafc !important; margin: 0; font-size: 1.75rem; }
    .bj-hero p { color: #cbd5e1; margin: 0.5rem 0 0 0; font-size: 0.95rem; }
    .bj-metric-card {
        background: #f8fafc;
        border: 1px solid #e2e8f0;
        border-radius: 10px;
        padding: 1rem;
        text-align: center;
    }
    .bj-metric-card .value { font-size: 1.75rem; font-weight: 700; color: #0f172a; }
    .bj-metric-card .label { font-size: 0.8rem; color: #64748b; text-transform: uppercase; letter-spacing: 0.05em; }
    .bj-fit-high { color: #059669; font-weight: 600; }
    .bj-fit-mid { color: #d97706; font-weight: 600; }
    .bj-fit-low { color: #94a3b8; }
    .bj-pipeline-step {
        border-left: 3px solid #0d9488;
        padding-left: 1rem;
        margin: 0.5rem 0;
    }
    div[data-testid="stSidebar"] { background: linear-gradient(180deg, #f1f5f9 0%, #fff 100%); }
    .stTabs [data-baseweb="tab-list"] { gap: 4px; }
    .stTabs [data-baseweb="tab"] {
        border-radius: 8px 8px 0 0;
        padding: 0.5rem 1rem;
        font-weight: 500;
    }
</style>
"""


def inject() -> None:
    st.markdown(CUSTOM_CSS, unsafe_allow_html=True)


def hero(title: str, subtitle: str) -> None:
    st.markdown(
        f'<div class="bj-hero"><h1>{title}</h1><p>{subtitle}</p></div>',
        unsafe_allow_html=True,
    )


def metric_card(label: str, value: str | int, col) -> None:
    with col:
        st.markdown(
            f'<div class="bj-metric-card"><div class="value">{value}</div>'
            f'<div class="label">{label}</div></div>',
            unsafe_allow_html=True,
        )


def fit_badge(score: int) -> str:
    if score >= 75:
        return f'<span class="bj-fit-high">{score}%</span>'
    if score >= 50:
        return f'<span class="bj-fit-mid">{score}%</span>'
    return f'<span class="bj-fit-low">{score}%</span>'


def format_local_timestamp(ts: float) -> str:
    """Unix timestamp → local 12-hour string."""
    return format_local_datetime(
        datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    )


def format_eta(seconds: int) -> str:
    """Human-readable Arabic ETA (seconds → د/ث)."""
    seconds = max(0, int(seconds))
    if seconds < 60:
        return f"{seconds} ث"
    mins, secs = divmod(seconds, 60)
    if mins < 60:
        return f"{mins} د {secs} ث" if secs else f"{mins} د"
    hours, mins = divmod(mins, 60)
    if mins:
        return f"{hours} س {mins} د"
    return f"{hours} س"


def estimate_send_eta_seconds(current_index: int, total: int, config: dict[str, Any]) -> int:
    """Rough ETA for remaining emails (SMTP + delay between sends)."""
    if total <= 0 or current_index <= 0:
        return 0
    sending = config.get("sending", {})
    dry = sending.get("dry_run", False)
    delay = int(sending.get("delay_seconds_between", 30))
    per_email = 8 + (2 if dry else delay)
    remaining = max(0, total - current_index + 1)
    return remaining * per_email


def make_streamlit_progress(
    label: str = "بدء التشغيل...",
) -> tuple[Callable[..., None], Any, Any]:
    """Progress bar + ETA line for pipeline/send callbacks."""
    prog = st.progress(0, text=label)
    eta_ph = st.empty()

    def callback(
        step: int,
        total: int,
        msg: str,
        eta_seconds: Optional[int] = None,
    ) -> None:
        frac = (step / total) if total else 0.0
        line = msg
        if eta_seconds is not None and eta_seconds > 0:
            eta_label = format_eta(eta_seconds)
            line = f"{msg} | ⏱ ~{eta_label}"
            eta_ph.info(f"⏱ **الوقت المتبقي التقريبي:** {eta_label}")
        else:
            eta_ph.empty()
        prog.progress(min(max(frac, 0.0), 1.0), text=line)

    return callback, prog, eta_ph


def format_local_datetime(value: str | None, empty: str = "—") -> str:
    """UTC/ISO timestamp → local time, 12-hour (ص/م)."""
    if not value or not str(value).strip():
        return empty
    raw = str(value).strip()
    try:
        if raw.endswith("Z"):
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        elif len(raw) >= 19 and raw[10] in ("T", " "):
            if "+" in raw[10:] or raw.endswith("+00:00"):
                dt = datetime.fromisoformat(raw.replace(" ", "T", 1) if "T" not in raw else raw)
            else:
                dt = datetime.strptime(raw[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        else:
            dt = datetime.fromisoformat(raw)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
        local = dt.astimezone()
        hour = int(local.strftime("%I"))
        minute = local.strftime("%M")
        ampm = local.strftime("%p").replace("AM", "ص").replace("PM", "م")
        return f"{local.strftime('%Y-%m-%d')} {hour}:{minute} {ampm}"
    except (ValueError, TypeError):
        return raw
