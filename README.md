# BetterJob — أداة التوظيف للمساحين

أداة محلية بسيطة تساعد **مساح عام (General Land Surveyor)** في:

1. اكتشاف شركات المقاولات والهندسة والمساحة في **جدة، أبها، والمنطقة الغربية والجنوبية**
2. استخراج إيميلات التوظيف من المواقع الرسمية
3. توليد رسائل HR احترافية (عربي + إنجليزي) مخصصة لكل شركة
4. إرسال CV + رسالة رسمية **بعد موافقتك اليدوية**
5. تتبع الحالات عبر لوحة تحكم Streamlit

> **ملاحظة:** الأداة تكتب **رسالة HR فقط** — الـ CV ملف منفصل مُحسّن لـ ATS.

---

## المتطلبات

- Python 3.10+
- Google Cloud API Key (Places API New)
- بريد Hotmail/Outlook (SMTP) أو Gmail (OAuth)

---

## التثبيت

```bash
cd Desktop/betterjob
python -m venv .venv
.venv\Scripts\activate        # Windows
pip install -r requirements.txt
```

---

## الإعداد

### 1. ملف البيئة

```bash
copy .env.example .env
```

املأ القيم:

| المتغير | الوصف |
|---------|-------|
| `GOOGLE_PLACES_API_KEY` | مفتاح Google Places API |
| `SMTP_USER` | بريدك (مثلاً ss.guess@hotmail.com) |
| `SMTP_PASSWORD` | App Password من Microsoft |
| `EMAIL_PROVIDER` | `smtp` أو `gmail` |

### 2. Google Places API

1. أنشئ مشروعاً في [Google Cloud Console](https://console.cloud.google.com/)
2. فعّل **Places API (New)**
3. أنشئ API Key وقيّده بـ Places API فقط
4. ضع المفتاح في `.env`

### 3. إعداد البريد

**Hotmail/Outlook (موصى به لبريدك):**
1. اذهب إلى [account.microsoft.com/security](https://account.microsoft.com/security)
2. أنشئ **App Password**
3. ضعه في `SMTP_PASSWORD`

**Gmail (بديل):**
1. أنشئ OAuth credentials في Google Cloud
2. حمّل `credentials.json` في مجلد المشروع
3. عيّن `EMAIL_PROVIDER=gmail`
4. أول إرسال سيفتح نافذة OAuth ويحفظ `token.json`

### 4. السيرة الذاتية

- `assets/cv/cv.pdf` — **موجود** (نسخة من CV M.B.Y.pdf)
- `assets/cv/cv.docx` — **أنشئه** باستخدام برومبت ATS في تبويب «مساعد CV»

---

## التشغيل

```bash
streamlit run app.py
```

يفتح المتصفح على `http://localhost:8501`

---

## سير العمل

```
اكتشاف → استخراج إيميل → مراجعة → موافقة → إرسال → متابعة
```

| المرحلة | ماذا تفعل | أين |
|---------|-----------|-----|
| 1 — اكتشاف | بحث شركات عبر Places API | تبويب «اكتشاف» |
| 2 — استخراج | جلب إيميل من الموقع | تبويب «الشركات» |
| 3 — مراجعة | معاينة رسالة AR/EN | تبويب «مراجعة وإرسال» |
| 4 — إرسال | موافقة + إرسال (≤12/يوم) | تبويب «مراجعة وإرسال» |
| 5 — متابعة | Follow-up بعد 7 أيام | يدوياً عبر Dashboard |

---

## وضع Dry-Run

مفعّل افتراضياً — يسجل الإرسال في قاعدة البيانات **بدون إرسال فعلي**.

لتفعيل الإرسال الحقيقي:
1. أوقف Dry-Run من الشريط الجانبي
2. تأكد من إعداد SMTP/Gmail
3. وافق على الشركة ثم اضغط «إرسال»

---

## حدود الأمان

- حد إرسال: **12 رسالة/يوم**
- تأخير: **45 ثانية** بين كل إرسال
- لا إرسال لإيميلات مُخمّنة (`guessed`)
- موافقة يدوية مطلوبة (`require_manual_approve: true`)
- لا scraping لخرائط Google — Places API فقط
- لا أسرار في Git (`.env` و `token.json` في `.gitignore`)

---

## هيكل المشروع

```
betterjob/
├── app.py              # لوحة التحكم Streamlit
├── config.yaml         # بياناتك + مدن + فلاتر
├── database.py         # SQLite
├── discover.py         # Google Places API
├── extract_email.py    # استخراج إيميلات
├── compose.py          # رسائل HR
├── send_email.py       # SMTP / Gmail
├── templates/
│   ├── email_ar.txt
│   ├── email_en.txt
│   └── cv_prompt.md    # برومبت ATS
├── assets/cv/
│   ├── cv.pdf          # سيرتك الذاتية
│   └── cv.docx         # (أنشئه)
└── data/
    └── outreach.db     # قاعدة البيانات
```

---

## تحذير قانوني

هذه الأداة مخصصة لـ **طلبات التوظيف B2B** وليست أداة spam تسويقي.
- خصّص كل رسالة باسم الشركة
- لا ترسل أكثر من 12 رسالة يومياً
- Follow-up بعد 7 أيام فقط
- احترم خصوصية الشركات

---

## بياناتك المُضمّنة

| الحقل | القيمة |
|-------|--------|
| الاسم | محمد باسل محمود يونس |
| المسمى | مساح عام / General Land Surveyor |
| الخبرة | 12 سنة |
| البريد | ss.guess@hotmail.com |
| الجوال | +966544883336 |
| العضوية | الهيئة السعودية للمهندسين — مساح عام |

عدّل `config.yaml` إذا احتجت تحديث أي بيانات.

---

## المزامنة عبر GitHub (جهاز آخر)

المستودع: `https://github.com/Jonah-hex/betterjob`

### رفع من هذا الجهاز

```powershell
cd Desktop\betterjob
.\publish_to_github.ps1
```

يفتح صفحة إنشاء مستودع جديد على GitHub — أنشئه **بدون** README ثم ينتظر السكربت ويرفع الكود تلقائياً.

### استنساخ على جهازك الآخر

```bash
git clone https://github.com/Jonah-hex/betterjob.git
cd betterjob
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
```

ثم املأ `.env` (Brevo SMTP) وشغّل `streamlit run app.py`.

> **ملاحظة:** `.env` و `data/outreach.db` غير مرفوعة لأسباب أمنية. انسخ `.env` يدوياً أو أعد إعداد المفاتيح على الجهاز الجديد.
