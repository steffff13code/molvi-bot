"""HTTP API + HTML admin panel для бота МОЛВИ.

Маршруты:
  GET  /health                   — healthcheck (открытый)
  GET  /admin                    — HTML-панель (вход / дашборд)
  POST /admin/login              — форма входа
  GET  /admin/logout             — выход
  GET  /admin/api/stats          — JSON статистика (session)
  GET  /admin/api/whitelist      — JSON whitelist (session)
  POST /admin/api/whitelist      — добавить (session)
  DELETE /admin/api/whitelist/{id} — удалить (session)
  GET  /api/stats                — JSON (X-Admin-Token, для curl)
  GET  /api/whitelist            — JSON (X-Admin-Token, для curl)
  POST /api/whitelist            — добавить (X-Admin-Token)
  DELETE /api/whitelist/{id}     — удалить (X-Admin-Token)
"""
from __future__ import annotations

import secrets
import time

import bcrypt
from aiohttp import web
from loguru import logger

from bot.config import settings
from bot.db.queries import get_stats, whitelist_add, whitelist_list, whitelist_remove

# ───────────────────────── Сессии (в памяти) ─────────────────────────
_SESSION_TTL = 8 * 3600  # 8 часов
_sessions: dict[str, float] = {}  # token → expires_at


def _cleanup_sessions() -> None:
    """Удаляет просроченные сессии (предотвращает утечку памяти)."""
    now = time.time()
    expired = [k for k, v in list(_sessions.items()) if v <= now]
    for k in expired:
        _sessions.pop(k, None)


def _new_session() -> str:
    _cleanup_sessions()
    token = secrets.token_urlsafe(32)
    _sessions[token] = time.time() + _SESSION_TTL
    return token


def _valid_session(request: web.Request) -> bool:
    sid = request.cookies.get("admin_sid", "")
    exp = _sessions.get(sid)
    return bool(exp and exp > time.time())


def _check_admin_password(pw: str) -> bool:
    """Проверяет пароль web-панели.

    Приоритет:
    1. ADMIN_PASSWORD_HASH (bcrypt) — предпочтительно
    2. ADMIN_PASSWORD (plaintext, legacy)
    3. ADMIN_API_TOKEN как запасной пароль
    """
    pw_bytes = pw.encode()
    if settings.admin_password_hash:
        try:
            return bcrypt.checkpw(pw_bytes, settings.admin_password_hash.encode())
        except Exception:
            return False
    expected = settings.admin_password or settings.admin_api_token
    if not expected:
        return False
    return secrets.compare_digest(pw_bytes, expected.encode())


def _check_token(request: web.Request) -> bool:
    t = settings.admin_api_token
    if not t:
        return False
    provided = request.headers.get("X-Admin-Token", "")
    return bool(provided and secrets.compare_digest(provided, t))


# ───────────────────────── Брутфорс-защита ───────────────────────────
_FAIL_MAX = 5
_FAIL_WINDOW = 900  # 15 минут

_fail_log: dict[str, tuple[int, float]] = {}  # ip → (count, first_fail_ts)


def _is_rate_limited(ip: str) -> bool:
    entry = _fail_log.get(ip)
    if not entry:
        return False
    count, first_ts = entry
    if time.time() - first_ts > _FAIL_WINDOW:
        _fail_log.pop(ip, None)
        return False
    return count >= _FAIL_MAX


def _record_fail(ip: str) -> None:
    now = time.time()
    entry = _fail_log.get(ip)
    if not entry or now - entry[1] > _FAIL_WINDOW:
        _fail_log[ip] = (1, now)
    else:
        _fail_log[ip] = (entry[0] + 1, entry[1])


def _record_success(ip: str) -> None:
    _fail_log.pop(ip, None)


# ───────────────────────── HTML ─────────────────────────────────────

