"""BetterJob — Survey Job Outreach Dashboard (Streamlit)."""

from __future__ import annotations

import os
from pathlib import Path

import pandas as pd
import streamlit as st
import yaml
from dotenv import load_dotenv

from datetime import datetime

import importlib

import compose
import database as db
import extract_email
import import_csv
import ats_audit
import cv_generate

import discover_multi
import discover_directory
import discover_domains
import send_email

db = importlib.reload(db)

import auto_run
import delivery_tracking

send_email = importlib.reload(send_email)
auto_run = importlib.reload(auto_run)
delivery_tracking = importlib.reload(delivery_tracking)
discover_multi = importlib.reload(discover_multi)
discover_directory = importlib.reload(discover_directory)
discover_domains = importlib.reload(discover_domains)

check_prerequisites = auto_run.check_prerequisites
run_discovery = auto_run.run_discovery
run_extraction = auto_run.run_extraction
run_sending = auto_run.run_sending
run_apply_new = auto_run.run_apply_new
run_discover_and_apply = auto_run.run_discover_and_apply
run_prepare_sendable = auto_run.run_prepare_sendable
from check_domain import check_domain_setup

BASE_DIR = Path(__file__).parent
load_dotenv(BASE_DIR / ".env", override=True)

st.set_page_config(
    page_title="BetterJob — مساح عام",
    page_icon="📐",
    layout="wide",
    initial_sidebar_state="expanded",
)

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

if st.sidebar.button("🔌 اختبار البريد", use_container_width=True):
    result = send_email.test_connection(config)
    if result["status"] == "ok":
        st.sidebar.success(result["message"])
    else:
        st.sidebar.error(result["message"])

st.sidebar.markdown("---")
st.sidebar.info(f"جدة + أبها | {config['sending']['max_per_day']} إيميل/يوم | اكتشاف متعدد المصادر")

# ── Tabs ─────────────────────────────────────────────────────────
tab_home, tab_auto, tab_companies, tab_delivery, tab_send, tab_log, tab_cv, tab_settings = st.tabs(
    [
        "🏠 الرئيسية",
        "🚀 تشغيل آلي",
        "🏢 الشركات",
        "📬 تتبع التسليم",
        "✉️ إرسال",
        "📋 السجل",
        "📄 CV",
        "⚙️ إعدادات",
    ]
)

stats = db.get_stats()
sendable = db.get_sendable_companies(config.get("automation", {}).get("target_cities"))

