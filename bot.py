import logging
import subprocess
import os
import sys
import ctypes
import webbrowser
import urllib.parse
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters
)

# ─────────────────────────────────────────────
# НАЛАШТУВАННЯ — заповни перед запуском!
# ─────────────────────────────────────────────
BOT_TOKEN   = "YOUR_BOT_TOKEN_HERE"   # токен від @BotFather
ALLOWED_ID  = 123456789               # твій Telegram user_id (перевір через @userinfobot)
# ─────────────────────────────────────────────

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(message)s",
    level=logging.INFO
)
log = logging.getLogger(__name__)

# ──────────── QUICK-MENU APPS ────────────
AMENU_APPS = [
    ("🎮 Steam",        r"C:\Program Files (x86)\Steam\steam.exe"),
    ("💬 Discord",      r""),
    ("⛏️ Minecraft",    r""),
    ("🧅 Browser",  r""),
    ("🗒️ Блокнот",      "notepad.exe"),
    ("📁 Провідник",    "explorer.exe"),
    ("🧮 Калькулятор",  "calc.exe"),
    ("🎵 Медіаплеєр",   "wmplayer.exe"),
    ("⚙️ Диспетчер",    "taskmgr.exe"),
    ("🖥️ CMD",          "cmd.exe"),
    ("🌐 Chrome",       "chrome.exe"),
    ("📝 PowerShell",   "powershell.exe"),
]

# ──────────── GUARD ────────────
def guard(update: Update) -> bool:
    uid = update.effective_user.id if update.effective_user else None
    if uid != ALLOWED_ID:
        log.warning("Заблоковано: user_id=%s", uid)
        return False
    return True

# ──────────── PowerShell helper (прихований, без вікна) ────────────
def _ps(cmd: str) -> str:
    CREATE_NO_WINDOW = 0x08000000
    result = subprocess.run(
        ["powershell", "-NonInteractive", "-WindowStyle", "Hidden", "-Command", cmd],
        capture_output=True, text=True,
        creationflags=CREATE_NO_WINDOW
    )
    return result.stdout.strip()

# ──────────── ЗВУК — pycaw (з правильною ініціалізацією COM) ────────────
try:
    from ctypes import cast, POINTER
    import comtypes
    from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume

    def _vol_iface():
        # COM треба ініціалізувати в КОЖНОМУ потоці, де він використовується
        comtypes.CoInitialize()
        devices = AudioUtilities.GetSpeakers()
        iface = devices.Activate(
            IAudioEndpointVolume._iid_, comtypes.CLSCTX_ALL, None
        )
        return cast(iface, POINTER(IAudioEndpointVolume))

    def get_volume_status() -> tuple[int, bool]:
        """Повертає (відсоток_гучності, чи_замучено)"""
        v = _vol_iface()
        pct = round(v.GetMasterVolumeLevelScalar() * 100)
        muted = bool(v.GetMute())
        return pct, muted

    def volume_up() -> tuple[int, bool]:
        v = _vol_iface()
        new_level = min(1.0, v.GetMasterVolumeLevelScalar() + 0.10)
        v.SetMasterVolumeLevelScalar(new_level, None)
        return round(new_level * 100), bool(v.GetMute())

    def volume_down() -> tuple[int, bool]:
        v = _vol_iface()
        new_level = max(0.0, v.GetMasterVolumeLevelScalar() - 0.10)
        v.SetMasterVolumeLevelScalar(new_level, None)
        return round(new_level * 100), bool(v.GetMute())

    def volume_mute() -> tuple[int, bool]:
        v = _vol_iface()
        new_mute = not v.GetMute()
        v.SetMute(new_mute, None)
        pct = round(v.GetMasterVolumeLevelScalar() * 100)
        return pct, new_mute

    def volume_zero() -> tuple[int, bool]:
        v = _vol_iface()
        v.SetMasterVolumeLevelScalar(0.0, None)
        return 0, bool(v.GetMute())

    # тестовий виклик при старті — якщо впаде, перейдемо у except нижче
    _test = _vol_iface()
    _test.GetMasterVolumeLevelScalar()

    log.info("pycaw: керування звуком активне ✅")

