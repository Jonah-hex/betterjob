# مزامنة العمل بين الجهازين + سيرفر Oracle

المستودع: **https://github.com/Jonah-hex/betterjob**

| الجهاز | الدور |
|--------|--------|
| جهاز الدوام | تطوير + رفع التغييرات |
| جهاز البيت | جلب التحديثات + مفتاح SSH + Oracle |
| سيرفر Oracle | تشغيل 24/7 على `http://207.127.102.118/` |

> **لا يُرفع على GitHub:** `.env` · `data/outreach.db` · مفاتيح SSH  
> انسخ `.env` يدوياً بين الأجهزة (واتساب/إيميل لنفسك — لا ترفعه للمستودع).

---

## 1) من جهاز الدوام — حفظ ورفع

```powershell
cd Desktop\betterjob
git status
git add .
git commit -m "وصف مختصر للتغيير"
git push origin master
```

أو:

```powershell
.\publish_to_github.ps1
```

---

## 2) على جهاز البيت — جلب آخر نسخة

```powershell
cd Desktop\betterjob
git pull origin master
.\.venv\Scripts\pip install -r requirements.txt
```

تأكد من وجود `.env` (انسخه من الدوام إن لزم):

```powershell
notepad .env
```

تشغيل محلي:

```powershell
.\.venv\Scripts\streamlit run app.py
```

أو النسخة Pro:

```powershell
.\run_pro.bat
```

---

## 3) على سيرفر Oracle — تحديث بعد كل رفع

اتصل بالسيرفر (من جهاز البيت حيث مفتاح SSH):

```bash
ssh -i "path/to/your-key.pem" ubuntu@207.127.102.118
```

ثم نفّذ **أحد** الخيارين:

### أ) السكربت الجاهز

```bash
cd ~/betterjob
chmod +x deploy/oracle/update.sh
./deploy/oracle/update.sh
```

### ب) الأوامر يدوياً

```bash
cd ~/betterjob
git pull
docker compose -f docker-compose.prod.yml restart
```

بعد التحديث:
- BetterJob: http://207.127.102.118/
- BetterJob Pro: http://207.127.102.118/pro/

---

## 4) ترتيب العمل اليومي (مُوصى به)

```
جهاز الدوام          GitHub              جهاز البيت / Oracle
     │                  │                        │
     ├─ تعديل كود ─────►│                        │
     ├─ git push ──────►│                        │
     │                  ├──── git pull ◄─────────┤ (بيت)
     │                  │                        │
     │                  └──── git pull + docker ─► (Oracle)
```

1. اعمل على **الدوام** → `git push`
2. في **البيت** → `git pull` للعمل المحلي أو إدارة السيرفر
3. على **Oracle** → `./deploy/oracle/update.sh` بعد كل push مهم

---

## 5) استكشاف سريع

| المشكلة | الحل |
|---------|------|
| `git pull` يطلب دمج | `git stash` ثم `git pull` ثم `git stash pop` |
| السيرفر لا يظهر التحديث | تأكد من `git pull` داخل `~/betterjob` ثم `docker compose ... restart` |
| الإيميل لا يُرسل على Oracle | عدّل `~/betterjob/.env` على السيرفر (ليس في Git) |
| نسيت كلمة مرور اللوحة | راجع `deploy/oracle/DEPLOY_ORACLE.md` → إعادة `.htpasswd` |

---

## 6) نسخ احتياطي لقاعدة البيانات (Oracle)

```bash
cd ~/betterjob
docker compose -f docker-compose.prod.yml exec betterjob \
  tar -czf - /app/data > betterjob-data-backup.tar.gz
```

انسخ الملف لجهازك عبر `scp` إن احتجت.