_CSS = """
*{box-sizing:border-box;margin:0;padding:0}
body{background:#0b0e17;color:#e2e8f0;font-family:system-ui,sans-serif;font-size:15px}
a{color:#60a5fa;text-decoration:none}
.nav{background:#131926;border-bottom:1px solid #1e2d4a;padding:12px 24px;
     display:flex;align-items:center;justify-content:space-between}
.nav-brand{font-weight:800;font-size:18px}
.btn-out{background:#1e2d4a;border:none;color:#e2e8f0;padding:8px 16px;
         border-radius:8px;cursor:pointer;font-size:13px}
.btn-out:hover{background:#2563eb}
.wrap{max-width:1100px;margin:0 auto;padding:32px 24px}
h1{font-size:26px;font-weight:800;margin-bottom:24px}
h2{font-size:13px;font-weight:700;margin-bottom:14px;color:#64748b;
   text-transform:uppercase;letter-spacing:.06em}
.period{display:flex;gap:8px;margin-bottom:28px}
.period button{padding:8px 18px;border-radius:8px;border:1px solid #1e2d4a;
               background:#131926;color:#94a3b8;cursor:pointer;font-size:14px}
.period button.active,.period button:hover{background:#2563eb;border-color:#2563eb;color:#fff}
.kpi-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:14px;margin-bottom:36px}
.kpi{background:#131926;border:1px solid #1e2d4a;border-radius:12px;padding:18px 20px}
.kpi-val{font-size:30px;font-weight:900;color:#fff}
.kpi-lbl{font-size:11px;color:#64748b;margin-top:4px;text-transform:uppercase;letter-spacing:.05em}
.card{background:#131926;border:1px solid #1e2d4a;border-radius:12px;padding:22px;margin-bottom:24px}
table{width:100%;border-collapse:collapse}
th{text-align:left;font-size:11px;color:#64748b;text-transform:uppercase;
   letter-spacing:.05em;padding:8px 10px;border-bottom:1px solid #1e2d4a}
td{padding:10px 10px;border-bottom:1px solid #0f1621;font-size:14px}
tr:last-child td{border-bottom:none}
tr:hover td{background:#0f1621}
.badge{display:inline-block;padding:2px 8px;border-radius:999px;font-size:12px;font-weight:600}
.bb{background:rgba(37,99,235,.2);color:#60a5fa}
.form-row{display:flex;gap:10px;flex-wrap:wrap;align-items:center}
input[type=text],input[type=number]{padding:10px 14px;background:#0b0e17;border:1px solid #1e2d4a;
  border-radius:8px;color:#e2e8f0;font-size:14px;outline:none;flex:1;min-width:130px}
input:focus{border-color:#2563eb}
.btn{padding:10px 18px;border:none;border-radius:8px;font-size:14px;font-weight:600;cursor:pointer}
.btn-blue{background:#2563eb;color:#fff}
.btn-blue:hover{background:#1d4ed8}
.btn-red{background:transparent;border:1px solid #dc2626;color:#f87171;
         padding:5px 10px;border-radius:6px;cursor:pointer;font-size:12px}
.btn-red:hover{background:#dc2626;color:#fff}
.note{font-size:12px;color:#475569;margin-top:14px}
.msg-ok{color:#4ade80;font-size:14px;margin-top:10px}
.msg-err{color:#f87171;font-size:14px;margin-top:10px}
#msg{min-height:22px}
.sec{margin-bottom:36px}
"""