except Exception as e:
    log.warning(f"pycaw недоступний ({e}) — використовується WinAPI keybd_event")

    # ──────────── FALLBACK: WinAPI keybd_event (без COM, завжди працює) ────────────
    # Тут немає прямого доступу до точного % гучності системи, тому
    # ведемо приблизний внутрішній лічильник у самому боті.
    VK_VOLUME_UP   = 0xAF
    VK_VOLUME_DOWN = 0xAE
    VK_VOLUME_MUTE = 0xAD
    KEYEVENTF_EXTENDEDKEY = 0x0001
    KEYEVENTF_KEYUP       = 0x0002
    VK_SPACE = 0x20
    VK_LEFT = 0x25
    VK_RIGHT = 0x27
    VK_F = 0x46
    VK_K = 0x4B
    VK_J = 0x4A
    VK_L = 0x4C
    VK_N = 0x4E
    VK_P = 0x50

    def press_key(vk):
        KEYEVENTF_EXTENDEDKEY = 0x0001
        KEYEVENTF_KEYUP = 0x0002

        ctypes.windll.user32.keybd_event(vk, 0, KEYEVENTF_EXTENDEDKEY, 0)
        ctypes.windll.user32.keybd_event(vk, 0, KEYEVENTF_EXTENDEDKEY | KEYEVENTF_KEYUP, 0)

    _fallback_state = {"level": 50, "muted": False}  # початкове наближення

    def _media_key(vk: int, count: int = 1):
        for _ in range(count):
            ctypes.windll.user32.keybd_event(vk, 0, KEYEVENTF_EXTENDEDKEY, 0)
            ctypes.windll.user32.keybd_event(vk, 0, KEYEVENTF_EXTENDEDKEY | KEYEVENTF_KEYUP, 0)

    def get_volume_status() -> tuple[int, bool]:
        return _fallback_state["level"], _fallback_state["muted"]

    def volume_up() -> tuple[int, bool]:
        _media_key(VK_VOLUME_UP, 5)
        _fallback_state["level"] = min(100, _fallback_state["level"] + 10)
        _fallback_state["muted"] = False
        return _fallback_state["level"], _fallback_state["muted"]

    def volume_down() -> tuple[int, bool]:
        _media_key(VK_VOLUME_DOWN, 5)
        _fallback_state["level"] = max(0, _fallback_state["level"] - 10)
        return _fallback_state["level"], _fallback_state["muted"]

    def volume_mute() -> tuple[int, bool]:
        _media_key(VK_VOLUME_MUTE, 1)
        _fallback_state["muted"] = not _fallback_state["muted"]
        return _fallback_state["level"], _fallback_state["muted"]

    def volume_zero() -> tuple[int, bool]:
        _media_key(VK_VOLUME_DOWN, 50)
        _fallback_state["level"] = 0
        return 0, _fallback_state["muted"]

    def search_web(query: str):
        q = urllib.parse.quote(query)
        url = f"https://www.google.com/search?q={q}"
        webbrowser.open(url)

# ──────────── ЯСКРАВІСТЬ (через WMI напряму, без PowerShell) ────────────
try:
    import wmi as _wmi_module
    _wmi_obj = _wmi_module.WMI(namespace="root/WMI")

    def _get_brightness() -> int:
        try:
            return int(_wmi_obj.WmiMonitorBrightness()[0].CurrentBrightness)
        except Exception:
            return 50

    def _set_brightness(level: int) -> int:
        level = max(0, min(100, level))
        try:
            _wmi_obj.WmiMonitorBrightnessMethods()[0].WmiSetBrightness(level, 0)
        except Exception:
            pass
        return level

    log.info("WMI: яскравість активна ✅")

except Exception as _wmi_err:
    log.warning(f"WMI недоступний ({_wmi_err}) — fallback через PowerShell")

    def _get_brightness() -> int:
        out = _ps("(Get-WmiObject -Namespace root/WMI -Class WmiMonitorBrightness).CurrentBrightness")
        try:
            return int(out)
        except Exception:
            return 50

    def _set_brightness(level: int) -> int:
        level = max(0, min(100, level))
        _ps(f"(Get-WmiObject -Namespace root/WMI -Class WmiMonitorBrightnessMethods).WmiSetBrightness(1,{level})")
        return level

def brightness_up() -> int:
    return _set_brightness(_get_brightness() + 10)

def brightness_down() -> int:
    return _set_brightness(_get_brightness() - 10)


# ──────────── СИСТЕМНІ ────────────
def minimize_all():
    _ps("(New-Object -com Shell.Application).MinimizeAll()")

def lock_pc():
    ctypes.windll.user32.LockWorkStation()

