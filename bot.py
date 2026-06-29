import logging
import subprocess
import os
import sys
import ctypes
import webbrowser
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

# ──────────── ЗВУК (через PowerShell / nircmd) ────────────
def _ps(cmd: str) -> None:
    subprocess.run(["powershell", "-Command", cmd], capture_output=True)

def volume_up():
    _ps("(New-Object -com WScript.Shell).SendKeys([char]175)")   # VK_VOLUME_UP ×5
    for _ in range(4):
        _ps("(New-Object -com WScript.Shell).SendKeys([char]175)")

def volume_down():
    for _ in range(5):
        _ps("(New-Object -com WScript.Shell).SendKeys([char]174)")

def volume_mute():
    _ps("(New-Object -com WScript.Shell).SendKeys([char]173)")

# ──────────── ЯСКРАВІСТЬ ────────────
def _get_brightness() -> int:
    r = subprocess.run(
        ["powershell", "-Command",
         "(Get-WmiObject -Namespace root/WMI -Class WmiMonitorBrightness).CurrentBrightness"],
        capture_output=True, text=True
    )
    try:
        return int(r.stdout.strip())
    except Exception:
        return 50

def _set_brightness(level: int) -> None:
    level = max(0, min(100, level))
    _ps(f"(Get-WmiObject -Namespace root/WMI -Class WmiMonitorBrightnessMethods)"
        f".WmiSetBrightness(1,{level})")

def brightness_up():
    _set_brightness(_get_brightness() + 10)

def brightness_down():
    _set_brightness(_get_brightness() - 10)

# ──────────── СИСТЕМНІ ────────────
def minimize_all():
    _ps("(New-Object -com Shell.Application).MinimizeAll()")

def lock_pc():
    ctypes.windll.user32.LockWorkStation()

def shutdown_pc():
    subprocess.run(["shutdown", "/s", "/t", "10"])

def open_app(name: str):
    subprocess.Popen(name, shell=True)

def open_url(link: str, incognito: bool = False):
    if not link.startswith("http"):
        link = "https://" + link
    if incognito:
        # Chrome incognito
        chrome_paths = [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        ]
        for p in chrome_paths:
            if os.path.exists(p):
                subprocess.Popen([p, "--incognito", link])
                return
        # fallback — Firefox приватний режим
        subprocess.Popen(["firefox", "--private-window", link], shell=True)
    else:
        webbrowser.open(link)

# ──────────── КЛАВІАТУРА ГОЛОВНОГО МЕНЮ ────────────
def main_keyboard():
    kb = [
        [
            InlineKeyboardButton("🔊 Гучніше",    callback_data="vol_up"),
            InlineKeyboardButton("🔉 Тихіше",     callback_data="vol_down"),
            InlineKeyboardButton("🔇 Тихо",       callback_data="vol_mute"),
        ],
        [
            InlineKeyboardButton("☀️ Яскравіше",  callback_data="br_up"),
            InlineKeyboardButton("🌑 Темніше",    callback_data="br_down"),
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
        for label, app in AMENU_APPS[i:i+2]:
            row.append(InlineKeyboardButton(label, callback_data=f"open__{app}"))
        rows.append(row)
    rows.append([InlineKeyboardButton("⬅️ Назад", callback_data="back_main")])
    return InlineKeyboardMarkup(rows)

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
        "`open <програма>` — відкрити програму\n"
        "  _Приклад:_ `open notepad.exe`\n\n"
        "`url <посилання>` — відкрити в браузері\n"
        "  _Приклад:_ `url google.com`\n\n"
        "`aurl <посилання>` — відкрити в інкогніто\n"
        "  _Приклад:_ `aurl youtube.com`\n\n"
        "`amenu` — швидке меню додатків\n"
        "`lock` — заблокувати ПК\n"
        "`theend` — вимкнути ПК\n"
    )
    await update.message.reply_text(text, parse_mode="Markdown")

async def on_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not guard(update): return
    text = (update.message.text or "").strip()
    lower = text.lower()

    # open <app>
    if lower.startswith("open "):
        app = text[5:].strip()
        if app:
            try:
                open_app(app)
                await update.message.reply_text(f"✅ Відкриваю: `{app}`", parse_mode="Markdown")
            except Exception as e:
                await update.message.reply_text(f"❌ Помилка: {e}")
        return

    # url <link>
    if lower.startswith("url "):
        link = text[4:].strip()
        if link:
            open_url(link, incognito=False)
            await update.message.reply_text(f"🌐 Відкриваю: `{link}`", parse_mode="Markdown")
        return

    # aurl <link>
    if lower.startswith("aurl "):
        link = text[5:].strip()
        if link:
            open_url(link, incognito=True)
            await update.message.reply_text(f"🕵️ Інкогніто: `{link}`", parse_mode="Markdown")
        return

    # amenu
    if lower == "amenu":
        await update.message.reply_text(
            "📋 *Швидке меню*\nВибери програму:",
            parse_mode="Markdown",
            reply_markup=amenu_keyboard()
        )
        return

    # lock
    if lower == "lock":
        lock_pc()
        await update.message.reply_text("🔒 ПК заблоковано")
        return

    # theend
    if lower == "theend":
        await update.message.reply_text("⚡ Вимкнення через 10 секунд...")
        shutdown_pc()
        return

    # unknown
    await update.message.reply_text(
        "❓ Не розумію. Введи `/help` для списку команд.",
        parse_mode="Markdown"
    )

async def on_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not guard(update): return
    q = update.callback_query
    await q.answer()
    data = q.data

    actions = {
        "vol_up":   (volume_up,    "🔊 Гучність підвищена"),
        "vol_down": (volume_down,  "🔉 Гучність знижена"),
        "vol_mute": (volume_mute,  "🔇 Звук вимкнено"),
        "br_up":    (brightness_up,  "☀️ Яскравість підвищена"),
        "br_down":  (brightness_down,"🌑 Яскравість знижена"),
        "minimize": (minimize_all, "🗕 Всі вікна згорнуто"),
        "lock":     (lock_pc,     "🔒 ПК заблоковано"),
    }

    if data in actions:
        fn, msg = actions[data]
        try:
            fn()
            await q.edit_message_text(msg, reply_markup=main_keyboard())
        except Exception as e:
            await q.edit_message_text(f"❌ Помилка: {e}", reply_markup=main_keyboard())

    elif data == "theend":
        await q.edit_message_text("⚡ Вимкнення через 10 секунд...")
        shutdown_pc()

    elif data == "amenu":
        await q.edit_message_text(
            "📋 *Швидке меню*\nВибери програму:",
            parse_mode="Markdown",
            reply_markup=amenu_keyboard()
        )

    elif data == "back_main":
        await q.edit_message_text(
            "🖥️ *PC Control Bot*\nВибери дію:",
            parse_mode="Markdown",
            reply_markup=main_keyboard()
        )

    elif data.startswith("open__"):
        app = data[6:]
        try:
            open_app(app)
            await q.edit_message_text(
                f"✅ Відкриваю: `{app}`",
                parse_mode="Markdown",
                reply_markup=amenu_keyboard()
            )
        except Exception as e:
            await q.edit_message_text(f"❌ {e}", reply_markup=amenu_keyboard())

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