_LOGIN_HTML = (
    '<!DOCTYPE html><html lang="ru"><head>'
    '<meta charset="UTF-8"><meta name="robots" content="noindex,nofollow">'
    '<title>МОЛВИ — Вход</title>'
    '<style>'
    '*{box-sizing:border-box;margin:0;padding:0}'
    'body{background:#0b0e17;color:#e2e8f0;font-family:system-ui,sans-serif;'
    '     display:flex;align-items:center;justify-content:center;min-height:100vh}'
    '.card{background:#131926;border:1px solid #1e2d4a;border-radius:16px;padding:40px;width:380px}'
    'h1{font-size:22px;margin-bottom:6px}'
    '.sub{color:#64748b;font-size:14px;margin-bottom:24px}'
    'input{width:100%;padding:12px 16px;background:#0b0e17;border:1px solid #1e2d4a;'
    '      border-radius:10px;color:#e2e8f0;font-size:15px;margin-bottom:14px;outline:none}'
    'input:focus{border-color:#2563eb}'
    'button{width:100%;padding:13px;background:#2563eb;border:none;border-radius:10px;'
    '       color:#fff;font-size:15px;font-weight:600;cursor:pointer}'
    'button:hover{background:#1d4ed8}'
    '.err{color:#f87171;font-size:14px;margin-bottom:12px}'
    '</style></head><body>'
    '<div class="card">'
    '  <h1>\U0001f92b МОЛВИ Админка</h1>'
    '  <p class="sub">Введите пароль для входа</p>'
    '  <!--MOLVI_ERR-->'
    '  <form method="post" action="/admin/login">'
    '    <input type="password" name="password" placeholder="Пароль" autofocus>'
    '    <button type="submit">Войти</button>'
    '  </form>'
    '</div></body></html>'
)

