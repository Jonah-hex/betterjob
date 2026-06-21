# نشر BetterJob على Oracle Cloud (تشغيل 24/7)

دليل نشر **BetterJob** و **BetterJob Pro** على **Oracle Cloud Infrastructure (OCI)** — Always Free VM.

---

## ماذا ستحصل؟

| الرابط | التطبيق |
|--------|---------|
| `http://IP_SERVER/` | BetterJob — اكتشاف + إعداد |
| `http://IP_SERVER/pro/` | BetterJob Pro — استرategie التقديم |

- تشغيل مستمر عبر Docker (`restart: unless-stopped`)
- قاعدة البيانات SQLite محفوظة في volume
- حماية بكلمة مرور (nginx basic auth)
- لا حاجة لفتح منافذ 8501/8502 للعامة — فقط **80**

---

## 1) إنشاء VM على Oracle Cloud

1. ادخل [Oracle Cloud Console](https://cloud.oracle.com/)
2. **Compute → Instances → Create instance**
3. **Name:** `betterjob`
4. **Image:** Ubuntu 22.04 أو 24.04
5. **Shape:** Ampere A1 **Always Free** (4 OCPU / 24 GB) — أو AMD Micro إن Ampere غير متاح
6. **Networking:** Public IP مُفعّل
7. **SSH keys:** أضف مفتاحك العام (أو أنشئ زوجاً جديداً)
8. Create

### فتح المنفذ 80

1. **Networking → Virtual Cloud Networks** → شبكة الـ VM
2. **Security Lists → Default Security List → Add Ingress Rules**
3. **Source CIDR:** `0.0.0.0/0` · **IP Protocol:** TCP · **Port:** `80`
4. (اختياري) Port `22` للـ SSH إن لم يكن مفتوحاً

---

## 2) الاتصال بالسيرفر

```bash
ssh ubuntu@YOUR_PUBLIC_IP
# أو opc@... حسب صورة Oracle
```

---

## 3) التثبيت التلقائي (من GitHub)

```bash
curl -fsSL https://raw.githubusercontent.com/Jonah-hex/betterjob/master/deploy/oracle/install.sh -o install.sh
chmod +x install.sh
./install.sh
```

أو يدوياً:

```bash
git clone https://github.com/Jonah-hex/betterjob.git
cd betterjob
chmod +x deploy/oracle/install.sh
./deploy/oracle/install.sh
```

السكربت يقوم بـ:
- تثبيت Docker
- استنساخ/تحديث المشروع
- إنشاء `.env` من القالب
- طلب **كلمة مرور** لوحة التحكم
- تشغيل `docker compose -f docker-compose.prod.yml up -d --build`

---

## 4) إعداد البريد (مهم)

```bash
nano ~/betterjob/.env
```

املأ Brevo/SMTP (راجع `.env.example` في المشروع).

ثم أعد التشغيل:

```bash
cd ~/betterjob
docker compose -f docker-compose.prod.yml restart
```

---

## 5) إعدادات الإنتاج في `config.yaml`

**قبل التشغيل 24/7** — عدّل على السيرفر:

```yaml
automation:
  auto_send: false      # لا إرسال تلقائي بدون مراقبة
  run_on_startup: false

sending:
  dry_run: false        # true للاختبار فقط
  max_per_day: 10       # أو 3 حسب استرategie Pro
```

```bash
nano ~/betterjob/config.yaml
docker compose -f docker-compose.prod.yml restart betterjob betterjob-pro
```

> **تحذير:** `auto_send: true` على سيرفر دائم قد يرسل مئات الإيميلات!

---

## 6) أوامر الصيانة

```bash
cd ~/betterjob

# السجلات
docker compose -f docker-compose.prod.yml logs -f

# إعادة تشغيل
docker compose -f docker-compose.prod.yml restart

# تحديث من GitHub
git pull
docker compose -f docker-compose.prod.yml up -d --build

# إيقاف
docker compose -f docker-compose.prod.yml down

# نسخ احتياطي لقاعدة البيانات
docker compose -f docker-compose.prod.yml exec betterjob \
  tar -czf - /app/data > betterjob-data-backup.tar.gz
```

---

## 7) (اختياري) دومين + HTTPS

1. اربط دوميناً بـ Public IP (A record)
2. ثبّت Certbot على الـ VM أو استخدم Oracle Load Balancer
3. عدّل `deploy/oracle/nginx/betterjob.conf` لـ SSL

---

## 8) التكلفة

- **Always Free Ampere VM:** 0$ شهرياً (ضمن حدود Oracle Free Tier)
- **Brevo SMTP:** مجاني حتى حد معين
- **Google Places API:** حسب الاستخدام

---

## استكشاف الأخطاء

| المشكلة | الحل |
|---------|------|
| الصفحة لا تفتح | تحقق من Security List (port 80) |
| 502 Bad Gateway | `docker compose logs betterjob` |
| Pro لا يعمل على `/pro/` | تأكد من `baseUrlPath = "pro"` في config_pro |
| نسيت كلمة المرور | احذف `.htpasswd` وأعد `install.sh` أو أنشئها بـ `openssl passwd -apr1` |

---

## البنية

```
Internet :80
    └── nginx (auth)
            ├── /     → betterjob:8501  (app.py)
            └── /pro/ → betterjob-pro:8502  (app_pro.py)
    volume: betterjob_data → /app/data/outreach.db
```

---

**المستودع:** https://github.com/Jonah-hex/betterjob