def shutdown_pc():
    subprocess.run(["shutdown", "/s", "/t", "10"])

def press_space():
    KEYEVENTF_EXTENDEDKEY = 0x0001
    KEYEVENTF_KEYUP = 0x0002

    ctypes.windll.user32.keybd_event(VK_SPACE, 0, KEYEVENTF_EXTENDEDKEY, 0)
    ctypes.windll.user32.keybd_event(VK_SPACE, 0, KEYEVENTF_EXTENDEDKEY | KEYEVENTF_KEYUP, 0)

def open_app(name: str):
    # CREATE_NEW_CONSOLE — щоб консольні застосунки (cmd, powershell)
    # відкривались у власному вікні, а не виводили текст у консоль бота
    CREATE_NEW_CONSOLE = 0x00000010
    subprocess.Popen(
        name,
        shell=True,
        creationflags=CREATE_NEW_CONSOLE
    )

def show_text_window(text: str, title: str = "Повідомлення"):
    """
    Показує текст у легкому спливаючому віконці через mshta
    (вбудований у Windows HTML-движок, без temp-файлів і без
    окремого процесу типу notepad.exe, що висить у пам'яті).
    """
    import html as html_lib

    safe_text = html_lib.escape(text).replace("\n", "<br>")
    safe_title = html_lib.escape(title)

    hta = f"""
<html>
<head>
<meta http-equiv="Content-Type" content="text/html; charset=utf-8">
<title>{safe_title}</title>
<HTA:APPLICATION
    APPLICATIONNAME="Note"
    SCROLL="yes"
    SINGLEINSTANCE="no"
    CAPTION="yes"
    SYSMENU="yes"
    MAXIMIZEBUTTON="yes"
    MINIMIZEBUTTON="yes"
/>
<style>
    body {{
        background: #1e1e2e;
        color: #cdd6f4;
        font-family: Segoe UI, sans-serif;
        font-size: 16px;
        padding: 20px;
        margin: 0;
    }}
    .content {{
        white-space: pre-wrap;
        word-wrap: break-word;
        line-height: 1.5;
    }}
</style>
</head>
<body>
<div class="content">{safe_text}</div>
<script>
    window.resizeTo(500, 400);
    window.moveTo((screen.width-500)/2, (screen.height-400)/2);
</script>
</body>
</html>
""".strip()

    import tempfile, time
    folder = os.path.join(tempfile.gettempdir(), "tgbot_hta")
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, f"note_{int(time.time()*1000)}.hta")
    # utf-8-sig (з BOM) — mshta правильно визначає кодування і кирилицю
    with open(path, "w", encoding="utf-8-sig") as f:
        f.write(hta)

    subprocess.Popen(["mshta.exe", path])

    # видаляємо файл за кілька секунд, mshta вже встигне його прочитати
    def _cleanup():
        time.sleep(3)
        try:
            os.remove(path)
        except Exception:
            pass
    import threading
    threading.Thread(target=_cleanup, daemon=True).start()

def open_url(link: str, incognito: bool = False):
    if not link.startswith("http"):
        link = "https://" + link
    if incognito:
        chrome_paths = [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        ]
        for p in chrome_paths:
            if os.path.exists(p):
                subprocess.Popen([p, "--incognito", link])
                return
        subprocess.Popen(["firefox", "--private-window", link], shell=True)
    else:
        webbrowser.open(link)

# ──────────── КЛАВІАТУРИ ────────────
def main_keyboard():
    kb = [
        [
            InlineKeyboardButton("🔊 Гучніше",     callback_data="vol_up"),
            InlineKeyboardButton("🔉 Тихіше",      callback_data="vol_down"),
            InlineKeyboardButton("🔇 Тихо/Звук",   callback_data="vol_mute"),
        ],
        [
            InlineKeyboardButton("🔕 Звук = 0",    callback_data="vol_zero"),
        ],
        [
            InlineKeyboardButton("☀️ Яскравіше",   callback_data="br_up"),
            InlineKeyboardButton("🌑 Темніше",     callback_data="br_down"),
        ],
        [
            InlineKeyboardButton("_SPACE", callback_data="space"),
        ],
        [
            InlineKeyboardButton("🗕 Згорнути все", callback_data="minimize"),
            InlineKeyboardButton("🔒 Блокувати",    callback_data="lock"),
        ],
        [
            InlineKeyboardButton("📋 Швидке меню", callback_data="amenu"),
            InlineKeyboardButton("⚡ Вимкнути ПК", callback_data="theend"),
        ],
    ]
    return InlineKeyboardMarkup(kb)