_ADMIN_HTML = """\
<!DOCTYPE html><html lang="ru"><head>
<meta charset="UTF-8"><meta name="robots" content="noindex,nofollow">
<title>МОЛВИ — Админка</title>
<style>MOLVI_ADMIN_CSS</style>
</head><body>
<nav class="nav">
  <span class="nav-brand">🤫 МОЛВИ Админка</span>
  <button class="btn-out" onclick="location='/admin/logout'">Выйти</button>
</nav>
<div class="wrap">
  <h1>Дашборд</h1>

  <div class="period" id="periodBar">
    <button onclick="load(7)"  data-d="7">7 дней</button>
    <button onclick="load(30)" data-d="30" class="active">30 дней</button>
    <button onclick="load(90)" data-d="90">90 дней</button>
    <button onclick="load(365)" data-d="365">Всё время</button>
  </div>

  <div class="kpi-grid">
    <div class="kpi"><div class="kpi-val" id="k-users">—</div><div class="kpi-lbl">Всего пользователей</div></div>
    <div class="kpi"><div class="kpi-val" id="k-new">—</div><div class="kpi-lbl">Новых за период</div></div>
    <div class="kpi"><div class="kpi-val" id="k-dau">—</div><div class="kpi-lbl">DAU</div></div>
    <div class="kpi"><div class="kpi-val" id="k-wau">—</div><div class="kpi-lbl">WAU</div></div>
    <div class="kpi"><div class="kpi-val" id="k-min">—</div><div class="kpi-lbl">Минут расшифровано</div></div>
    <div class="kpi"><div class="kpi-val" id="k-avg">—</div><div class="kpi-lbl">Ср. длина (мин)</div></div>
    <div class="kpi"><div class="kpi-val" id="k-files">—</div><div class="kpi-lbl">Файлов принято</div></div>
    <div class="kpi"><div class="kpi-val" id="k-pay">—</div><div class="kpi-lbl">Упёрлись в лимит</div></div>
    <div class="kpi"><div class="kpi-val" id="k-err">—</div><div class="kpi-lbl">Ошибок</div></div>
    <div class="kpi"><div class="kpi-val" id="k-wl">—</div><div class="kpi-lbl">В whitelist</div></div>
  </div>

  <div class="sec">
    <h2>Шаблоны саммари</h2>
    <div class="card">
      <table>
        <thead><tr><th>Шаблон</th><th>Использований</th></tr></thead>
        <tbody id="tplBody"><tr><td colspan="2" style="color:#475569">Загрузка…</td></tr></tbody>
      </table>
    </div>
  </div>

  <div class="sec">
    <h2>Форматы экспорта</h2>
    <div class="card">
      <table>
        <thead><tr><th>Формат</th><th>Скачиваний</th></tr></thead>
        <tbody id="fmtBody"><tr><td colspan="2" style="color:#475569">Загрузка…</td></tr></tbody>
      </table>
    </div>
  </div>

  <div class="sec">
    <h2>Whitelist — безлимитный доступ</h2>
    <div class="card">
      <div class="form-row">
        <input type="number" id="wl-id" placeholder="Telegram ID (число)">
        <input type="text"   id="wl-un" placeholder="username (без @)">
        <input type="text"   id="wl-nt" placeholder="Заметка">
        <button class="btn btn-blue" onclick="wlAdd()">+ Добавить</button>
      </div>
      <div id="msg"></div>
      <table style="margin-top:20px">
        <thead><tr><th>#</th><th>TG ID</th><th>Username</th><th>Заметка</th><th>Добавлен</th><th></th></tr></thead>
        <tbody id="wlBody"><tr><td colspan="6" style="color:#475569">Загрузка…</td></tr></tbody>
      </table>
      <p class="note">⚠ Контент пользователей не хранится (Вариант А). Только метаданные.</p>
    </div>
  </div>
</div>

<script>
const TPL={plain:'Просто расшифровка',protocol:'Протокол встречи',call:'Звонок/переговоры',
  lecture:'Конспект лекции',legal:'Юр. консультация',hr:'Собеседование',
  interview:'Интервью',note:'Личная заметка',therapy:'Сессия с психологом'};

async function api(url,opts){
  const r=await fetch(url,opts);
  if(!r.ok){const t=await r.text();throw new Error(t);}
  return r.json();
}

function setMsg(html){document.getElementById('msg').innerHTML=html;}

async function load(days=30){
  document.querySelectorAll('#periodBar button').forEach(b=>
    b.classList.toggle('active',b.dataset.d==days));
  const s=await api('/admin/api/stats?days='+days);
  document.getElementById('k-users').textContent=s.users_total??'—';
  document.getElementById('k-new').textContent=s.users_new??'—';
  document.getElementById('k-dau').textContent=s.dau??'—';
  document.getElementById('k-wau').textContent=s.wau??'—';
  document.getElementById('k-min').textContent=s.minutes!=null?Math.round(s.minutes):'—';
  document.getElementById('k-avg').textContent=s.avg_minutes??'—';
  document.getElementById('k-files').textContent=s.files??'—';
  document.getElementById('k-pay').textContent=s.paywall_hits??'—';
  document.getElementById('k-err').textContent=s.errors??'—';
  document.getElementById('k-wl').textContent=s.whitelist_count??'—';

  const tpl=s.templates||{};
  const tRows=Object.entries(tpl).sort((a,b)=>b[1]-a[1]);
  document.getElementById('tplBody').innerHTML=tRows.length
    ?tRows.map(([k,v])=>`<tr><td>${TPL[k]||k}</td><td><span class="badge bb">${v}</span></td></tr>`).join('')
    :'<tr><td colspan="2" style="color:#475569">Нет данных за период</td></tr>';

  const fmt=s.formats||{};
  const fRows=Object.entries(fmt).sort((a,b)=>b[1]-a[1]);
  document.getElementById('fmtBody').innerHTML=fRows.length
    ?fRows.map(([k,v])=>`<tr><td>${k.toUpperCase()}</td><td><span class="badge bb">${v}</span></td></tr>`).join('')
    :'<tr><td colspan="2" style="color:#475569">Нет данных за период</td></tr>';
}

async function loadWl(){
  const d=await api('/admin/api/whitelist');
  const body=document.getElementById('wlBody');
  if(!d.items||!d.items.length){
    body.innerHTML='<tr><td colspan="6" style="color:#475569">Whitelist пуст</td></tr>';
    return;
  }
  body.innerHTML=d.items.map(it=>`<tr>
    <td>${it.id}</td>
    <td>${it.tg_id||'—'}</td>
    <td>${it.username?'@'+it.username:'—'}</td>
    <td>${it.note||'—'}</td>
    <td style="color:#475569;font-size:12px">${(it.added_at||'').slice(0,16)}</td>
    <td><button class="btn-red" onclick="wlRemove(${it.id})">✕ Убрать</button></td>
  </tr>`).join('');
}

async function wlAdd(){
  const tg=document.getElementById('wl-id').value.trim();
  const un=document.getElementById('wl-un').value.trim().replace('@','');
  const nt=document.getElementById('wl-nt').value.trim();
  if(!tg&&!un){setMsg('<span class="msg-err">Укажите TG ID или username</span>');return;}
  try{
    await api('/admin/api/whitelist',{
      method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({tg_id:tg||null,username:un||null,note:nt||null})
    });
    setMsg('<span class="msg-ok">✓ Добавлен</span>');
    document.getElementById('wl-id').value='';
    document.getElementById('wl-un').value='';
    document.getElementById('wl-nt').value='';
    loadWl();
  }catch(e){setMsg('<span class="msg-err">Ошибка (возможно, уже есть)</span>');}
}

async function wlRemove(id){
  if(!confirm('Удалить из whitelist?'))return;
  await fetch('/admin/api/whitelist/'+id,{method:'DELETE'});
  loadWl();
}

load(30);loadWl();
</script>
</body></html>"""


