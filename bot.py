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
import pygetwindow as gw
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

_WINDOW_TITLES = {}  # idx -> title, refreshed every time the windows menu is opened

def windows_keyboard():
    kb = []
    _WINDOW_TITLES.clear()

    for idx, w in enumerate(gw.getAllWindows()):
        if w.title.strip():
            _WINDOW_TITLES[idx] = w.title
            kb.append([
                InlineKeyboardButton(
                    w.title[:45],
                    callback_data=f"closewin|{idx}"
                )
            ])

    kb.append([
        InlineKeyboardButton("⬅️ Back", callback_data="back_main")
    ])

    return InlineKeyboardMarkup(kb)
# ─────────────────────────────────────────────
# SETTINGS — fill in before running!
# ─────────────────────────────────────────────
BOT_TOKEN   = ""   # token from @BotFather
ALLOWED_ID  = 123456789               # your Telegram user_id (check via @userinfobot)
# ─────────────────────────────────────────────

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(message)s",
    level=logging.INFO
)
log = logging.getLogger(__name__)

# ──────────── QUICK-MENU APPS ────────────
AMENU_APPS = [
    ("🎮 Steam",        r"C:\Program Files (x86)\Steam\steam.exe"),
    ("💬 Discord",      r"C:\Users\admin\AppData\Local\Discord\Update.exe --processStart Discord.exe"),
    ("⛏️ TLauncher",    r"C:\Users\admin\AppData\Roaming\.minecraft\TLauncher.exe"),
    ("🧅 Tor Browser",  r"C:\Users\admin\Desktop\Tor Browser\Browser\firefox.exe"),
    
]

# ──────────── GUARD ────────────
def guard(update: Update) -> bool:
    uid = update.effective_user.id if update.effective_user else None
    if uid != ALLOWED_ID:
        log.warning("Blocked: user_id=%s", uid)
        return False
    return True

# ──────────── PowerShell helper (hidden, no window) ────────────
def _ps(cmd: str) -> str:
    CREATE_NO_WINDOW = 0x08000000
    result = subprocess.run(
        ["powershell", "-NonInteractive", "-WindowStyle", "Hidden", "-Command", cmd],
        capture_output=True, text=True,
        creationflags=CREATE_NO_WINDOW
    )
    return result.stdout.strip()

# ──────────── VOLUME — pycaw (with proper COM initialization) ────────────
try:
    from ctypes import cast, POINTER
    import comtypes
    from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume

    def _vol_iface():
        # COM must be initialized in EVERY thread that uses it
        comtypes.CoInitialize()
        devices = AudioUtilities.GetSpeakers()
        iface = devices.Activate(
            IAudioEndpointVolume._iid_, comtypes.CLSCTX_ALL, None
        )
        return cast(iface, POINTER(IAudioEndpointVolume))

    def get_volume_status() -> tuple[int, bool]:
        """Returns (volume_percent, is_muted)"""
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

    # test call on startup — if it fails, we fall through to except below
    _test = _vol_iface()
    _test.GetMasterVolumeLevelScalar()

    log.info("pycaw: volume control active ✅")

except Exception as e:
    log.warning(f"pycaw unavailable ({e}) — using WinAPI keybd_event")

    # ──────────── FALLBACK: WinAPI keybd_event (no COM, always works) ────────────
    # There's no direct access to the exact system volume % here, so we
    # keep an approximate internal counter inside the bot itself.
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

    _fallback_state = {"level": 50, "muted": False}  # initial approximation

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

# ──────────── BRIGHTNESS (via WMI directly, no PowerShell) ────────────
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

    log.info("WMI: brightness active ✅")

except Exception as _wmi_err:
    log.warning(f"WMI unavailable ({_wmi_err}) — falling back to PowerShell")

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


# ──────────── SYSTEM ────────────
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
    # CREATE_NEW_CONSOLE — so console apps (cmd, powershell) open in their
    # own window instead of dumping text into the bot's own console
    CREATE_NEW_CONSOLE = 0x00000010
    subprocess.Popen(
        name,
        shell=True,
        creationflags=CREATE_NEW_CONSOLE
    )