# ── Tab: Home ────────────────────────────────────────────────────
with tab_home:
    st.header(f"مرحباً {profile.get('full_name_ar', '')}")
    st.caption("أداة التوظيف التلقائية — مساح عام | Total Station")

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("إجمالي الشركات", stats.get("total", 0))
    c2.metric("إيميل جاهز", stats.get("email_found", 0))
    c3.metric("مُرسل فعلياً", stats.get("sent_confirmed", 0))
    c4.metric("جاهز للإرسال", len(sendable))
    c5.metric("مُرسل اليوم", f"{stats.get('sent_today', 0)} / {config['sending']['max_per_day']}")

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
        ```
        1. اكتشاف متعدد المصادر      CSV + Google + OSM + دليل
        2. استخراج إيميلات + دومين   تلقائي
        3. توليد رسالة HR             تلقائي
        4. إرسال CV (حتى 50/يوم)     Brevo
        ```
        """)
        cv_ok = send_email.get_cv_info().get("exists", False)
        st.write(f"{ATS_CV_LABEL}: {'✅ جاهز للإرسال' if cv_ok else '❌ غير موجود'}")

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

# ── Tab: Auto Run ────────────────────────────────────────────────
with tab_auto:
    st.header("🚀 تشغيل آلي")
    mode_label = {
        "csv": "ملف CSV",
        "overpass": "OpenStreetMap",
        "google": "Google Places",
        "multi": "متعدد المصادر",
    }
    st.caption(f"المصدر: {mode_label.get(discovery_mode, discovery_mode)} | الإرسال: Brevo + Hotmail")

    prereq_errors = check_prerequisites(config)
    if prereq_errors:
        st.error("أكمل المتطلبات أولاً:")
        for err in prereq_errors:
            st.write(f"- {err}")
    else:
        st.success("جميع المتطلبات جاهزة — اضغط تشغيل ✅")

    m1, m2, m3 = st.columns(3)
    m1.metric("شركات في القائمة", stats.get("total", 0))
    m2.metric("جاهز للإرسال", len(sendable))
    m3.metric("متبقي اليوم", max(0, remaining))

    st.markdown("---")

    btn1, btn2, btn3 = st.columns(3)

    with btn1:
        if st.button("▶️ تشغيل كامل", type="primary", use_container_width=True):
            if prereq_errors:
                st.error("أكمل المتطلبات أولاً")
            else:
                prog = st.progress(0, text="استيراد/اكتشاف...")
                try:
                    run_discovery(config)
                    prog.progress(33, text="استخراج إيميلات...")
                    run_extraction(config)
                    prog.progress(66, text="إرسال CV...")
                    result = run_sending(config)
                    prog.progress(100, text="اكتمل!")
                    st.success(f"✅ أُرسل: {result['sent']} | ❌ فشل: {result['failed']}")
                    if result.get("details"):
                        with st.expander("تفاصيل الإرسال"):
                            for d in result["details"]:
                                icon = "✅" if d.get("success") else "❌"
                                st.write(f"{icon} {d.get('company')} — {d.get('email', d.get('error', ''))}")
                    st.rerun()
                except Exception as exc:
                    st.error(str(exc))

    with btn2:
        if st.button("📧 استخراج إيميلات", use_container_width=True):
            with st.spinner("جاري الاستخراج..."):
                result = run_extraction(config)
                st.success(f"وُجد: {result['email_found']} | بدون: {result['no_email']}")

    with btn3:
        if st.button("📤 إرسال فقط", use_container_width=True):
            if prereq_errors:
                st.error("أكمل المتطلبات أولاً")
            else:
                with st.spinner("جاري الإرسال..."):
                    result = run_sending(config)
                    st.success(f"أُرسل: {result['sent']} | فشل: {result['failed']}")
                    st.rerun()

    if dry_run:
        st.warning("⚠️ Dry-Run مفعّل — لن يُرسل إيميلات حقيقية. أوقفه من الشريط الجانبي.")

# ── Tab: Companies ───────────────────────────────────────────────
with tab_companies:
    st.header("🏢 الشركات")

    sub_all, sub_sent, sub_discover = st.tabs([
        "📋 كل الشركات",
        "✅ تم الإرسال فعلياً",
        "🔎 اكتشاف متعدد المصادر",
    ])

    with sub_sent:
        st.subheader("الشركات التي وصلها CV فعلياً")
        sent_city = st.selectbox("المدينة", ["الكل", "Jeddah", "Abha"], key="sent_city_filter")
        sent_rows = db.get_sent_companies(
            city=None if sent_city == "الكل" else sent_city,
            limit=500,
        )
        if sent_rows:
            st.dataframe(
                pd.DataFrame([{
                    "الشركة": r["company_name"],
                    "الإيميل": r["email"],
                    "المدينة": r.get("city", ""),
                    "القطاع": r.get("sector", ""),
                    "المصدر": SOURCE_LABELS.get(r.get("discovery_source", ""), r.get("discovery_source", "—")),
                    "تاريخ الإرسال": r.get("sent_at", ""),
                    "الموقع": r.get("website", ""),
                } for r in sent_rows]),
                use_container_width=True,
                hide_index=True,
            )
            st.caption(f"إجمالي مُرسل فعلياً: {len(sent_rows)}")
        else:
            st.info("لم يُرسل لأي شركة بعد — سيظهر الجدول تلقائياً بعد الإرسال الناجح")

    with sub_discover:
        st.subheader("اكتشاف احترافي من مصادر متعددة")
        st.caption(
            "ابحث عن شركات جديدة → جهّز الإيميلات → قدّم CV → تنتقل تلقائياً إلى «تم الإرسال فعلياً»"
        )

        target_cities = config.get("automation", {}).get("target_cities", ["Jeddah", "Abha"])
        pending_new = db.get_sendable_companies(target_cities)
        remaining_today = max(0, config["sending"]["max_per_day"] - db.count_sent_today())

        pm1, pm2, pm3, pm4 = st.columns(4)
        pm1.metric("جاهز للتقديم", len(pending_new))
        pm2.metric("متبقي اليوم", remaining_today)
        pm3.metric("مُرسل فعلياً", stats.get("sent_confirmed", 0))
        pm4.metric("إجمالي الشركات", stats.get("total", 0))

        if pending_new:
            st.markdown("**الشركات الجديدة الجاهزة للتقديم:**")
            st.dataframe(
                pd.DataFrame([{
                    "الشركة": c["company_name"],
                    "المدينة": c.get("city", ""),
                    "الإيميل": c.get("email", ""),
                    "المصدر": SOURCE_LABELS.get(c.get("discovery_source", ""), c.get("discovery_source", "—")),
                    "الموقع": c.get("website", "") or "—",
                } for c in pending_new[:50]]),
                use_container_width=True,
                hide_index=True,
            )
            if len(pending_new) > 50:
                st.caption(f"يعرض 50 من {len(pending_new)} — الباقي يُرسل تلقائياً حسب الحد اليومي")
        else:
            st.info("لا توجد شركات جديدة جاهزة — اضغط «اكتشاف شامل» أو «اكتشاف + تقديم» للبحث عن شركات جديدة")

        st.markdown("---")
        src_stats = db.get_discovery_stats()
        if src_stats:
            cols = st.columns(min(len(src_stats), 5))
            for i, (src, cnt) in enumerate(src_stats.items()):
                cols[i % len(cols)].metric(
                    SOURCE_LABELS.get(src, src),
                    cnt,
                )

        d1, d2, d3, d4, d5 = st.columns(5)
        prereq_apply = check_prerequisites(config)

        if d1.button("🚀 اكتشاف شامل", use_container_width=True):
            with st.spinner("جاري الاكتشاف من جميع المصادر..."):
                summary = discover_multi.discover_all_sources(config)
                prep = run_prepare_sendable(config)
                st.success(
                    f"مصادر: {', '.join(summary.get('sources_run', []))} | "
                    f"جديد: {summary.get('total_new', 0)} | "
                    f"إيميلات: {prep['extract'].get('email_found', 0)} | "
                    f"جاهز للتقديم: {prep['pending_count']}"
                )
                st.rerun()

        if d2.button("📤 تقديم CV للجديد", type="primary", use_container_width=True):
            if prereq_apply:
                st.error("أكمل المتطلبات أولاً: " + " | ".join(prereq_apply))
            elif dry_run:
                st.warning("أوقف وضع Dry-Run من الشريط الجانبي للإرسال الفعلي")
            elif not pending_new:
                st.warning("لا توجد شركات جديدة جاهزة — نفّذ اكتشافاً أولاً")
            else:
                with st.spinner(f"جاري إرسال CV لـ {min(len(pending_new), remaining_today)} شركة..."):
                    result = run_apply_new(config)
                    st.success(
                        f"✅ أُرسل: {result['sent']} | ❌ فشل: {result['failed']} | "
                        f"متبقي اليوم: {result['remaining_today']}"
                    )
                    if result.get("details"):
                        with st.expander("تفاصيل الإرسال"):
                            for d in result["details"]:
                                icon = "✅" if d.get("success") else "❌"
                                st.write(f"{icon} {d.get('company')} — {d.get('email', d.get('error', ''))}")
                    st.rerun()

        if d3.button("⚡ اكتشاف + تقديم", use_container_width=True):
            if prereq_apply:
                st.error("أكمل المتطلبات أولاً: " + " | ".join(prereq_apply))
            elif dry_run:
                st.warning("أوقف وضع Dry-Run من الشريط الجانبي للإرسال الفعلي")
            else:
                with st.spinner("اكتشاف شركات جديدة ثم تقديم CV..."):
                    result = run_discover_and_apply(config)
                    st.success(
                        f"اكتشاف ✅ | أُرسل: {result['sent']} | فشل: {result['failed']} | "
                        f"جاهز متبقي: {result.get('pending_count', 0)}"
                    )
                    if result.get("details"):
                        with st.expander("تفاصيل الإرسال"):
                            for d in result["details"]:
                                icon = "✅" if d.get("success") else "❌"
                                st.write(f"{icon} {d.get('company')} — {d.get('email', d.get('error', ''))}")
                    st.rerun()

        if d4.button("📒 دليل ويب", use_container_width=True):
            with st.spinner("بحث في الدلائل..."):
                result = discover_directory.discover_target_cities(config)
                prep = run_prepare_sendable(config)
                st.success(f"{result} | جاهز للتقديم: {prep['pending_count']}")
                st.rerun()

        if d5.button("🔄 CSV", use_container_width=True):
            csv_path = BASE_DIR / "data" / "companies.csv"
            if csv_path.exists():
                result = import_csv.import_csv(csv_path)
                prep = run_prepare_sendable(config)
                st.success(
                    f"مستورد: {result['imported']} | بإيميل: {result['with_email']} | "
                    f"جاهز: {prep['pending_count']}"
                )
                st.rerun()
            else:
                st.error("ملف companies.csv غير موجود")

        if st.button("🌐 استخراج دومينات", use_container_width=False):
            with st.spinner("استنتاج إيميلات من المواقع..."):
                result = discover_domains.enrich_all_pending(config)
                prep = run_prepare_sendable(config)
                st.success(f"وُجد: {result.get('email_found', 0)} | جاهز: {prep['pending_count']}")
                st.rerun()

        if dry_run:
            st.warning("⚠️ Dry-Run مفعّل — التقديم لن يُرسل فعلياً حتى توقفه من الشريط الجانبي")

        with st.expander("تفاصيل المصادر"):
            for src, label in discover_multi.SOURCE_LABELS.items():
                st.write(f"**{label}** — {'مفعّل' if src in config.get('discovery', {}).get('sources', []) else 'معطّل'}")
            st.markdown("""
            **سير العمل المقترح:**
            1. **اكتشاف شامل** — يجلب شركات جديدة ويستخرج إيميلاتها
            2. **تقديم CV للجديد** — يرسل للشركات الجاهزة فقط (ضمن 50/يوم)
            3. **اكتشاف + تقديم** — دورة كاملة في زر واحد
            4. بعد الإرسال الناجح → تظهر في تبويب **تم الإرسال فعلياً**
            """)

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
            rows = [{
                "ID": c["id"],
                "الشركة": c["company_name"],
                "المدينة": c.get("city", ""),
                "القطاع": c.get("sector", ""),
                "المصدر": SOURCE_LABELS.get(c.get("discovery_source", ""), c.get("discovery_source", "—")),
                "الإيميل": c.get("primary_email", "—"),
                "الحالة": status_badge(c.get("status", "")),
                "الموقع": c.get("website", ""),
            } for c in companies]
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
            st.caption(f"عرض {len(companies)} شركة | جاهز للإرسال: {len(sendable)}")
        else:
            st.info("لا توجد شركات — استخدم تبويب «اكتشاف متعدد المصادر»")

# ── Tab: Delivery Tracking ───────────────────────────────────────
with tab_delivery:
    st.header("📬 تتبع تسليم CV")
    st.caption("مسارات واضحة: مُستلم | مُرسل | معلق | لم يُرسل | فشل | بدون إيميل")

    target_cities = config.get("automation", {}).get("target_cities", ["Jeddah", "Abha"])
    delivery_tracking.sync_pipeline(target_cities)
    pipeline = delivery_tracking.get_pipeline_summary(target_cities)

    dm1, dm2, dm3, dm4, dm5, dm6 = st.columns(6)
    dm1.metric("✅ مُستلم", pipeline["delivered"])
    dm2.metric("📤 مُرسل", pipeline["sent"])
    dm3.metric("⏳ معلق", pipeline["pending"])
    dm4.metric("📭 لم يُرسل", pipeline["not_sent"])
    dm5.metric("❌ فشل", pipeline["failed"])
    dm6.metric("🚫 بدون إيميل", pipeline["no_email"])

    st.markdown("---")
    tr_delivered, tr_sent, tr_pending, tr_not_sent, tr_failed, tr_no_email = st.tabs([
        "✅ مُستلم",
        "📤 مُرسل (بانتظار تأكيد)",
        "⏳ معلق",
        "📭 لم يُرسل",
        "❌ فشل",
        "🚫 بدون إيميل",
    ])

    def _company_rows(items: list) -> list:
        return [{
            "الشركة": c.get("company_name", ""),
            "الإيميل": c.get("email", c.get("primary_email", "—")),
            "المدينة": c.get("city", ""),
            "المصدر": SOURCE_LABELS.get(c.get("discovery_source", ""), c.get("discovery_source", "—")),
        } for c in items]

    with tr_delivered:
        items = pipeline["delivered_list"]
        if items:
            st.dataframe(pd.DataFrame([{
                "الشركة": r["company_name"],
                "الإيميل": r["email"],
                "المدينة": r.get("city", ""),
                "أُرسل": r.get("sent_at", ""),
                "استُلم": r.get("delivered_at", "—"),
                "CV": "✅" if r.get("cv_attached") else "—",
            } for r in items]), use_container_width=True, hide_index=True)
        else:
            st.info("لا توجد رسائل مؤكدة الاستلام — يمكنك تأكيد الاستلام من تبويب «مُرسل»")

    with tr_sent:
        items = pipeline["sent_list"]
        if items:
            st.dataframe(pd.DataFrame([{
                "ID": r["company_id"],
                "الشركة": r["company_name"],
                "الإيميل": r["email"],
                "المدينة": r.get("city", ""),
                "تاريخ الإرسال": r.get("sent_at", ""),
                "CV": "✅" if r.get("cv_attached", 1) else "—",
            } for r in items]), use_container_width=True, hide_index=True)
            st.caption("إذا وصل الرد أو تأكدت من الاستلام، اختر الشركة واضغط تأكيد")
            confirm_opts = {
                f"{r['company_name']} — {r['email']}": r["company_id"]
                for r in items
            }
            sel_del = st.selectbox("تأكيد استلام", ["—"] + list(confirm_opts.keys()), key="confirm_delivered")
            if sel_del != "—" and st.button("✅ تأكيد استلام CV", key="btn_confirm_delivered"):
                cid = confirm_opts[sel_del]
                row = next(r for r in items if r["company_id"] == cid)
                delivery_tracking.mark_company_delivered(cid, row.get("outreach_log_id"))
                st.success(f"تم تأكيد استلام CV لـ {sel_del.split(' — ')[0]}")
                st.rerun()
        else:
            st.info("لا توجد رسائل مُرسلة بانتظار التأكيد")

    with tr_pending:
        items = pipeline["pending_list"]
        if items:
            st.dataframe(pd.DataFrame([{
                "الشركة": r["company_name"],
                "الإيميل": r["email"],
                "الحالة": delivery_tracking.label(r.get("status", "")),
                "محاولات": r.get("attempts", 0),
                "آخر تحديث": r.get("updated_at", ""),
            } for r in items]), use_container_width=True, hide_index=True)
            if st.button("📤 إرسال المعلّق الآن", type="primary", key="send_pending_batch"):
                result = run_apply_new(config)
                st.success(f"أُرسل: {result['sent']} | فشل: {result['failed']}")
                st.rerun()
        else:
            st.info("لا توجد رسائل معلقة — شغّل اكتشافاً جديداً أو انتظر الحد اليومي")

    with tr_not_sent:
        items = pipeline["not_sent_list"]
        if items:
            st.dataframe(pd.DataFrame(_company_rows(items)), use_container_width=True, hide_index=True)
            if st.button("📤 تقديم CV للجميع", type="primary", key="send_not_sent_batch"):
                result = run_apply_new(config)
                st.success(f"أُرسل: {result['sent']} | فشل: {result['failed']}")
                st.rerun()
        else:
            st.success("جميع الشركات ذات الإيميل تم التعامل معها")

    with tr_failed:
        items = pipeline["failed_list"]
        if items:
            st.dataframe(pd.DataFrame([{
                "الشركة": r.get("company_name", ""),
                "الإيميل": r.get("email", ""),
                "التاريخ": r.get("sent_at", ""),
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
            st.success("لا توجد محاولات فاشلة")

    with tr_no_email:
        items = pipeline["no_email_list"]
        if items:
            st.dataframe(pd.DataFrame([{
                "الشركة": c["company_name"],
                "المدينة": c.get("city", ""),
                "الموقع": c.get("website", "—"),
                "الحالة": status_badge(c.get("status", "")),
            } for c in items]), use_container_width=True, hide_index=True)
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

            if st.button("📤 إرسال لهذه الشركة", type="primary"):
                db.update_company_status(company["id"], "approved")
                result = send_email.send_to_company(company["id"], config, skip_approval=True)
                if result.get("success"):
                    mode = "تجريبي" if result.get("dry_run") else "فعلي"
                    st.success(f"تم الإرسال ({mode})")
                else:
                    st.error(result.get("error", "فشل"))

# ── Tab: Log ─────────────────────────────────────────────────────
with tab_log:
    st.header("📋 سجل الإرسال التفصيلي")
    logs = db.get_outreach_log(limit=200)
    if logs:
        rows = [{
            "الشركة": l.get("company_name", ""),
            "الإيميل": l.get("email", ""),
            "التاريخ": l.get("sent_at", ""),
            "التسليم": delivery_tracking.label(l.get("delivery_status", db.DELIVERY_SENT)),
            "الحالة": "✅" if not l.get("error_message") else "❌",
            "Dry-Run": "نعم" if l.get("dry_run") else "لا",
            "خطأ": l.get("error_message", "") or "—",
            "Message-ID": l.get("provider_message_id", "") or "—",
        } for l in logs]
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    else:
        st.info("لا يوجد سجل بعد — شغّل التشغيل الآلي")

# ── Tab: CV ──────────────────────────────────────────────────────
with tab_cv:
    st.header("📄 السيرة الذاتية ATS")

    ats_info = send_email.get_cv_info()
    uploaded_info = send_email.get_uploaded_cv_info()

    st.markdown("#### 📤 السيرة المرفوعة (نسختك الأصلية)")
    if uploaded_info.get("exists"):
        up_mod = datetime.fromtimestamp(uploaded_info["modified"]).strftime("%Y-%m-%d %H:%M")
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
        ats_mod = datetime.fromtimestamp(ats_info["modified"]).strftime("%Y-%m-%d %H:%M")
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

    cv_info = send_email.get_cv_info()
    uploaded_info = send_email.get_uploaded_cv_info()

    # ── رفع السيرة الذاتية ──
    st.subheader("📄 رفع سيرتك الأصلية")

    if uploaded_info.get("exists"):
        mod = datetime.fromtimestamp(uploaded_info["modified"]).strftime("%Y-%m-%d %H:%M")
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
        ats_mod = datetime.fromtimestamp(cv_info["modified"]).strftime("%Y-%m-%d %H:%M")
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
        if st.button("💾 حفظ CV", type="primary", use_container_width=True):
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
        if st.button("🔍 تحقق من المرفق", use_container_width=True):
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

    if st.button("💾 حفظ الملف الشخصي", type="primary"):
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

    if st.button("🚀 إرسال إيميل تجريبي", type="primary"):
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