# ───────────────────────── Middleware для /api/* ──────────────────────────────

@web.middleware
async def _api_auth_mw(request: web.Request, handler):
    if request.path.startswith("/api/"):
        if not settings.admin_api_token:
            return web.json_response({"error": "API disabled (no ADMIN_API_TOKEN)"}, status=503)
        if not _check_token(request):
            return web.json_response({"error": "unauthorized"}, status=401)
    return await handler(request)


# ───────────────────────── Healthcheck ───────────────────────────────────────

async def _health(request: web.Request) -> web.Response:
    return web.json_response({"ok": True, "service": "molvi-bot"})


# ───────────────────────── HTML admin routes ──────────────────────────────────

async def _admin_get(request: web.Request) -> web.Response:
    if not _valid_session(request):
        return web.Response(content_type="text/html",
                            text=_LOGIN_HTML.replace("<!--MOLVI_ERR-->", ""))
    return web.Response(content_type="text/html",
                        text=_ADMIN_HTML.replace("MOLVI_ADMIN_CSS", _CSS))


async def _admin_login(request: web.Request) -> web.Response:
    ip = request.remote or "unknown"

    if _is_rate_limited(ip):
        logger.warning("Admin login rate-limited for ip={ip}", ip=ip)
        return web.Response(
            content_type="text/html", status=429,
            text=_LOGIN_HTML.replace("<!--MOLVI_ERR-->",
                '<p class="err">Слишком много попыток. Подождите 15 минут.</p>'),
        )

    data = await request.post()
    pw = str(data.get("password", ""))
    if not (settings.admin_password_hash or settings.admin_password or settings.admin_api_token):
        return web.Response(content_type="text/html",
                            text=_LOGIN_HTML.replace("<!--MOLVI_ERR-->",
                                '<p class="err">ADMIN_PASSWORD_HASH не задан</p>'))

    if _check_admin_password(pw):
        _record_success(ip)
        sid = _new_session()
        resp = web.HTTPFound("/admin")
        resp.set_cookie("admin_sid", sid, max_age=_SESSION_TTL,
                        httponly=True, samesite="Lax", secure=True)
        return resp

    _record_fail(ip)
    logger.warning("Admin login failed for ip={ip}", ip=ip)
    return web.Response(
        content_type="text/html",
        text=_LOGIN_HTML.replace("<!--MOLVI_ERR-->", '<p class="err">Неверный пароль</p>'),
    )


async def _admin_logout(request: web.Request) -> web.Response:
    sid = request.cookies.get("admin_sid", "")
    _sessions.pop(sid, None)
    resp = web.HTTPFound("/admin")
    resp.del_cookie("admin_sid")
    return resp


# ───────────────────────── Admin JSON API (session) ───────────────────────────

async def _admin_stats(request: web.Request) -> web.Response:
    if not _valid_session(request):
        return web.json_response({"error": "unauthorized"}, status=401)
    days = int(request.query.get("days", "30"))
    days = max(1, min(days, 365))
    return web.json_response(await get_stats(days))