def amenu_keyboard():
    rows = []
    for i in range(0, len(AMENU_APPS), 2):
        row = []
        for idx, (label, app) in enumerate(AMENU_APPS[i:i+2], start=i):
            row.append(InlineKeyboardButton(label, callback_data=f"open__{idx}"))
        rows.append(row)
    rows.append([InlineKeyboardButton("⬅️ Назад", callback_data="back_main")])
    return InlineKeyboardMarkup(rows)

def yt_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("⏯ Пауза", callback_data="yt_pause"),
        ],
        [
            InlineKeyboardButton("⏪ -10с", callback_data="yt_back"),
            InlineKeyboardButton("⏩ +10с", callback_data="yt_forward"),
        ],
        [
            InlineKeyboardButton("⏭ Наступне", callback_data="yt_next"),
            InlineKeyboardButton("⏮ Попереднє", callback_data="yt_prev"),
        ],
        [
            InlineKeyboardButton("📺 Повний екран", callback_data="yt_full"),
        ],
        [
            InlineKeyboardButton("⬅️ Назад", callback_data="back_main"),
        ]
    ])
# ──────────── HANDLERS ────────────
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not guard(update): return
    await update.message.reply_text(
        "🖥️ *PC Control Bot*\n\nВибери дію або введи команду:",
        parse_mode="Markdown",
        reply_markup=main_keyboard()
    )

async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not guard(update): return
    text = (
        "📖 *Список команд:*\n\n"
        "`/start` — головне меню\n"
        "`write <текст>` — показати текст у вікні на ПК\n"
        "  _Приклад:_ `write Привіт зі смартфону!`\n\n"
        "`open <програма>` — відкрити програму\n"
        "  _Приклад:_ `open notepad.exe`\n\n"
        "`url <посилання>` — відкрити в браузері\n"
        "  _Приклад:_ `url google.com`\n\n"
        "`aurl <посилання>` — відкрити в інкогніто\n"
        "  _Приклад:_ `aurl youtube.com`\n\n"
        "`amenu` — швидке меню додатків\n"
        "`search` — пошук інформації у гугл\n"
        "`yt` — швидке меню керування ютуб\n"
        "`lock` — заблокувати ПК\n"
        "`theend` — вимкнути ПК\n"
    )
    await update.message.reply_text(text, parse_mode="Markdown")

async def on_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not guard(update): return
    text = (update.message.text or "").strip()
    lower = text.lower()

    if lower.startswith("write "):
        content = text[6:].strip()  # беремо з оригінального тексту, не lower(), щоб зберегти регістр
        if content:
            try:
                show_text_window(content)
                await update.message.reply_text("🪟 Показано у вікні на ПК")
            except Exception as e:
                await update.message.reply_text(f"❌ Помилка: {e}")
        return

    if lower.startswith("open "):
        app = text[5:].strip()
        if app:
            try:
                open_app(app)
                await update.message.reply_text(f"✅ Відкриваю: `{app}`", parse_mode="Markdown")
            except Exception as e:
                await update.message.reply_text(f"❌ Помилка: {e}")
        return

    if lower.startswith("url "):
        link = text[4:].strip()
        if link:
            open_url(link, incognito=False)
            await update.message.reply_text(f"🌐 Відкриваю: `{link}`", parse_mode="Markdown")
        return

    if lower.startswith("aurl "):
        link = text[5:].strip()
        if link:
            open_url(link, incognito=True)
            await update.message.reply_text(f"🕵️ Інкогніто: `{link}`", parse_mode="Markdown")
        return

    if lower == "amenu":
        await update.message.reply_text(
            "📋 *Швидке меню*\nВибери програму:",
            parse_mode="Markdown",
            reply_markup=amenu_keyboard()
        )
        return

    if lower == "lock":
        lock_pc()
        await update.message.reply_text("🔒 ПК заблоковано")
        return

    if lower == "theend":
        await update.message.reply_text("⚡ Вимкнення через 10 секунд...")
        shutdown_pc()
        return

    if lower.startswith("search "):
        query = text[7:].strip()
        if query:
            search_web(query)
            await update.message.reply_text(
                f"🔎 Пошук: `{query}`",
                parse_mode="Markdown"
            )
        return

    if lower == "yt":
        await update.message.reply_text(
            "🎬 Керування YouTube",
            reply_markup=yt_keyboard()
        )
        return

    await update.message.reply_text(
        "❓ Не розумію. Введи `/help` для списку команд.",
        parse_mode="Markdown"
    )
    return
    