def show_text_window(text: str, title: str = "Message"):
    """
    Shows text in a lightweight popup window via mshta
    (Windows' built-in HTML engine, no temp files and no
    separate process like notepad.exe hanging around in memory).
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
    # utf-8-sig (with BOM) — mshta correctly detects the encoding and Cyrillic text
    with open(path, "w", encoding="utf-8-sig") as f:
        f.write(hta)

    subprocess.Popen(["mshta.exe", path])

    # delete the file after a few seconds, mshta will have already read it
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

# ──────────── KEYBOARDS ────────────
def main_keyboard():
    kb = [
        [
            InlineKeyboardButton("🔊 Louder",     callback_data="vol_up"),
            InlineKeyboardButton("🔉 Quieter",    callback_data="vol_down"),
            InlineKeyboardButton("🔇 Mute/Sound", callback_data="vol_mute"),
        ],
        [
            InlineKeyboardButton("🔕 Volume = 0", callback_data="vol_zero"),
        ],
        [
            InlineKeyboardButton("☀️ Brighter",   callback_data="br_up"),
            InlineKeyboardButton("🌑 Darker",     callback_data="br_down"),
        ],
        [
            InlineKeyboardButton("_SPACE", callback_data="space"),
        ],
        [
            InlineKeyboardButton("🗕 Minimize all", callback_data="minimize"),
            InlineKeyboardButton("🔒 Lock",         callback_data="lock"),
        ],
        [
            InlineKeyboardButton("📋 Quick menu", callback_data="amenu"),
            InlineKeyboardButton("⚡ Shut down PC", callback_data="theend"),
        ],
        [
            InlineKeyboardButton("🪟 Windows", callback_data="windows")
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
    rows.append([InlineKeyboardButton("⬅️ Back", callback_data="back_main")])
    return InlineKeyboardMarkup(rows)

def yt_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("⏯ Pause", callback_data="yt_pause"),
        ],
        [
            InlineKeyboardButton("⏪ -10s", callback_data="yt_back"),
            InlineKeyboardButton("⏩ +10s", callback_data="yt_forward"),
        ],
        [
            InlineKeyboardButton("⏭ Next", callback_data="yt_next"),
            InlineKeyboardButton("⏮ Previous", callback_data="yt_prev"),
        ],
        [
            InlineKeyboardButton("📺 Fullscreen", callback_data="yt_full"),
        ],
        [
            InlineKeyboardButton("⬅️ Back", callback_data="back_main"),
        ]
    ])
# ──────────── HANDLERS ────────────
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not guard(update): return
    await update.message.reply_text(
        "🖥️ *PC Control Bot*\n\nChoose an action or type a command:",
        parse_mode="Markdown",
        reply_markup=main_keyboard()
    )

async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not guard(update): return
    text = (
        "📖 *Command list:*\n\n"
        "`/start` — main menu\n"
        "`write <text>` — show text in a window on the PC\n"
        "  _Example:_ `write Hello from my phone!`\n\n"
        "`open <program>` — open a program\n"
        "  _Example:_ `open notepad.exe`\n\n"
        "`url <link>` — open in browser\n"
        "  _Example:_ `url google.com`\n\n"
        "`aurl <link>` — open in incognito\n"
        "  _Example:_ `aurl youtube.com`\n\n"
        "`amenu` — quick apps menu\n"
        "`lock` — lock the PC\n"
        "`theend` — shut down the PC\n"
    )
    await update.message.reply_text(text, parse_mode="Markdown")

async def on_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not guard(update): return
    text = (update.message.text or "").strip()
    lower = text.lower()

    if lower.startswith("write "):
        content = text[6:].strip()  # taken from the original text, not lower(), to preserve case
        if content:
            try:
                show_text_window(content)
                await update.message.reply_text("🪟 Shown in a window on the PC")
            except Exception as e:
                await update.message.reply_text(f"❌ Error: {e}")
        return

    if lower.startswith("open "):
        app = text[5:].strip()
        if app:
            try:
                open_app(app)
                await update.message.reply_text(f"✅ Opening: `{app}`", parse_mode="Markdown")
            except Exception as e:
                await update.message.reply_text(f"❌ Error: {e}")
        return

    if lower.startswith("url "):
        link = text[4:].strip()
        if link:
            open_url(link, incognito=False)
            await update.message.reply_text(f"🌐 Opening: `{link}`", parse_mode="Markdown")
        return

    if lower.startswith("aurl "):
        link = text[5:].strip()
        if link:
            open_url(link, incognito=True)
            await update.message.reply_text(f"🕵️ Incognito: `{link}`", parse_mode="Markdown")
        return

    if lower == "amenu":
        await update.message.reply_text(
            "📋 *Quick menu*\nChoose a program:",
            parse_mode="Markdown",
            reply_markup=amenu_keyboard()
        )
        return

    if lower == "lock":
        lock_pc()
        await update.message.reply_text("🔒 PC locked")
        return

    if lower == "theend":
        await update.message.reply_text("⚡ Shutting down in 10 seconds...")
        shutdown_pc()
        return

    if lower.startswith("search "):
        query = text[7:].strip()
        if query:
            search_web(query)
            await update.message.reply_text(
                f"🔎 Search: `{query}`",
                parse_mode="Markdown"
            )
        return

    if lower == "yt":
        await update.message.reply_text(
            "🎬 YouTube control",
            reply_markup=yt_keyboard()
        )
        return

    await update.message.reply_text(
        "❓ I don't understand. Type `/help` for a list of commands.",
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
        "br_up":    (brightness_up,   "☀️ Brightness +10%"),
        "br_down":  (brightness_down, "🌑 Brightness -10%"),
        "minimize": (minimize_all,    "🗕 All windows minimized"),
        "lock":     (lock_pc,         "🔒 PC locked"),
    }

    if data in VOLUME_ACTIONS:
        try:
            pct, muted = VOLUME_ACTIONS[data]()
            if muted:
                msg = "🔇 Sound muted"
            elif pct == 0:
                msg = "🔕 Volume: 0% (muted)"
            else:
                msg = f"🔊 Volume: {pct}%"
            await q.answer(msg, show_alert=False)
        except Exception as e:
            log.exception("Error performing action %s", data)
            await q.answer(f"❌ Error: {e}", show_alert=True)

    elif data in actions:
        fn, msg = actions[data]
        try:
            fn()
            await q.answer(msg, show_alert=False)
        except Exception as e:
            log.exception("Error performing action %s", data)
            await q.answer(f"❌ Error: {e}", show_alert=True)

    elif data == "theend":
        await q.answer()
        kb = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✅ Yes", callback_data="shutdown_yes"),
                InlineKeyboardButton("❌ No", callback_data="shutdown_no"),
            ]
        ])

        await q.edit_message_text(
            "⚠️ Are you sure you want to shut down the computer?",
            reply_markup=kb
        )
    
    elif data == "shutdown_yes":
        await q.answer("Shutting down PC...")
        await q.edit_message_text("⚡ The computer will shut down in 10 seconds...")
        subprocess.run(["shutdown", "/s", "/t", "10"])

    elif data == "shutdown_no":
        await q.answer("Cancelled")
        await q.edit_message_text(
            "🖥️ *PC Control Bot*\nChoose an action:",
            parse_mode="Markdown",
            reply_markup=main_keyboard()
        )

    elif data == "amenu":
        await q.answer()
        try:
            await q.edit_message_text(
                "📋 *Quick menu*\nChoose a program:",
                parse_mode="Markdown",
                reply_markup=amenu_keyboard()
            )
        except Exception:
            pass  # message is already the same

    elif data == "back_main":
        await q.answer()
        try:
            await q.edit_message_text(
                "🖥️ *PC Control Bot*\nChoose an action:",
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
            await q.answer(f"✅ Opening: {label}")
        except Exception as e:
            log.exception("Error opening by index %s", data)
            await q.answer(f"❌ {e}", show_alert=True)
    elif data == "space":
        try:
            press_space()
            await q.answer("␣ Space pressed", show_alert=False)
        except Exception as e:
            await q.answer(f"❌ Error: {e}", show_alert=True)

    elif data == "yt_pause":
        press_key(VK_K)
        await q.answer("⏯ Pause")

    elif data == "yt_forward":
        press_key(VK_L)
        await q.answer("+10 seconds")

    elif data == "yt_back":
        press_key(VK_J)
        await q.answer("-10 seconds")

    elif data == "yt_full":
        press_key(VK_F)
        await q.answer("Fullscreen")

    elif data == "yt_next":
        press_key(VK_N)
        await q.answer("Next video")

    elif data == "yt_prev":
        press_key(VK_P)
        await q.answer("Previous video")

    elif data == "windows":
        try:
            await q.edit_message_text(
                "🖥 Open programs:",
                reply_markup=windows_keyboard()
            )
            await q.answer()
        except Exception as e:
            log.exception("Error opening window list")
            await q.answer(f"❌ Error: {e}", show_alert=True)

    elif data.startswith("closewin|"):
        try:
            idx = int(data.split("|", 1)[1])
        except (ValueError, IndexError):
            await q.answer("❌ Invalid data", show_alert=True)
            return

        title = _WINDOW_TITLES.get(idx)
        if title is None:
            await q.answer("❌ Window no longer exists, refresh the list", show_alert=True)
            return

        kb = InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "✅ Yes",
                    callback_data=f"closeyes|{idx}"
                ),
                InlineKeyboardButton(
                    "❌ No",
                    callback_data="windows"
                )
            ]
        ])
        try:
            await q.edit_message_text(
                f"❓ Close\n\n{title}?",
                reply_markup=kb
            )
            await q.answer()
        except Exception as e:
            log.exception("Error confirming window close")
            await q.answer(f"❌ Error: {e}", show_alert=True)

    elif data.startswith("closeyes|"):
        try:
            idx = int(data.split("|", 1)[1])
        except (ValueError, IndexError):
            await q.answer("❌ Invalid data", show_alert=True)
            return

        title = _WINDOW_TITLES.get(idx)

        try:
            if title:
                for w in gw.getAllWindows():
                    if w.title == title:
                        w.close()
                        break

            await q.answer("Closed")
            await q.edit_message_text(
                "🖥 Open programs:",
                reply_markup=windows_keyboard()
            )
        except Exception as e:
            log.exception("Error closing window")
            await q.answer(f"❌ Error: {e}", show_alert=True)
# ──────────── MAIN ────────────
async def startup_notify(app):
    await app.bot.send_message(
        chat_id=ALLOWED_ID,
        text="🟢 Computer turned on and bot started."
    )

def main():
    if BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        print("❌  Insert your token in bot.py!")
        sys.exit(1)

    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(startup_notify)
        .build()
    )
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help",  cmd_help))
    app.add_handler(CallbackQueryHandler(on_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_message))

    log.info("Bot started ✅")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