async def _admin_wl_list(request: web.Request) -> web.Response:
    if not _valid_session(request):
        return web.json_response({"error": "unauthorized"}, status=401)
    return web.json_response({"items": await whitelist_list()})


async def _admin_wl_add(request: web.Request) -> web.Response:
    if not _valid_session(request):
        return web.json_response({"error": "unauthorized"}, status=401)
    try:
        body = await request.json()
    except Exception:
        body = {}
    tg_id = body.get("tg_id")
    username = body.get("username")
    note = body.get("note")
    try:
        tg_id = int(tg_id) if tg_id not in (None, "") else None
    except (TypeError, ValueError):
        tg_id = None
    ok = await whitelist_add(tg_id=tg_id, username=username, note=note)
    return web.json_response({"ok": ok}, status=200 if ok else 400)


async def _admin_wl_remove(request: web.Request) -> web.Response:
    if not _valid_session(request):
        return web.json_response({"error": "unauthorized"}, status=401)
    try:
        entry_id = int(request.match_info["id"])
    except (KeyError, ValueError):
        return web.json_response({"ok": False, "error": "bad id"}, status=400)
    ok = await whitelist_remove(entry_id)
    return web.json_response({"ok": ok}, status=200 if ok else 404)


# ───────────────────────── External API (X-Admin-Token) ───────────────────────

async def _api_stats(request: web.Request) -> web.Response:
    days = int(request.query.get("days", "30"))
    days = max(1, min(days, 365))
    return web.json_response(await get_stats(days))


async def _api_wl_list(request: web.Request) -> web.Response:
    return web.json_response({"items": await whitelist_list()})


async def _api_wl_add(request: web.Request) -> web.Response:
    try:
        body = await request.json()
    except Exception:
        body = {}
    tg_id = body.get("tg_id")
    username = body.get("username")
    note = body.get("note")
    try:
        tg_id = int(tg_id) if tg_id not in (None, "") else None
    except (TypeError, ValueError):
        tg_id = None
    ok = await whitelist_add(tg_id=tg_id, username=username, note=note)
    return web.json_response({"ok": ok}, status=200 if ok else 400)


async def _api_wl_remove(request: web.Request) -> web.Response:
    try:
        entry_id = int(request.match_info["id"])
    except (KeyError, ValueError):
        return web.json_response({"ok": False, "error": "bad id"}, status=400)
    ok = await whitelist_remove(entry_id)
    return web.json_response({"ok": ok}, status=200 if ok else 404)


# ───────────────────────── App ────────────────────────────────────────────────

@web.middleware
async def _security_headers_mw(request: web.Request, handler):
    resp = await handler(request)
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("X-Frame-Options", "DENY")
    resp.headers.setdefault("X-XSS-Protection", "1; mode=block")
    resp.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    return resp


def build_app() -> web.Application:
    app = web.Application(middlewares=[_security_headers_mw, _api_auth_mw])
    # Healthcheck
    app.router.add_get("/health", _health)
    # HTML admin panel
    app.router.add_get("/admin", _admin_get)
    app.router.add_post("/admin/login", _admin_login)
    app.router.add_get("/admin/logout", _admin_logout)
    # Admin JSON API (session-based, for JS in panel)
    app.router.add_get("/admin/api/stats", _admin_stats)
    app.router.add_get("/admin/api/whitelist", _admin_wl_list)
    app.router.add_post("/admin/api/whitelist", _admin_wl_add)
    app.router.add_delete("/admin/api/whitelist/{id}", _admin_wl_remove)
    # External API (X-Admin-Token)
    app.router.add_get("/api/stats", _api_stats)
    app.router.add_get("/api/whitelist", _api_wl_list)
    app.router.add_post("/api/whitelist", _api_wl_add)
    app.router.add_delete("/api/whitelist/{id}", _api_wl_remove)
    return app


async def start_api(port: int) -> None:
    app = build_app()
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host="0.0.0.0", port=port)
    await site.start()
    logger.info("API + admin panel listening on 0.0.0.0:{port}", port=port)