async def on_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not guard(update): return
    q = update.callback_query
    data = q.data

    VOLUME_ACTIONS = {
        "vol_up":   volume_up,
        "vol_down": volume_down,
        "vol_mute": volume_mute,
        "vol_zero": volume_zero,
    }

    actions = {
        "br_up":    (brightness_up,   "☀️ Яскравість +10%"),
        "br_down":  (brightness_down, "🌑 Яскравість -10%"),
        "minimize": (minimize_all,    "🗕 Всі вікна згорнуто"),
        "lock":     (lock_pc,         "🔒 ПК заблоковано"),
    }

    if data in VOLUME_ACTIONS:
        try:
            pct, muted = VOLUME_ACTIONS[data]()
            if muted:
                msg = "🔇 Звук вимкнено"
            elif pct == 0:
                msg = "🔕 Гучність: 0% (тихо)"
            else:
                msg = f"🔊 Гучність: {pct}%"
            await q.answer(msg, show_alert=False)
        except Exception as e:
            log.exception("Помилка дії %s", data)
            await q.answer(f"❌ Помилка: {e}", show_alert=True)

    elif data in actions:
        fn, msg = actions[data]
        try:
            fn()
            await q.answer(msg, show_alert=False)
        except Exception as e:
            log.exception("Помилка дії %s", data)
            await q.answer(f"❌ Помилка: {e}", show_alert=True)

    elif data == "theend":
        await q.answer()
        kb = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✅ Так", callback_data="shutdown_yes"),
                InlineKeyboardButton("❌ Ні", callback_data="shutdown_no"),
            ]
        ])

        await q.edit_message_text(
            "⚠️ Ви справді хочете вимкнути комп'ютер?",
            reply_markup=kb
        )
    
    elif data == "shutdown_yes":
        await q.answer("Вимикаю ПК...")
        await q.edit_message_text("⚡ Комп'ютер буде вимкнений через 10 секунд...")
        subprocess.run(["shutdown", "/s", "/t", "10"])

    elif data == "shutdown_no":
        await q.answer("Скасовано")
        await q.edit_message_text(
            "🖥️ *PC Control Bot*\nВибери дію:",
            parse_mode="Markdown",
            reply_markup=main_keyboard()
        )

    elif data == "amenu":
        await q.answer()
        try:
            await q.edit_message_text(
                "📋 *Швидке меню*\nВибери програму:",
                parse_mode="Markdown",
                reply_markup=amenu_keyboard()
            )
        except Exception:
            pass  # повідомлення вже таке саме

    elif data == "back_main":
        await q.answer()
        try:
            await q.edit_message_text(
                "🖥️ *PC Control Bot*\nВибери дію:",
                parse_mode="Markdown",
                reply_markup=main_keyboard()
            )
        except Exception:
            pass

    elif data.startswith("open__"):
        try:
            idx = int(data[6:])
            label, app = AMENU_APPS[idx]
            open_app(app)
            await q.answer(f"✅ Відкриваю: {label}")
        except Exception as e:
            log.exception("Помилка відкриття за index %s", data)
            await q.answer(f"❌ {e}", show_alert=True)
    elif data == "space":
        try:
            press_space()
            await q.answer("␣ Пробіл натиснуто", show_alert=False)
        except Exception as e:
            await q.answer(f"❌ Помилка: {e}", show_alert=True)

    elif data == "yt_pause":
        press_key(VK_K)
        await q.answer("⏯ Пауза")

    elif data == "yt_forward":
        press_key(VK_L)
        await q.answer("+10 секунд")

    elif data == "yt_back":
        press_key(VK_J)
        await q.answer("-10 секунд")

    elif data == "yt_full":
        press_key(VK_F)
        await q.answer("Повний екран")

    elif data == "yt_next":
        press_key(VK_N)
        await q.answer("Наступне відео")

    elif data == "yt_prev":
        press_key(VK_P)
        await q.answer("Попереднє відео")


# ──────────── MAIN ────────────
def main():
    if BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        print("❌  Встав свій токен у змінну BOT_TOKEN у файлі bot.py!")
        sys.exit(1)

    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help",  cmd_help))
    app.add_handler(CallbackQueryHandler(on_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_message))

    log.info("Бот запущено ✅")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
