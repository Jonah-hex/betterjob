"""BetterJob Pro — Smart Application Command Center."""

from __future__ import annotations

import importlib
import os
from pathlib import Path

import pandas as pd
import streamlit as st
import yaml
from dotenv import load_dotenv

import compose
import database as db
import outreach_quality
import send_email
import ui_theme
import whatsapp_outreach

import application_strategy
import strategy_store

db = importlib.reload(db)
compose = importlib.reload(compose)
application_strategy = importlib.reload(application_strategy)
strategy_store = importlib.reload(strategy_store)
send_email = importlib.reload(send_email)

BASE_DIR = Path(__file__).parent
load_dotenv(BASE_DIR / ".env", override=True)

st.set_page_config(
    page_title="BetterJob Pro — مركز التقديم الذكي",
    page_icon="🎯",
    layout="wide",
    initial_sidebar_state="expanded",
)
ui_theme.inject()


@st.cache_resource
def init():
    db.init_db()
    return True


def load_config() -> dict:
    with open(BASE_DIR / "config.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


init()
config = load_config()
profile = config.get("profile", {})
strat_cfg = config.get("application_strategy", {})

st.sidebar.title("🎯 BetterJob Pro")
st.sidebar.caption("مركز التقديم الذكي — جودة قبل الكمية")
st.sidebar.markdown(f"**{profile.get('full_name_ar', '')}**")
st.sidebar.markdown("---")

dry_run = st.sidebar.toggle(
    "🧪 Dry Run (بدون إرسال فعلي)",
    value=config.get("sending", {}).get("dry_run", False),
    key="pro_dry_run",
)
if dry_run != config.get("sending", {}).get("dry_run"):
    config.setdefault("sending", {})["dry_run"] = dry_run

strategy_on = st.sidebar.toggle(
    "استراتيجية ذكية",
    value=strat_cfg.get("enabled", True),
    key="pro_strategy_on",
)
config.setdefault("application_strategy", {})["enabled"] = strategy_on

st.sidebar.markdown(application_strategy.strategy_summary_text(config))
st.sidebar.markdown("---")
st.sidebar.info("**3/يوم × 5 أيام = 15/أسبوع** · جمعة استراحة · سبت بحث")
st.sidebar.markdown("---")
st.sidebar.markdown("**📐 BetterJob — الاكتشاف والإعداد**")
st.sidebar.caption("Pro للتقديم والمتابعة · BetterJob لجلب الشركات وإيميلات HR")
st.sidebar.link_button(
    "فتح BetterJob (8501)",
    "http://localhost:8501",
    use_container_width=True,
)

tab_dash, tab_today, tab_follow, tab_custom, tab_report = st.tabs(
    [
        "📊 لوحة الاستراتيجية",
        "🎯 تقديم اليوم",
        "🔄 المتابعة",
        "✏️ تخصيص سريع",
        "📈 التقارير",
    ]
)

quotas = application_strategy.get_quota_status(config)
stats = strategy_store.get_strategy_stats()
focus = quotas["focus"]
today_q = quotas["today"]
week_q = quotas["week"]

with tab_dash:
    ui_theme.hero("📊 استراتيجية التقديم الذكية", focus["label_ar"])

    c1, c2, c3, c4, c5 = st.columns(5)
    ui_theme.metric_card("اليوم", f"{today_q['total_sent']}/{today_q['total_target']}", c1)
    ui_theme.metric_card("الأسبوع", f"{week_q['applications_sent']}/{week_q['applications_target']}", c2)
    ui_theme.metric_card("متابعات مستحقة", stats["due_follow_ups"], c3)
    ui_theme.metric_card("ردود", stats["replied"], c4)
    ui_theme.metric_card("مقابلات", stats["interview"], c5)

    st.markdown("---")
    col_a, col_b = st.columns(2)

    with col_a:
        st.subheader("📅 خطة الأسبوع")
        plan = strat_cfg.get("weekly_plan", {})
        for key, day in plan.items():
            icon = "👉" if key == focus["day_key"] else "·"
            st.markdown(
                f"{icon} **{day.get('label_ar', key)}** — "
                f"{day.get('new_applications', 0)} تقديم · "
                f"{day.get('follow_ups', 0)} متابعة"
            )

    with col_b:
        st.subheader("⏱ وقت التخصيص حسب المسمى")
        cust = strat_cfg.get("customization_time", {})
        for key, block in cust.items():
            ranks = block.get("job_ranks", [])
            st.write(
                f"**{block.get('label_ar', key)}** — {block.get('minutes', 5)} د "
                f"(وظائف {ranks[0]}-{ranks[-1] if ranks else '?'})"
            )
            st.caption(block.get("instruction_ar", ""))

    st.markdown("---")
    st.subheader("📋 قواعد الاستراتيجية")
    st.markdown("""
| القاعدة | التفاصيل |
|---------|----------|
| **يومياً** | **3** تقديمات مخصصة فقط |
| **أسبوعياً** | **15** تقديم (3×5 أيام) — ردود أكثر بـ3× من 50 عشوائي |
| **أحد–خميس** | تقديم + متابعة |
| **الجمعة** | **استراحة** |
| **السبت** | **بحث + تعديل الرسائل** للأسبوع القادم |
| **وظائف 1–3** | 15 دقيقة + ذكر مشروع محدد |
| **وظائف 4–6** | 8 دقائق |
| **7–10** | 5 دقائق — تعديل سطر واحد |
    """)

    if focus.get("is_rest_day"):
        st.info("🕌 اليوم استراحة — لا تقديمات جديدة.")
    elif focus.get("is_research_day"):
        st.info("🔍 اليوم للبحث وتعديل الرسائل — راجع تبويب «تقديم اليوم».")
    elif focus.get("is_review_day"):
        st.warning("اليوم للمراجعة/التحضير — ركّز على المتابعات.")

with tab_today:
    ui_theme.hero("🎯 قائمة تقديم اليوم", focus["label_ar"])

    if focus.get("is_research_day"):
        st.subheader("🔍 السبت — بحث وتعديل رسائل الأسبوع القادم (15 شركة)")
        preview = application_strategy.build_research_preview(config, limit=15)
        if not preview:
            st.info("لا شركات للبحث — شغّل الاكتشاف من BetterJob.")
        else:
            total_mins = sum(p["customization"]["minutes"] for p in preview)
            st.caption(f"{len(preview)} شركة · ~{total_mins} دقيقة تحضير")
            for i, c in enumerate(preview, 1):
                cust = c["customization"]
                proj = c.get("project_draft", {})
                with st.expander(
                    f"{i}. {c['company_name'][:35]} — {cust['minutes']}د ({cust['label_ar']})",
                    expanded=(i <= 3),
                ):
                    st.caption(cust["instruction_ar"])
                    if cust.get("require_project_mention"):
                        st.text_area(
                            "سطر المشروع (عدّله بعد البحث)",
                            proj.get("ar", ""),
                            key=f"proj_{c.get('id', i)}",
                            height=70,
                        )
                    msg = compose.compose_for_company(
                        c,
                        config,
                        project_line_ar=proj.get("ar") if cust.get("require_project_mention") else None,
                    )
                    st.write(f"**Subject:** {msg['subject']}")
                    st.text(msg["body_ar"][:500] + "…")
        st.stop()

    if focus.get("is_rest_day"):
        st.info("🕌 الجمعة — استراحة. راجع «المتابعة» فقط إن لزم.")
        st.stop()

    queue = application_strategy.build_today_queue(config)
    remaining_smtp = max(0, config["sending"]["max_per_day"] - db.count_sent_today())
    left = max(0, today_q["total_target"] - today_q["total_sent"])

    st.caption(
        f"القائمة: {len(queue)} · SMTP متبقي: {remaining_smtp} · هدف متبقي: {left}"
    )

    if not queue:
        st.info("لا شركات في قائمة اليوم — شغّل الاكتشاف أو انتظر يوم عمل.")
    else:
        rows = [
            {
                "#": i,
                "الشركة": c.get("company_name", ""),
                "المسمى": c.get("job_title_en", "")[:28],
                "الوقت": f"{c.get('customization', {}).get('minutes', 5)}د",
                "الملاءمة": c.get("fit_score", 0),
                "الإيميل": c.get("email") or c.get("primary_email", ""),
            }
            for i, c in enumerate(queue, 1)
        ]
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

        max_batch = max(1, min(len(queue), left or 1, remaining_smtp or 1))
        batch_n = st.slider("عدد الإرسال الآن", 1, max_batch, min(3, max_batch), key="pro_batch_n")

        if st.button("🚀 إرسال دفعة اليوم (مُخصّصة)", type="primary", key="pro_send_batch"):
            progress = st.progress(0)
            status = st.empty()
            ok_count = 0
            for i, company in enumerate(queue[:batch_n], 1):
                cid = company.get("id") or company.get("company_id")
                status.write(f"إرسال {i}/{batch_n}: {company.get('company_name', '')[:40]}")
                progress.progress(i / batch_n)
                db.update_company_status(cid, "approved")
                result = send_email.send_to_company(cid, config, skip_approval=True)
                if result.get("success"):
                    ok_count += 1
            st.success(f"تم: {ok_count}/{batch_n}")

        with st.expander("معاينة + تخصيص أول شركة"):
            first = queue[0]
            cid = first.get("id") or first.get("company_id")
            full = db.get_company(cid) or first
            cust = application_strategy.get_customization_plan(full, config)
            st.caption(f"{cust['label_ar']} — {cust['minutes']} د · {cust['instruction_ar']}")
            proj = application_strategy.suggest_project_line(full, config)
            proj_ar = proj["ar"]
            if cust.get("require_project_mention"):
                proj_ar = st.text_area("سطر المشروع", proj["ar"], key="preview_proj_line")
            msg = compose.compose_for_company(
                full,
                config,
                project_line_ar=proj_ar if cust.get("require_project_mention") else None,
                project_line_en=proj.get("en") if cust.get("require_project_mention") else None,
            )
            st.write(f"**Subject:** {msg['subject']}")
            st.text_area("Arabic", msg["body_ar"], height=180, key="preview_ar_today")
            st.text_area("English", msg["body_en"], height=180, key="preview_en_today")

with tab_follow:
    ui_theme.hero("🔄 المتابعة بعد التقديم", "يوم 3 · 7 · 14")

    due = strategy_store.get_due_follow_ups(limit=40)
    st.metric("متابعات مستحقة الآن", len(due))

    if not due:
        st.info("لا متابعات مستحقة حالياً.")
    else:
        for fu in due:
            with st.expander(
                f"{'📧' if fu['channel'] == 'email' else '📲'} "
                f"{fu['company_name']} — مرحلة {fu['stage']}",
                expanded=False,
            ):
                content = application_strategy.compose_follow_up(fu, config)
                st.write(f"**Job:** {fu.get('job_title_en', '')}")
                if content["channel"] == "whatsapp":
                    url = whatsapp_outreach.build_whatsapp_url(fu.get("phone", ""), content["body_ar"])
                    if url:
                        st.link_button("📲 فتح واتساب", url)
                    else:
                        st.warning("لا رقم — استخدم البريد")
                else:
                    st.write(f"**Subject:** {content['subject']}")
                    st.text_area("Arabic", content["body_ar"], height=100, key=f"fu_ar_{fu['id']}")
                    if st.button("📧 إرسال متابعة", key=f"send_fu_{fu['id']}"):
                        to_email = fu.get("primary_email")
                        if to_email:
                            try:
                                send_email._dispatch_send(
                                    to_email,
                                    content["subject"],
                                    content["body_ar"],
                                    content["body_en"],
                                    config,
                                    send_email._resolve_attachments(config),
                                )
                                strategy_store.complete_follow_up(fu["id"])
                                st.success("تم")
                            except Exception as exc:
                                st.error(str(exc))

                c1, c2, c3 = st.columns(3)
                if c1.button("💬 رد", key=f"replied_{fu['id']}"):
                    strategy_store.update_application_status(fu["company_id"], "replied")
                    strategy_store.complete_follow_up(fu["id"])
                    st.rerun()
                if c2.button("📅 مقابلة", key=f"interview_{fu['id']}"):
                    strategy_store.update_application_status(fu["company_id"], "interview")
                    st.rerun()
                if c3.button("✓ تم", key=f"done_{fu['id']}"):
                    strategy_store.complete_follow_up(fu["id"])
                    st.rerun()

with tab_custom:
    ui_theme.hero("✏️ تخصيص سريع", "مسمى + Hook + Subject")

    cities = config.get("automation", {}).get("target_cities", [])
    raw = db.get_sendable_companies(cities)
    sendable, _ = outreach_quality.prioritize_sendable(raw, config)
    options = sendable or db.get_companies()

    if not options:
        st.warning("لا شركات جاهزة.")
    else:
        pick = st.selectbox(
            "اختر شركة",
            options,
            format_func=lambda c: f"{c['company_name']} — {c.get('city', '')}",
            key="pro_custom_co",
        )
        meta = application_strategy.classify_tier(pick, config)
        cust = application_strategy.get_customization_plan(pick, config)
        hook = application_strategy.get_hook(meta["hook_key"], config)
        proj = application_strategy.suggest_project_line(pick, config)
        proj_ar = proj["ar"]
        if cust.get("require_project_mention"):
            proj_ar = st.text_area("سطر المشروع (15 د)", proj["ar"], key="custom_proj")
        msg = compose.compose_for_company(
            pick,
            config,
            project_line_ar=proj_ar if cust.get("require_project_mention") else None,
        )

        st.info(f"{cust['label_ar']} — {cust['minutes']} د · {cust['instruction_ar']}")
        st.write(f"**Subject:** {msg['subject']}")
        st.text_area("Arabic", msg["body_ar"], height=200, key="custom_ar")

        if st.button("📤 إرسال", type="primary", key="pro_custom_send"):
            db.update_company_status(pick["id"], "approved")
            result = send_email.send_to_company(pick["id"], config, skip_approval=True)
            st.success("تم ✅") if result.get("success") else st.error(result.get("error"))

with tab_report:
    ui_theme.hero("📈 تقارير", "تقديم · متابعة · ردود")
    recent = strategy_store.list_recent_applications(limit=50)
    if recent:
        df = pd.DataFrame([
            {
                "التاريخ": r.get("applied_at", "")[:10],
                "الشركة": r.get("company_name", ""),
                "المسمى": r.get("job_title_en", "")[:28],
                "النوع": r.get("tier", ""),
                "الحالة": r.get("status", ""),
            }
            for r in recent
        ])
        st.dataframe(df, use_container_width=True, hide_index=True)
        st.bar_chart(df["النوع"].value_counts())
    else:
        st.info("لا تقديمات بعد.")

st.caption(
    "BetterJob Pro = التقديم والمتابعة · BetterJob (8501) = اكتشاف الشركات واستخراج الإيميلات"
)
