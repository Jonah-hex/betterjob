# إعداد الدومين الاحترافي — BetterJob

دليل خطوة بخطوة لشراء دومين وربطه بـ Brevo حتى يصل CV لصندوق الوارد وليس Spam.

---

## الدومين المقترح

| الدومين | السعر التقريبي | ملاحظة |
|---------|----------------|--------|
| `mby-surveyor.com` | ~40 ريال/سنة | **موصى به** — واضح ومهني |
| `basil-surveyor.com` | ~40 ريال/سنة | بديل |
| `mbyunus-survey.com` | ~40 ريال/سنة | بديل |

**أين تشتري:**
- [Namecheap](https://www.namecheap.com) — الأسهل
- [Porkbun](https://porkbun.com) — رخيص
- [Cloudflare Registrar](https://www.cloudflare.com/products/registrar/) — بدون هامش ربح

---

## المرحلة 1 — شراء الدومين (10 دقائق)

1. ادخل [namecheap.com](https://www.namecheap.com)
2. ابحث عن: `mby-surveyor.com`
3. أضف للسلة وادفع (~$10)
4. **لا تشترِ hosting** — تحتاج الدومين فقط

---

## المرحلة 2 — ربط الدومين بـ Brevo (15 دقيقة)

### 2.1 أضف الدومين في Brevo

1. ادخل [app.brevo.com](https://app.brevo.com)
2. اذهب إلى:
   ```
   Settings → Senders, Domains & Dedicated IPs → Domains
   ```
3. اضغط **Add a domain**
4. أدخل: `mby-surveyor.com`
5. اختر مزود DNS:
   - إذا الدومين في **Namecheap** → اختر Namecheap
   - إذا غير متأكد → اختر **Other**

### 2.2 أضف سجلات DNS

Brevo يعرض لك 3 سجلات — انسخها وأضفها في Namecheap:

1. ادخل [Namecheap → Domain List → Manage → Advanced DNS](https://ap.www.namecheap.com/domains/list/)
2. أضف السجلات التي يعطيك إياها Brevo:

| النوع | Host | Value |
|-------|------|-------|
| **TXT** | `@` | (قيمة Brevo للمصادقة) |
| **TXT** | `mail._domainkey` | (قيمة DKIM من Brevo) |
| **TXT** | `_dmarc` | `v=DMARC1; p=none; rua=mailto:jobs@mby-surveyor.com` |
| **CNAME** | `brevo-code.xxx` | (إن طلب Brevo) |

3. انتظر **15 دقيقة إلى 48 ساعة** (غالباً 30 دقيقة)
4. في Brevo اضغط **Verify** — يجب أن يظهر ✅ أخضر

### 2.3 أنشئ المرسل الاحترافي

```
Settings → Senders → Add a sender

From name:  Mohammed Basil Mahmood Yunus
From email: jobs@mby-surveyor.com
```

بعد مصادقة الدومين → المرسل يُفعَّل **تلقائياً** بدون كود.

---

## المرحلة 3 — تحديث الأداة (5 دقائق)

### 3.1 عدّل `config.yaml`

```yaml
profile:
  sender_email: "jobs@mby-surveyor.com"

domain:
  name: "mby-surveyor.com"
  sender_email: "jobs@mby-surveyor.com"
```

### 3.2 عدّل `.env`

```env
EMAIL_PROVIDER=brevo_smtp
SMTP_HOST=smtp-relay.brevo.com
SMTP_PORT=587
SMTP_LOGIN=7123456@smtp-brevo.com     ← من Brevo SMTP & API
SMTP_PASSWORD=xsmtpsib-...              ← مفتاح SMTP
```

**SMTP Login** من:
```
Brevo → Settings → SMTP & API → SMTP tab → Login
```

### 3.3 اختبر الإرسال

```powershell
cd "C:\Users\My Pc\Desktop\betterjob"
.venv\Scripts\activate
python auto_run.py --send-only
```

أرسل أولاً لبريدك الشخصي `ss.guess@hotmail.com` للتأكد أنه يصل **Inbox** وليس Spam.

---

## المرحلة 4 — تحقق من التسليم

| الاختبار | النتيجة المتوقعة |
|----------|------------------|
| أرسل لنفسك | Inbox ✅ |
| في Brevo → Transactional | Delivered ✅ |
| DKIM في Brevo Senders | ✅ أخضر |
| DMARC في Brevo Senders | ✅ أخضر |

---

## مقارنة قبل وبعد

| | Hotmail مجاني | دومين + Brevo |
|--|---------------|---------------|
| يصل Inbox | ❌ غالباً Spam | ✅ غالباً Inbox |
| يبدو احترافي لـ HR | ❌ | ✅ |
| ATS-friendly | ❌ | ✅ |
| تكلفة | مجاني | ~40 ريال/سنة |

---

## بعد الإعداد — شغّل الأداة

```powershell
python auto_run.py
```

الشركات سترى:
```
From: Mohammed Basil Mahmood Yunus <jobs@mby-surveyor.com>
Subject: Application — General Land Surveyor | Total Station
Attachment: cv.pdf
```

---

## مساعدة

بعد شراء الدومين، أرسل لي:
1. اسم الدومين الذي اشتريته
2. لقطة من صفحة DNS في Brevo (السجلات المطلوبة)

وأساعدك في ضبط `config.yaml` و `.env` بدقة.
