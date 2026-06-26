"""BetterJob — Survey Job Outreach Dashboard (Streamlit)."""

from __future__ import annotations

import os
from pathlib import Path

import pandas as pd
import streamlit as st
import yaml
from dotenv import load_dotenv

import importlib

import compose
import database as db
import extract_email
import ats_audit
import cv_generate

import discover_multi
import send_email
import ui_theme
import job_fit
import whatsapp_outreach
import outreach_quality

db = importlib.reload(db)

import auto_run
import delivery_tracking

send_email = importlib.reload(send_email)
auto_run = importlib.reload(auto_run)
delivery_tracking = importlib.reload(delivery_tracking)
discover_multi = importlib.reload(discover_multi)
ui_theme = importlib.reload(ui_theme)
job_fit = importlib.reload(job_fit)
whatsapp_outreach = importlib.reload(whatsapp_outreach)
outreach_quality = importlib.reload(outreach_quality)

check_prerequisites = auto_run.check_prerequisites
run_discovery = auto_run.run_discovery
run_extraction = auto_run.run_extraction
run_sending = auto_run.run_sending
run_apply_new = auto_run.run_apply_new
run_pipeline = auto_run.run_pipeline
run_discover_only = auto_run.run_discover_only
run_prepare_only = auto_run.run_prepare_only
run_send_only = auto_run.run_send_only
run_extract_contacts_export = auto_run.run_extract_contacts_export
PIPELINE_STEPS = auto_run.PIPELINE_STEPS

import export_contacts
export_contacts = importlib.reload(export_contacts)
from check_domain import check_domain_setup

BASE_DIR = Path(__file__).parent
load_dotenv(BASE_DIR / ".env", override=True)

st.set_page_config(
    page_title="BetterJob — مساح عام",
    page_icon="📐",
    layout="wide",
    initial_sidebar_state="expanded",
)
ui_theme.inject()

STATUS_LABELS = {
    "discovered": "🔍 مكتشفة",
    "email_found": "✉️ إيميل موجود",
    "no_email": "❌ بدون إيميل",
    "approved": "⏳ بانتظار الإرسال",
    "sent": "✅ تم الإرسال",
    "replied": "💬 رد",
    "rejected": "🚫 مرفوض",
}

SOURCE_LABELS = {
    "csv": "📄 CSV",
    "google": "🗺️ Google",
    "overpass": "🌍 OSM",
    "directory": "📒 دليل ويب",
    "domains": "🌐 دومين",
    "linkedin": "💼 LinkedIn",
    "careers_portal": "🎯 بوابات توظيف",
    "deep_search": "🔬 بحث HR",
    "unknown": "—",
}


@st.cache_resource
def init():
    db.init_db()
    return True


def load_config() -> dict:
    with open(BASE_DIR / "config.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


def status_badge(status: str) -> str:
    return STATUS_LABELS.get(status, status)


def fmt_website_url(url: str | None) -> str:
    """Normalize website for Streamlit LinkColumn."""
    if not url or not str(url).strip():
        return ""
    u = str(url).strip()
    if u in ("—", "-", "None"):
        return ""
    if not u.startswith(("http://", "https://")):
        u = "https://" + u
    return u


def resolve_website(row: dict) -> str:
    """Website from row or company record."""
    url = row.get("website") or ""
    if not url and row.get("company_id"):
        company = db.get_company(row["company_id"])
        if company:
            url = company.get("website") or ""
    return fmt_website_url(url)


def show_companies_table(df: pd.DataFrame, height: int | None = None) -> None:
    """Render dataframe with clickable website column when present."""
    kwargs: dict = {"use_container_width": True, "hide_index": True}
    if height:
        kwargs["height"] = height
    site_col = None
    for name in ("الموقع الإلكتروني", "الموقع"):
        if name in df.columns:
            site_col = name
            break
    if site_col:
        kwargs["column_config"] = {
            site_col: st.column_config.LinkColumn(
                site_col,
                help="اضغط لفتح موقع الشركة ومراجعة صفحة التوظيف / اتصل بنا",
            ),
        }
    st.dataframe(df, **kwargs)


def get_prioritized_sendable(config: dict) -> list[dict]:
    cities = config.get("automation", {}).get("target_cities")
    allowed, _ = outreach_quality.prioritize_sendable(
        db.get_sendable_companies(cities), config
    )
    return allowed


init()
config = load_config()
profile = config.get("profile", {})
ATS_CV_LABEL = send_email.attachment_display_name(send_email.get_cv_path(), config)
UPLOADED_CV_LABEL = send_email.attachment_display_name(send_email.get_uploaded_cv_path(), config)

# ── Sidebar ──────────────────────────────────────────────────────
st.sidebar.title("📐 BetterJob")
st.sidebar.caption(f"{profile.get('full_name_ar', '')} — {profile.get('title_ar', '')}")
st.sidebar.markdown("---")

dry_run = st.sidebar.toggle(
    "وضع Dry-Run (تجريبي)",
    value=config.get("sending", {}).get("dry_run", False),
    help="مفعّل = لا يرسل فعلياً، يسجل فقط",
)
config["sending"]["dry_run"] = dry_run

discovery_mode = config.get("discovery_provider", "csv")
email_mode = config.get("email_mode", "hotmail_brevo")
sender = profile.get("sender_email", "")
remaining = config["sending"]["max_per_day"] - db.count_sent_today()

st.sidebar.markdown(f"**الاكتشاف:** `{discovery_mode}`")
st.sidebar.markdown(f"**البريد:** `{sender}`")
st.sidebar.markdown(f"**Brevo:** {os.getenv('EMAIL_PROVIDER', '—')}")
st.sidebar.markdown(f"**مُرسل اليوم:** {db.count_sent_today()} / {config['sending']['max_per_day']}")
st.sidebar.markdown(f"**متبقي:** {max(0, remaining)}")
st.sidebar.markdown("---")

if st.sidebar.button("🔌 اختبار البريد", use_container_width=True, key="sidebar_test_smtp"):
    result = send_email.test_connection(config)
    if result["status"] == "ok":
        st.sidebar.success(result["message"])
    else:
        st.sidebar.error(result["message"])

st.sidebar.markdown("---")
st.sidebar.markdown("**🎯 BetterJob Pro:** `run_pro.bat` → http://localhost:8502")
st.sidebar.info(f"جدة + أبها | {config['sending']['max_per_day']} إيميل/يوم | ⚡ مركز العمل الموحّد")

# ── Tabs ─────────────────────────────────────────────────────────
tab_home, tab_work, tab_companies, tab_delivery, tab_send, tab_whatsapp, tab_log, tab_cv, tab_settings = st.tabs(
    [
        "🏠 الرئيسية",
        "⚡ مركز العمل",
        "🏢 الشركات",
        "📬 تتبع الإرسال",
        "✉️ إرسال يدوي",
        "💬 واتساب",
        "📋 السجل",
        "📄 CV",
        "⚙️ إعدادات",
    ]
)

stats = db.get_stats()
sendable = get_prioritized_sendable(config)
wa_followup = outreach_quality.get_whatsapp_followup_targets(config)

# ── Tab: Home ────────────────────────────────────────────────────
with tab_home:
    ui_theme.hero(
        profile.get("full_name_ar", ""),
        f"{profile.get('title_ar', '')} | {profile.get('years_experience', 12)} سنة | "
        f"Total Station · GNSS · AutoCAD",
    )

    job_fit.sync_all_scores(config)
    top_fit = job_fit.rank_companies(db.get_companies(), config)[:5]

    c1, c2, c3, c4, c5, c6 = st.columns(6)
    ui_theme.metric_card("الشركات", stats.get("total", 0), c1)
    ui_theme.metric_card("إيميل جاهز", stats.get("email_found", 0), c2)
    ui_theme.metric_card("تم الإرسال", stats.get("sent_confirmed", 0), c3)
    ui_theme.metric_card("جاهز (جودة)", len(sendable), c4)
    ui_theme.metric_card("اليوم", f"{stats.get('sent_today', 0)}/{config['sending']['max_per_day']}", c5)
    ui_theme.metric_card("واتساب Top30", len(wa_followup), c6)

    st.markdown("---")

    col_a, col_b = st.columns(2)
    with col_a:
        st.subheader("حالة النظام")
        checks = check_domain_setup()
        for chk in checks:
            icon = "✅" if chk["status"] == "ok" else "⚠️" if chk["status"] == "warn" else "❌"
            st.write(f"{icon} **{chk['item']}:** {chk['message']}")

        prereq = check_prerequisites(config)
        if prereq:
            st.warning("متطلبات ناقصة:")
            for e in prereq:
                st.write(f"- {e}")
        else:
            st.success("جاهز للتشغيل ✅")

    with col_b:
        st.subheader("سير العمل")
        st.markdown("""
        <div class="bj-pipeline-step">1. اكتشاف — مقاولات · هندسة · مساحة (جدة + أبها)</div>
        <div class="bj-pipeline-step">2. استخراج إيميلات من مواقع الشركات فقط</div>
        <div class="bj-pipeline-step">3. ترتيب حسب ملاءمة السيرة الذاتية</div>
        <div class="bj-pipeline-step">4. إرسال يدوي (حد 5/يوم) + متابعة واتساب</div>
        """, unsafe_allow_html=True)
        st.caption("كل العمليات من تبويب **⚡ مركز العمل** — مصدر واحد للاكتشاف والإرسال")
        cv_ok = send_email.get_cv_info().get("exists", False)
        st.write(f"{ATS_CV_LABEL}: {'✅' if cv_ok else '❌'}")

        if top_fit:
            st.subheader("أعلى ملاءمة")
            for t in top_fit:
                score = t.get("job_fit_score", 0)
                em = t.get("primary_email", "")
                src = t.get("email_source", "")
                tier = outreach_quality.email_tier_label(em, src) if em else ""
                st.markdown(
                    f"**{t['company_name'][:40]}** — "
                    f"{job_fit.fit_label(score)} ({score}%) {tier}",
                    unsafe_allow_html=False,
                )

        if wa_followup:
            st.subheader("📲 متابعة واتساب مقترحة")
            st.caption("أعلى 5 من Top 30 — أُرسل لها إيميل ولم تُتابَع واتساب مؤخراً")
            for t in wa_followup[:5]:
                url = whatsapp_outreach.build_whatsapp_url(
                    t.get("phone", ""),
                    whatsapp_outreach.compose_message(t, config),
                )
                if url:
                    st.markdown(f"- [{t['company_name'][:35]}]({url}) — {t.get('job_fit_score', 0)}%")

    companies = db.get_companies()
    if companies:
        df = pd.DataFrame(companies)
        col1, col2 = st.columns(2)
        with col1:
            if "city" in df.columns:
                st.subheader("حسب المدينة")
                st.bar_chart(df["city"].value_counts())
        with col2:
            if "status" in df.columns:
                st.subheader("حسب الحالة")
                st.bar_chart(df["status"].value_counts())

# ── Tab: Work Center (unified discovery + send) ──────────────────
with tab_work:
    ui_theme.hero(
        "⚡ مركز العمل",
        "مصدر واحد: اكتشاف شركات حقيقية → تجهيز إيميلات → إرسال CV",
    )

    target_cities = config.get("automation", {}).get("target_cities", ["Jeddah", "Abha"])
    delivery_tracking.sync_pipeline(target_cities)
    work_pipeline = delivery_tracking.get_pipeline_summary(target_cities)
    enabled_sources = config.get("discovery", {}).get("sources", [])
    auto_send_on = config.get("automation", {}).get("auto_send", False)

    prereq_errors = check_prerequisites(config)
    raw_pending, skipped_quality = outreach_quality.prioritize_sendable(
        db.get_sendable_companies(target_cities), config
    )
    remaining_today = max(0, config["sending"]["max_per_day"] - db.count_sent_today())

    col_status, col_smtp = st.columns(2)
    with col_status:
        if prereq_errors:
            st.error("متطلبات ناقصة:")
            for err in prereq_errors:
                st.write(f"- {err}")
        else:
            st.success("جاهز للتشغيل ✅")
    with col_smtp:
        smtp = send_email.test_connection(config)
        if smtp["status"] == "ok":
            st.success(smtp["message"])
        else:
            st.warning(smtp["message"])

    wm1, wm2, wm3, wm4, wm5 = st.columns(5)
    ui_theme.metric_card("الشركات", stats.get("total", 0), wm1)
    ui_theme.metric_card("جاهز للإرسال", len(raw_pending), wm2)
    ui_theme.metric_card("تم الإرسال", work_pipeline["completed"], wm3)
    ui_theme.metric_card("اليوم", f"{stats.get('sent_today', 0)}/{config['sending']['max_per_day']}", wm4)
    ui_theme.metric_card("مُستبعد (جودة)", len(skipped_quality), wm5)

    st.markdown("**المسار الموحّد:**")
    step_cols = st.columns(len(PIPELINE_STEPS))
    for col, (_, label) in zip(step_cols, PIPELINE_STEPS):
        with col:
            st.markdown(
                f'<div class="bj-pipeline-step" style="font-size:0.85rem">{label}</div>',
                unsafe_allow_html=True,
            )

    st.markdown("---")

    def _render_pipeline_result(result: dict) -> None:
        if not result.get("success", True):
            for e in result.get("errors", []):
                st.error(e)
            return
        disc = result.get("discovery", {})
        send = result.get("send", {})
        pipe = result.get("pipeline", {})
        queue = result.get("queue", {})
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("شركات جديدة", disc.get("total_new", queue.get("pending_count", "—")))
        c2.metric("أُرسل الآن", send.get("sent", 0) if send else "—")
        c3.metric("تخطّى جودة", send.get("skipped_quality", 0) if send else "—")
        c4.metric("فشل", send.get("failed", 0) if send else "—")
        if send:
            st.caption(f"متبقي اليوم: {send.get('remaining_today', remaining_today)}")
            sent_now = int(send.get("sent", 0) or 0)
            if sent_now == 0:
                q = send.get("queue_size", send.get("eligible", 0))
                st.warning(
                    f"**لم يُرسل شيء في هذه الدورة** — الطابور كان فارغاً أو كل المرشحين مُرسل لهم سابقاً. "
                    f"مرشحون في القاعدة: {q} | جاهز الآن للإرسال: {len(raw_pending)}. "
                    "يُقبل فقط إيميلات من **موقع الشركة** (found_on_page / manual / CSV) — "
                    "لا قوائم دليل ولا careers@ مُخمّن."
                )
        if queue.get("pending_count") is not None and not send:
            st.caption(f"جاهز للإرسال بعد التجهيز: {queue.get('pending_count', 0)}")
        if pipe:
            st.success(
                f"✅ اكتمل | مُرسل كلياً: {pipe.get('completed', 0)} | "
                f"جاهز: {pipe.get('not_sent', 0)} | بدون إيميل: {pipe.get('no_email', 0)}"
            )
        if disc.get("sources"):
            st.caption(f"مصادر الاكتشاف: {', '.join(disc['sources'])}")
        if send and send.get("details"):
            with st.expander("تفاصيل الإرسال"):
                for d in send["details"]:
                    icon = "✅" if d.get("success") else "❌"
                    st.write(f"{icon} {d.get('company')} — {d.get('email', d.get('error', ''))}")

    if st.session_state.get("last_pipeline_run"):
        with st.expander("📊 آخر تشغيل", expanded=False):
            _render_pipeline_result(st.session_state["last_pipeline_run"])

    st.info(
        f"⏱️ ~30 ثانية/إيميل · حد **{config['sending']['max_per_day']}/يوم** · "
        "إيميلات من مواقع الشركات فقط (لا بوابات وظائف) · "
        f"{'إرسال تلقائي مفعّل' if auto_send_on else 'إرسال يدوي — اضغط زر الإرسال'}"
    )

    st.subheader("تشغيل المراحل")
    b_disc, b_prep, b_send, b_full = st.columns(4)

    def _run_stage(fn, label: str, **kwargs) -> None:
        on_progress, prog, eta_ph = ui_theme.make_streamlit_progress(label)
        try:
            result = fn(config, on_progress=on_progress, **kwargs)
            st.session_state["last_pipeline_run"] = result
            prog.progress(1.0, text="اكتمل!")
            eta_ph.empty()
            if result.get("success", True):
                _render_pipeline_result(result)
            else:
                for e in result.get("errors", []):
                    st.error(e)
            st.rerun()
        except Exception as exc:
            eta_ph.empty()
            st.error(str(exc))

    with b_disc:
        if st.button("🔍 ① اكتشاف شركات", use_container_width=True, key="work_discover"):
            _run_stage(run_discover_only, "اكتشاف شركات...")

    with b_prep:
        if st.button("📧 ② تجهيز إيميلات", use_container_width=True, key="work_prepare"):
            _run_stage(run_prepare_only, "تجهيز الإيميلات...")

    with b_send:
        if st.button("📤 ③ إرسال CV", type="primary", use_container_width=True, key="work_send"):
            if prereq_errors:
                st.error("أكمل المتطلبات أولاً")
            elif dry_run:
                st.warning("أوقف Dry-Run من الشريط الجانبي للإرسال الفعلي")
            elif not raw_pending:
                st.warning("لا شركات جاهزة — نفّذ اكتشافاً وتجهيزاً أولاً")
            elif remaining_today <= 0:
                st.warning("تم الوصول للحد اليومي")
            else:
                _run_stage(
                    run_send_only,
                    f"إرسال حتى {min(len(raw_pending), remaining_today)} شركة...",
                )

    with b_full:
        if st.button("⚡ دورة كاملة", type="primary", use_container_width=True, key="work_full"):
            if prereq_errors:
                st.error("أكمل المتطلبات أولاً")
            elif dry_run:
                st.warning("أوقف Dry-Run من الشريط الجانبي للإرسال الفعلي")
            else:
                _run_stage(
                    run_pipeline,
                    "دورة كاملة: اكتشاف → تجهيز → إرسال...",
                    discover=True,
                    prepare=True,
                    send=True,
                )

    st.markdown("---")
    st.subheader("📋 طابور الإرسال")
    if raw_pending:
        st.dataframe(
            pd.DataFrame([{
                "الشركة": c["company_name"],
                "ملاءمة": f"{c.get('job_fit_score', 0)}%",
                "المدينة": c.get("city", ""),
                "الإيميل": c.get("email", ""),
                "نوع الإيميل": outreach_quality.email_tier_label(
                    c.get("email", ""), c.get("email_source", "")
                ),
                "المصدر": SOURCE_LABELS.get(c.get("discovery_source", ""), c.get("discovery_source", "—")),
            } for c in raw_pending[:30]]),
            use_container_width=True,
            hide_index=True,
        )
        if len(raw_pending) > 30:
            st.caption(f"يعرض 30 من {len(raw_pending)} — يُرسل حسب الحد اليومي والملاءمة")
    else:
        st.warning(
            "**لا شركات جاهزة للإرسال** — نفّذ «اكتشاف» ثم «تجهيز». "
            "إن بقيت صفراً: إما أُرسل لها سابقاً، أو إيميلاتها من دليل ويب/قوائم (غير مقبولة)، "
            "أو لم يُستخرج إيميل من موقع الشركة بعد."
        )

    if skipped_quality:
        with st.expander(f"⚠️ مُستبعدة تلقائياً ({len(skipped_quality)})"):
            st.dataframe(pd.DataFrame([{
                "الشركة": c["company_name"],
                "ملاءمة": f"{c.get('job_fit_score', 0)}%",
                "الإيميل": c.get("email", ""),
                "السبب": c.get("skip_reason", ""),
            } for c in skipped_quality[:20]]), use_container_width=True, hide_index=True)

    st.markdown("---")
    with st.expander("📧 استخراج جهات الاتصال + Excel"):
        st.caption("زيارة مواقع الشركات → استخراج الإيميل → تصدير")
        if st.button("📧 استخراج وتحديث الجدول", use_container_width=True, key="work_extract_contacts"):
            with st.spinner("جاري زيارة المواقع..."):
                result = run_extract_contacts_export(config)
                st.session_state["contacts_export"] = result
                st.success(
                    f"وُجد: {result['extract'].get('email_found', 0)} إيميل | "
                    f"إجمالي بإيميل: {result['with_email']}"
                )
                st.rerun()

        contacts_data = st.session_state.get("contacts_export")
        if contacts_data and contacts_data.get("dataframe") is not None:
            df_email = contacts_data.get("dataframe_email", contacts_data["dataframe"])
            show_companies_table(df_email, height=300)
            try:
                xlsx_bytes = export_contacts.dataframe_to_excel_bytes(df_email)
                st.download_button(
                    label="⬇️ تحميل Excel",
                    data=xlsx_bytes,
                    file_name=export_contacts.export_filename(),
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True,
                    key="work_download_xlsx",
                )
            except Exception:
                pass

    with st.expander("المصادر المفعّلة"):
        for src, label in discover_multi.SOURCE_LABELS.items():
            on = src in enabled_sources
            st.write(f"{'✅' if on else '⬜'} **{label}**")
        st.caption(
            f"المدن: {', '.join(target_cities)} | "
            f"الحد اليومي: {config['sending']['max_per_day']} | "
            f"Dry-Run: {'نعم' if dry_run else 'لا'}"
        )

    if dry_run:
        st.warning("⚠️ Dry-Run مفعّل — لن يُرسل فعلياً حتى توقفه من الشريط الجانبي.")

# ── Tab: Companies ───────────────────────────────────────────────
with tab_companies:
    st.header("🏢 الشركات")

    sub_all, sub_sent, sub_queue = st.tabs([
        "📋 كل الشركات",
        "✅ تم الإرسال فعلياً",
        "📋 طابور الجاهز",
    ])

    with sub_sent:
        st.subheader("الشركات التي وصلها CV فعلياً")
        sent_city = st.selectbox("المدينة", ["الكل", "Jeddah", "Abha"], key="sent_city_filter")
        sent_rows = db.get_sent_companies(
            city=None if sent_city == "الكل" else sent_city,
            limit=500,
        )
        if sent_rows:
            show_companies_table(pd.DataFrame([{
                "الشركة": r["company_name"],
                "الإيميل": r["email"],
                "المدينة": r.get("city", ""),
                "القطاع": r.get("sector", ""),
                "الموقع الإلكتروني": resolve_website(r),
                "المصدر": SOURCE_LABELS.get(r.get("discovery_source", ""), r.get("discovery_source", "—")),
                "تاريخ الإرسال": ui_theme.format_local_datetime(r.get("sent_at")),
            } for r in sent_rows]))
            st.caption(f"إجمالي تم الإرسال: {len(sent_rows)}")
        else:
            st.info("لم يُرسل لأي شركة بعد — سيظهر الجدول تلقائياً بعد الإرسال الناجح")

    with sub_queue:
        st.subheader("الشركات الجاهزة للإرسال")
        st.caption("للتشغيل استخدم تبويب **⚡ مركز العمل** — اكتشاف → تجهيز → إرسال")

        target_cities = config.get("automation", {}).get("target_cities", ["Jeddah", "Abha"])
        raw_pending, skipped_quality = outreach_quality.prioritize_sendable(
            db.get_sendable_companies(target_cities), config
        )
        remaining_today = max(0, config["sending"]["max_per_day"] - db.count_sent_today())

        pm1, pm2, pm3 = st.columns(3)
        pm1.metric("جاهز (جودة عالية)", len(raw_pending))
        pm2.metric("مُستبعد (جودة)", len(skipped_quality))
        pm3.metric("متبقي اليوم", remaining_today)

        if raw_pending:
            show_companies_table(pd.DataFrame([{
                "الشركة": c["company_name"],
                "ملاءمة": f"{c.get('job_fit_score', 0)}%",
                "المدينة": c.get("city", ""),
                "الإيميل": c.get("email", ""),
                "نوع الإيميل": outreach_quality.email_tier_label(
                    c.get("email", ""), c.get("email_source", "")
                ),
                "الموقع الإلكتروني": resolve_website(c),
                "المصدر": SOURCE_LABELS.get(c.get("discovery_source", ""), c.get("discovery_source", "—")),
            } for c in raw_pending[:100]]), height=400)
        else:
            st.info("لا شركات جاهزة — من **⚡ مركز العمل** نفّذ اكتشافاً ثم تجهيز إيميلات")

        if skipped_quality:
            with st.expander(f"⚠️ مُستبعدة ({len(skipped_quality)})"):
                st.dataframe(pd.DataFrame([{
                    "الشركة": c["company_name"],
                    "ملاءمة": f"{c.get('job_fit_score', 0)}%",
                    "الإيميل": c.get("email", ""),
                    "السبب": c.get("skip_reason", ""),
                } for c in skipped_quality[:30]]), use_container_width=True, hide_index=True)

        src_stats = db.get_discovery_stats()
        if src_stats:
            st.markdown("**مصادر الاكتشاف في القاعدة:**")
            cols = st.columns(min(len(src_stats), 5))
            for i, (src, cnt) in enumerate(src_stats.items()):
                cols[i % len(cols)].metric(SOURCE_LABELS.get(src, src), cnt)

    with sub_all:
        f1, f2, f3 = st.columns(3)
        cities = ["الكل", "Jeddah", "Abha"]
        filter_city = f1.selectbox("المدينة", cities, key="all_city_filter")
        filter_status = f2.selectbox("الحالة", ["الكل"] + list(STATUS_LABELS.keys()), key="all_status_filter")
        search = f3.text_input("بحث بالاسم", key="all_search")

        city_param = None if filter_city == "الكل" else filter_city
        status_param = None if filter_status == "الكل" else filter_status
        companies = db.get_companies(status=status_param, city=city_param)

        if search.strip():
            companies = [c for c in companies if search.lower() in c["company_name"].lower()]

        if companies:
            ranked = job_fit.rank_companies(companies, config)
            rows = [{
                "ID": c["id"],
                "الشركة": c["company_name"],
                "ملاءمة": f"{c.get('job_fit_score', 0)}%",
                "المدينة": c.get("city", ""),
                "القطاع": c.get("sector", ""),
                "المصدر": SOURCE_LABELS.get(c.get("discovery_source", ""), c.get("discovery_source", "—")),
                "الإيميل": c.get("primary_email", "—"),
                "جودة الإيميل": outreach_quality.email_tier_label(
                    c.get("primary_email", "") or "",
                    c.get("email_source", "") or "",
                ) if c.get("primary_email") else "—",
                "الحالة": status_badge(c.get("status", "")),
                "LinkedIn": c.get("linkedin_url", "") or "—",
                "الموقع الإلكتروني": resolve_website(c),
            } for c in ranked]
            show_companies_table(pd.DataFrame(rows))
            st.caption(f"عرض {len(companies)} شركة | جاهز للإرسال: {len(sendable)}")
        else:
            st.info("لا توجد شركات — استخدم **⚡ مركز العمل** للاكتشاف")

# ── Tab: Delivery Tracking ───────────────────────────────────────
with tab_delivery:
    st.header("📬 تتبع الإرسال")
    st.caption("عرض ومتابعة — للإرسال الجديد استخدم **⚡ مركز العمل**")

    target_cities = config.get("automation", {}).get("target_cities", ["Jeddah", "Abha"])
    delivery_tracking.sync_pipeline(target_cities)
    pipeline = delivery_tracking.get_pipeline_summary(target_cities)

    dm1, dm2, dm3, dm4, dm5 = st.columns(5)
    dm1.metric("✅ تم الإرسال", pipeline["completed"])
    dm2.metric("⏳ في الطابور", pipeline["pending"])
    dm3.metric("📭 جاهز للإرسال", pipeline["not_sent"])
    dm4.metric("❌ فشل غير محلول", pipeline["failed"])
    dm5.metric("🚫 بدون إيميل", pipeline["no_email"])

    st.markdown("---")
    tr_completed, tr_pending, tr_not_sent, tr_failed, tr_no_email = st.tabs([
        "✅ تم الإرسال",
        "⏳ في الطابور",
        "📭 جاهز للإرسال",
        "❌ فشل غير محلول",
        "🚫 بدون إيميل",
    ])

    def _company_rows(items: list) -> list:
        return [{
            "الشركة": c.get("company_name", ""),
            "الإيميل": c.get("email", c.get("primary_email", "—")),
            "المدينة": c.get("city", ""),
            "الموقع الإلكتروني": resolve_website(c),
            "المصدر": SOURCE_LABELS.get(c.get("discovery_source", ""), c.get("discovery_source", "—")),
        } for c in items]

    with tr_completed:
        items = pipeline["completed_list"]
        if items:
            show_companies_table(pd.DataFrame([{
                "الشركة": r["company_name"],
                "الإيميل": r["email"],
                "المدينة": r.get("city", ""),
                "القطاع": r.get("sector", ""),
                "الموقع الإلكتروني": resolve_website(r),
                "تاريخ الإرسال": ui_theme.format_local_datetime(r.get("sent_at")),
                "CV": "✅" if r.get("cv_attached", 1) else "—",
                "المصدر": SOURCE_LABELS.get(r.get("discovery_source", ""), r.get("discovery_source", "—")),
            } for r in items]), height=400)
            st.caption(f"إجمالي: {len(items)} شركة — SMTP قبل الإرسال بنجاح")
            with st.expander("تسجيل رد HR (اختياري)"):
                st.caption("عند استلام رد من الشركة — للمتابعة فقط، لا يؤثر على الإرسال")
                confirm_opts = {
                    f"{r['company_name']} — {r['email']}": r["company_id"]
                    for r in items
                }
                sel_reply = st.selectbox("الشركة", ["—"] + list(confirm_opts.keys()), key="confirm_replied")
                if sel_reply != "—" and st.button("💬 سجّل رد HR", key="btn_confirm_replied"):
                    cid = confirm_opts[sel_reply]
                    row = next(r for r in items if r["company_id"] == cid)
                    delivery_tracking.mark_company_replied(cid, row.get("outreach_log_id"))
                    st.success(f"تم تسجيل الرد لـ {sel_reply.split(' — ')[0]}")
                    st.rerun()
        else:
            st.info("لم يُرسل لأي شركة بعد")

    with tr_pending:
        items = pipeline["pending_list"]
        if items:
            st.dataframe(pd.DataFrame([{
                "الشركة": r["company_name"],
                "الإيميل": r["email"],
                "الحالة": delivery_tracking.label(r.get("status", "")),
                "محاولات": r.get("attempts", 0),
                "آخر تحديث": ui_theme.format_local_datetime(r.get("updated_at")),
            } for r in items]), use_container_width=True, hide_index=True)
            if st.button("📤 إرسال المعلّق الآن", type="primary", key="send_pending_batch"):
                on_progress, prog, eta_ph = ui_theme.make_streamlit_progress("جاري إرسال المعلّق...")
                try:
                    result = run_apply_new(config, on_progress=on_progress)
                    prog.progress(1.0, text="اكتمل!")
                    eta_ph.empty()
                    st.success(f"أُرسل: {result['sent']} | فشل: {result['failed']}")
                    st.rerun()
                except Exception as exc:
                    eta_ph.empty()
                    st.error(str(exc))
        else:
            st.info("لا توجد رسائل معلقة — من **⚡ مركز العمل** نفّذ اكتشافاً أو انتظر الحد اليومي")

    with tr_not_sent:
        items = pipeline["not_sent_list"]
        if items:
            show_companies_table(pd.DataFrame(_company_rows(items)))
            if st.button("📤 تقديم CV للجميع", type="primary", key="send_not_sent_batch"):
                on_progress, prog, eta_ph = ui_theme.make_streamlit_progress("جاري الإرسال...")
                try:
                    result = run_apply_new(config, on_progress=on_progress)
                    prog.progress(1.0, text="اكتمل!")
                    eta_ph.empty()
                    st.success(f"أُرسل: {result['sent']} | فشل: {result['failed']}")
                    st.rerun()
                except Exception as exc:
                    eta_ph.empty()
                    st.error(str(exc))
        else:
            st.success("جميع الشركات ذات الإيميل تم التعامل معها")

    with tr_failed:
        items = pipeline["failed_list"]
        st.caption("آخر محاولة إرسال فاشلة ولم يُعاد الإرسال بنجاح بعدها")
        if items:
            st.dataframe(pd.DataFrame([{
                "الشركة": r.get("company_name", ""),
                "الإيميل": r.get("email", ""),
                "التاريخ": ui_theme.format_local_datetime(r.get("sent_at")),
                "الخطأ": r.get("error_message", ""),
            } for r in items]), use_container_width=True, hide_index=True)
            retry_opts = {
                f"{r.get('company_name', '')} — {r.get('email', '')}": r["company_id"]
                for r in items
            }
            sel_retry = st.selectbox("إعادة المحاولة", ["—"] + list(retry_opts.keys()), key="retry_failed")
            if sel_retry != "—" and st.button("🔄 إعادة إرسال", key="btn_retry_failed"):
                cid = retry_opts[sel_retry]
                delivery_tracking.retry_failed(cid, target_cities)
                result = send_email.send_to_company(cid, config, skip_approval=True)
                if result.get("success"):
                    st.success("تمت إعادة الإرسال")
                else:
                    st.error(result.get("error", "فشل"))
                st.rerun()
        else:
            st.success("لا توجد محاولات فاشلة غير محلولة ✅")

    with tr_no_email:
        items = pipeline["no_email_list"]
        if items:
            show_companies_table(pd.DataFrame([{
                "الشركة": c["company_name"],
                "المدينة": c.get("city", ""),
                "الموقع الإلكتروني": resolve_website(c),
                "الحالة": status_badge(c.get("status", "")),
            } for c in items]))
            if st.button("📧 استخراج إيميلات", key="extract_no_email"):
                result = run_extraction(config)
                st.success(f"وُجد: {result['email_found']} | بدون: {result['no_email']}")
                st.rerun()
        else:
            st.success("جميع الشركات لديها إيميل أو تم التعامل معها")

# ── Tab: Send ────────────────────────────────────────────────────
with tab_send:
    st.header("✉️ معاينة وإرسال")

    email_companies = [c for c in db.get_companies() if c.get("primary_email")]
    if not email_companies:
        st.info("لا توجد شركات بإيميل")
    else:
        options = {
            f"{c['company_name']} — {c.get('city', '')} ({c.get('primary_email', '')})": c["id"]
            for c in email_companies
        }
        sel = st.selectbox("اختر شركة", list(options.keys()))
        company = db.get_company(options[sel])
        if company:
            msg = compose.compose_for_company(company, config)
            st.text_input("Subject", msg["subject"], disabled=True)
            ca, ce = st.columns(2)
            with ca:
                st.text_area("عربي", msg["body_ar"], height=300)
            with ce:
                st.text_area("English", msg["body_en"], height=300)

            if st.button("📤 إرسال لهذه الشركة", type="primary", key="send_single_company"):
                db.update_company_status(company["id"], "approved")
                result = send_email.send_to_company(company["id"], config, skip_approval=True)
                if result.get("success"):
                    mode = "تجريبي" if result.get("dry_run") else "فعلي"
                    st.success(f"تم الإرسال ({mode})")
                else:
                    st.error(result.get("error", "فشل"))

# ── Tab: WhatsApp ────────────────────────────────────────────────
with tab_whatsapp:
    st.header("💬 متابعة عبر واتساب")
    st.caption("بعد الإيميل — ركّز على Top 30 الأعلى ملاءمة")

    target_cities = config.get("automation", {}).get("target_cities", ["Jeddah", "Abha"])
    followup_top = outreach_quality.get_whatsapp_followup_targets(config)
    qcfg = outreach_quality.quality_settings(config)

    w1, w2, w3, w4 = st.columns(4)
    w1.metric("📲 Top 30 مقترحة", len(followup_top))
    w2.metric("حد الملاءمة", f"{qcfg.get('whatsapp_min_fit', 50)}%")
    w3.metric("سجل واتساب", len(db.get_whatsapp_log(500)))
    w4.metric("جاهز إيميل", len(sendable))

    st.subheader("🎯 Top 30 — متابعة بعد الإيميل")
    st.caption("شركات أُرسل لها CV + لديها جوال + لم تُتابَع واتساب خلال 7 أيام")

    if followup_top:
        fu_rows = []
        for i, c in enumerate(followup_top, 1):
            msg = whatsapp_outreach.compose_message(c, config)
            url = whatsapp_outreach.build_whatsapp_url(c.get("phone", ""), msg)
            fu_rows.append({
                "#": i,
                "الشركة": c["company_name"],
                "ملاءمة": f"{c.get('job_fit_score', 0)}%",
                "الجوال": c.get("phone", ""),
                "المدينة": c.get("city", ""),
                "رابط": url or "—",
            })
        st.dataframe(pd.DataFrame(fu_rows), use_container_width=True, hide_index=True)

        pick_fu = st.selectbox(
            "فتح واتساب",
            [f"#{r['#']} {r['الشركة']}" for r in fu_rows],
            key="wa_followup_pick",
        )
        if pick_fu:
            idx = int(pick_fu.split("#")[1].split(" ")[0]) - 1
            chosen_fu = followup_top[idx]
            msg_fu = whatsapp_outreach.compose_message(chosen_fu, config)
            url_fu = whatsapp_outreach.build_whatsapp_url(chosen_fu.get("phone", ""), msg_fu)
            if url_fu:
                st.link_button(
                    f"📲 واتساب — {chosen_fu['company_name'][:30]}",
                    url_fu,
                    use_container_width=True,
                    key="wa_followup_open",
                )
                if st.button("✅ سجّل متابعة", key="wa_followup_log"):
                    whatsapp_outreach.log_outreach(
                        chosen_fu["company_id"],
                        chosen_fu.get("phone", ""),
                        msg_fu,
                        "followup_sent",
                    )
                    st.success("تم التسجيل")
                    st.rerun()
    else:
        st.info("لا توجد شركات في Top 30 — أرسل إيميلات أولاً أو خفّض whatsapp_min_fit في الإعدادات")

    st.markdown("---")
    st.subheader("جميع الشركات برقم جوال")
    wa_companies = whatsapp_outreach.get_companies_with_phones(target_cities)

    if not wa_companies:
        st.info("لا توجد شركات بأرقام جوال — سيُضاف الرقم تلقائياً من Google/OSM")
    else:
        min_fit = st.slider("حد أدنى للملاءمة %", 0, 100, 40, key="wa_min_fit")
        filtered = [c for c in job_fit.rank_companies(wa_companies, config) if c.get("job_fit_score", 0) >= min_fit]

        st.dataframe(
            pd.DataFrame([{
                "الشركة": c["company_name"],
                "ملاءمة": f"{c.get('job_fit_score', 0)}%",
                "الجوال": c.get("phone", ""),
                "المدينة": c.get("city", ""),
                "الإيميل": c.get("primary_email", "—"),
            } for c in filtered[:100]]),
            use_container_width=True,
            hide_index=True,
        )

        pick = st.selectbox(
            "اختر شركة",
            [f"{c['company_name']} — {c.get('phone', '')}" for c in filtered[:50]],
            key="wa_pick",
        )
        if pick and filtered:
            idx = [f"{c['company_name']} — {c.get('phone', '')}" for c in filtered[:50]].index(pick)
            chosen = filtered[idx]
            msg = whatsapp_outreach.compose_message(chosen, config)
            st.text_area("الرسالة", msg, height=180, key="wa_msg_preview")
            wa_url = chosen.get("whatsapp_url") or whatsapp_outreach.build_whatsapp_url(
                chosen.get("phone", ""), msg
            )
            if wa_url:
                st.link_button("📲 فتح واتساب", wa_url, use_container_width=True, key="wa_open_link")
                if st.button("✅ تسجيل أنني أرسلت", key="wa_log_btn"):
                    whatsapp_outreach.log_outreach(
                        chosen["id"], chosen.get("phone", ""), msg, "sent_manual"
                    )
                    st.success("تم التسجيل")

    wa_log = db.get_whatsapp_log(50)
    if wa_log:
        with st.expander("سجل واتساب"):
            st.dataframe(pd.DataFrame([{
                "الشركة": r.get("company_name", ""),
                "الجوال": r.get("phone", ""),
                "الحالة": r.get("status", ""),
                "التاريخ": ui_theme.format_local_datetime(r.get("created_at")),
            } for r in wa_log]), use_container_width=True, hide_index=True)

# ── Tab: Log ─────────────────────────────────────────────────────
with tab_log:
    st.header("📋 سجل الإرسال التفصيلي")
    logs = db.get_outreach_log(limit=200)
    if logs:
        rows = [{
            "الشركة": l.get("company_name", ""),
            "الإيميل": l.get("email", ""),
            "التاريخ": ui_theme.format_local_datetime(l.get("sent_at")),
            "الحالة": "✅ تم الإرسال" if not l.get("error_message") and not l.get("dry_run") else (
                "🧪 تجريبي" if l.get("dry_run") else "❌ فشل"
            ),
            "خطأ": l.get("error_message", "") or "—",
            "Message-ID": l.get("provider_message_id", "") or "—",
        } for l in logs]
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    else:
        st.info("لا يوجد سجل بعد — من **⚡ مركز العمل** أرسل CV للشركات")

# ── Tab: CV ──────────────────────────────────────────────────────
with tab_cv:
    st.header("📄 السيرة الذاتية ATS")

    ats_info = send_email.get_cv_info()
    uploaded_info = send_email.get_uploaded_cv_info()

    st.markdown("#### 📤 السيرة المرفوعة (نسختك الأصلية)")
    if uploaded_info.get("exists"):
        up_mod = ui_theme.format_local_timestamp(uploaded_info["modified"])
        st.info(f"**{UPLOADED_CV_LABEL}** — {uploaded_info['size_kb']} KB — {up_mod}")
        up_audit = ats_audit.audit_cv(cv_path=Path(uploaded_info["path"]), config=config)
        st.progress(up_audit["score"] / 100, text="تقييم النسخة المرفوعة")
        st.caption(f"تقييم ATS للنسخة المرفوعة: **{up_audit['score']}/100** — {up_audit['rank']}")
        with open(uploaded_info["path"], "rb") as f:
            st.download_button(
                label="⬇️ تحميل النسخة المرفوعة",
                data=f.read(),
                file_name=UPLOADED_CV_LABEL,
                mime="application/pdf",
                key="cv_tab_download_uploaded",
            )
    else:
        st.warning("لم تُرفع نسخة بعد — ارفع PDF من ⚙️ الإعدادات")
        st.caption("النسخة المرفوعة تُحفظ منفصلة ولا تُستبدل بالنسخة المحسّنة ATS.")

    st.markdown("---")
    st.markdown("#### ⚡ السيرة المحسّنة ATS (تُرسل للشركات)")
    if ats_info.get("exists"):
        ats_mod = ui_theme.format_local_timestamp(ats_info["modified"])
        st.success(f"**{ATS_CV_LABEL}** — {ats_info['size_kb']} KB — {ats_mod}")
    else:
        st.error(f"{ATS_CV_LABEL} غير موجود — اضغط توليد ATS أدناه")

    ats_audit_result = ats_audit.audit_cv(config=config)
    st.markdown(f"### الدرجة: **{ats_audit_result['score']}/100** — {ats_audit_result['rank']}")
    st.progress(ats_audit_result["score"] / 100, text="تقييم نسخة ATS")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("كلمات مفتاحية", f"{ats_audit_result['keyword_hits']}/{ats_audit_result['keyword_total']}")
    c2.metric("نص مستخرج", f"{ats_audit_result['text_chars']:,} حرف")
    c3.metric("صور مدمجة", ats_audit_result["images"])
    c4.metric("الحجم", f"{ats_audit_result['size_kb']} KB")

    with st.expander("📋 معايير ATS الأساسية (نقاط القوة)", expanded=False):
        for item in cv_generate.ATS_PRINCIPLES:
            st.markdown(f"- {item}")

    if ats_audit_result["passed"]:
        with st.expander(f"✅ نقاط قوة ({len(ats_audit_result['passed'])})", expanded=ats_audit_result["score"] >= 75):
            for item in ats_audit_result["passed"]:
                st.markdown(f"- {item}")

    if ats_audit_result["issues"]:
        with st.expander(f"⚠️ تحسينات ({len(ats_audit_result['issues'])})", expanded=ats_audit_result["score"] < 75):
            for item in ats_audit_result["issues"]:
                st.markdown(f"- {item}")

    missing_kw = [k for k, hit in ats_audit_result["keywords"].items() if not hit]
    if missing_kw:
        st.caption(f"كلمات ناقصة: {', '.join(missing_kw)}")

    col_gen, col_dl = st.columns(2)
    with col_gen:
        if st.button("⚡ توليد CV محسّن ATS", type="primary", use_container_width=True, key="cv_tab_generate_ats"):
            try:
                cv_generate.generate_ats_pdf()
                st.session_state["cv_upload_msg"] = f"تم توليد {ATS_CV_LABEL} — يُرسل تلقائياً مع الإيميلات"
                st.rerun()
            except Exception as exc:
                st.error(f"فشل التوليد: {exc}")
    with col_dl:
        if ats_info.get("exists"):
            with open(ats_info["path"], "rb") as f:
                st.download_button(
                    label=f"⬇️ تحميل {ATS_CV_LABEL}",
                    data=f.read(),
                    file_name=ATS_CV_LABEL,
                    mime="application/pdf",
                    use_container_width=True,
                    key="cv_tab_download_ats",
                )

    st.caption(f"الإرسال للشركات يُرفق **{ATS_CV_LABEL}** و**{UPLOADED_CV_LABEL}** (إن وُجدت) مع كل إيميل.")

    st.markdown("---")
    with st.expander("برومبت ATS"):
        st.markdown(compose.get_cv_prompt(config))

# ── Tab: Settings ────────────────────────────────────────────────
with tab_settings:
    st.header("⚙️ الإعدادات")

    st.subheader("🧪 اختبار وصول HR")
    test_email = config.get("testing", {}).get("hr_preview_email", "nader.bmm@gmail.com")
    hr_email_input = st.text_input("بريد اختبار HR", value=test_email, key="hr_test_email")
    st.caption("يُرسل نفس الموضوع والنص والمرفقات كما تصل للشركات — بدون وسم TEST")

    if st.button("📧 إرسال نسخة إنتاجية لـ HR", type="primary", key="hr_preview_send"):
        if dry_run:
            st.warning("أوقف Dry-Run من الشريط الجانبي للإرسال الفعلي")
        else:
            with st.spinner("جاري الإرسال..."):
                result = send_email.send_production_preview(hr_email_input, config)
                if result.get("success"):
                    st.success(
                        f"✅ وُصلت إلى {result['to']} | الموضوع: {result.get('subject', '')} | "
                        f"مرفقات: {len(result.get('attachments', []))}"
                    )
                    for att in result.get("attachments", []):
                        st.write(f"📎 {att['name']} ({att['size_kb']} KB)")
                else:
                    st.error(result.get("error", "فشل الإرسال"))

    st.markdown("---")

    cv_info = send_email.get_cv_info()
    uploaded_info = send_email.get_uploaded_cv_info()

    # ── رفع السيرة الذاتية ──
    st.subheader("📄 رفع سيرتك الأصلية")

    if uploaded_info.get("exists"):
        mod = ui_theme.format_local_timestamp(uploaded_info["modified"])
        st.success(f"✅ {UPLOADED_CV_LABEL} — {uploaded_info['size_kb']} KB — {mod}")
        with open(uploaded_info["path"], "rb") as f:
            st.download_button(
                label="⬇️ تحميل النسخة المرفوعة",
                data=f.read(),
                file_name=UPLOADED_CV_LABEL,
                mime="application/pdf",
                key="settings_tab_download_uploaded",
            )
    else:
        st.warning("لم تُرفع نسخة بعد — ارفع ملف PDF ثم اضغط «حفظ CV»")
        st.caption(f"الرفع يحفظ **{UPLOADED_CV_LABEL}** — للإرسال يُستخدم **{ATS_CV_LABEL}** من تبويب CV.")

    if cv_info.get("exists"):
        ats_mod = ui_theme.format_local_timestamp(cv_info["modified"])
        st.info(f"📎 يُرسل للشركات: **{ATS_CV_LABEL}** — {cv_info['size_kb']} KB — {ats_mod}")

    uploaded = st.file_uploader(
        "اختر ملف PDF",
        type=["pdf"],
        key="cv_upload",
        help="اختر الملف ثم اضغط «حفظ CV» — سيُرفق تلقائياً مع كل إيميل",
    )

    if uploaded is not None:
        st.caption(f"الملف المختار: **{uploaded.name}** — {len(uploaded.getvalue()) // 1024} KB")

    col_save, col_test_cv = st.columns(2)

    with col_save:
        if st.button("💾 حفظ CV", type="primary", use_container_width=True, key="settings_save_cv"):
            if uploaded is None:
                st.error("اختر ملف PDF أولاً من زر Browse files")
            else:
                try:
                    data = uploaded.getvalue()
                    saved = send_email.save_cv_pdf(data)
                    st.session_state["cv_upload_msg"] = (
                        f"تم حفظ {UPLOADED_CV_LABEL} ({saved.stat().st_size // 1024} KB)"
                    )
                    st.rerun()
                except ValueError as exc:
                    st.error(str(exc))
                except Exception as exc:
                    st.error(f"فشل الحفظ: {exc}")

    with col_test_cv:
        if st.button("🔍 تحقق من المرفق", use_container_width=True, key="settings_check_cv"):
            attachments = send_email._resolve_attachments(config)
            if attachments:
                for att in attachments:
                    label = send_email.attachment_display_name(att, config)
                    st.success(
                        f"جاهز للإرسال: {label} ({att.stat().st_size // 1024} KB)"
                    )
            else:
                st.error(f"لا يوجد {ATS_CV_LABEL} للإرفاق")

    if st.session_state.get("cv_upload_msg"):
        st.success(st.session_state.pop("cv_upload_msg"))

    st.markdown("---")

    # ── الملف الشخصي ──
    st.subheader("👤 الملف الشخصي")
    col1, col2 = st.columns(2)
    with col1:
        p_name_ar = st.text_input("الاسم (عربي)", value=profile.get("full_name_ar", ""), placeholder="محمد باسل محمود يونس")
        p_title_ar = st.text_input("المسمى (عربي)", value=profile.get("title_ar", ""), placeholder="مساح عام")
        p_phone = st.text_input("الجوال", value=profile.get("phone", ""), placeholder="+9665XXXXXXXX")
        p_email = st.text_input("البريد المرسل", value=profile.get("sender_email", ""), placeholder="ss.guess@hotmail.com")
    with col2:
        p_name_en = st.text_input("الاسم (English)", value=profile.get("full_name", ""), placeholder="Mohammed Basil Mahmood Yunus")
        p_title_en = st.text_input("المسمى (English)", value=profile.get("title", ""), placeholder="General Land Surveyor")
        p_years = st.number_input("سنوات الخبرة", min_value=1, max_value=40, value=int(profile.get("years_experience", 12)))
        p_city = st.text_input("المدينة", value=profile.get("city", ""), placeholder="Jeddah")

    if st.button("💾 حفظ الملف الشخصي", type="primary", key="settings_save_profile"):
        config["profile"]["full_name_ar"] = p_name_ar
        config["profile"]["full_name"] = p_name_en
        config["profile"]["title_ar"] = p_title_ar
        config["profile"]["title"] = p_title_en
        config["profile"]["phone"] = p_phone
        config["profile"]["sender_email"] = p_email
        config["profile"]["years_experience"] = int(p_years)
        config["profile"]["city"] = p_city
        with open(BASE_DIR / "config.yaml", "w", encoding="utf-8") as f:
            yaml.dump(config, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
        st.success("تم الحفظ ✅")
        st.rerun()

    st.markdown("---")

    # ── اختبار الإرسال ──
    st.subheader("📧 إرسال تجريبي")
    st.info(
        "تأكد أن **SMTP_LOGIN** في `.env` هو بريد Brevo "
        "(مثل `xxx@smtp-brevo.com`) من: Settings → SMTP & API → Login"
    )
    test_to = st.text_input("إيميل الاختبار", value="nader.bmm@gmail.com", placeholder="example@gmail.com")
    st.caption("يُرسل رسالة HR تجريبية + مرفقات CV (ATS + المرفوعة إن وُجدت) — إرسال حقيقي")

    if st.button("🚀 إرسال إيميل تجريبي", type="primary", key="settings_send_test_email"):
        attachments = send_email._resolve_attachments(config)
        if not attachments:
            st.error(f"لا يوجد CV — ولّد {ATS_CV_LABEL} من تبويب CV أو ارفع {UPLOADED_CV_LABEL} من الإعدادات")
        elif not test_to.strip():
            st.error("أدخل إيميل الاختبار")
        else:
            with st.spinner("جاري الإرسال..."):
                result = send_email.send_test_email(test_to.strip(), config)
                if result.get("success"):
                    att_lines = "\n".join(
                        f"• {a['name']} ({a['size_kb']} KB)"
                        for a in result.get("attachments", [])
                    )
                    st.success(
                        f"✅ تم الإرسال إلى {result['to']}\n\n"
                        f"Message ID: {result.get('message_id')}\n"
                        f"المرفقات:\n{att_lines}"
                    )
                else:
                    st.error(f"❌ فشل: {result.get('error')}")

    st.markdown("---")

    # ── فحص النظام ──
    st.subheader("🔌 فحص الاتصال")
    for chk in check_domain_setup():
        icon = "✅" if chk["status"] == "ok" else "⚠️" if chk["status"] == "warn" else "❌"
        st.write(f"{icon} {chk['item']}: {chk['message']}")

    conn = send_email.test_connection(config)
    if conn["status"] == "ok":
        st.success(conn["message"])
    elif conn["status"] == "warn":
        st.warning(conn["message"])
    else:
        st.error(conn["message"])

    st.markdown("---")
    st.caption(f"حد الإرسال: {config['sending']['max_per_day']}/يوم | المصدر: {config.get('discovery_provider', 'csv')}")
