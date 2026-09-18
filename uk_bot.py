import logging
import subprocess
import os
import sys
import ctypes
import webbrowser
import urllib.parse
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ForceReply
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters
)
import pygetwindow as gw

_WINDOW_TITLES = {}  # idx -> title, оновлюється щоразу при відкритті меню вікон

# ─────────────────────────────────────────────
# НАЛАШТУВАННЯ — заповни перед запуском!
# ─────────────────────────────────────────────
BOT_TOKEN   = ""   # токен від @BotFather
ALLOWED_ID  =                                       # твій Telegram user_id (перевір через @userinfobot)
# ─────────────────────────────────────────────

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(message)s",
    level=logging.INFO
)
log = logging.getLogger(__name__)

# ──────────── QUICK-MENU APPS ────────────
AMENU_APPS = [
    ("🎮 Steam",        r"C:\Program Files (x86)\Steam\steam.exe"),
    ("💬 Discord",      r"C:\Users\pestr\AppData\Local\Discord\Update.exe --processStart Discord.exe"),
    ("⛏️ TLauncher",    r"C:\Users\pestr\AppData\Roaming\.minecraft\TLauncher.exe"),
    ("🧅 Tor Browser",  r"C:\Users\pestr\Desktop\Tor Browser\Browser\firefox.exe"),
    ("🪖 SQUAD",        r"C:\Users\pestr\Desktop\files\cos\steam\Squad.url"),
    ("⚠️ FPV",          r"C:\Users\pestr\Desktop\files\cos\steam\FPV Kamikaze Drone.url"),
    ("🚛 ETS",          r"C:\Users\pestr\Desktop\files\cos\steam\Euro Truck Simulator 2.url"),
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
VK_SPACE = 0x20
VK_LEFT  = 0x25
VK_RIGHT = 0x27
VK_F = 0x46
VK_K = 0x4B
VK_J = 0x4A
VK_L = 0x4C
VK_N = 0x4E
VK_P = 0x50
KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP       = 0x0002

def press_key(vk):
    ctypes.windll.user32.keybd_event(vk, 0, KEYEVENTF_EXTENDEDKEY, 0)
    ctypes.windll.user32.keybd_event(vk, 0, KEYEVENTF_EXTENDEDKEY | KEYEVENTF_KEYUP, 0)

def press_space():
    press_key(VK_SPACE)

def search_web(query: str):
    q = urllib.parse.quote(query)
    url = f"https://www.google.com/search?q={q}"
    webbrowser.open(url)

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
    log.warning(f"pycaw недоступний ({e}) — використовується фолбек через PowerShell/COM")

    # ──────────── FALLBACK: справжнє системне гучномовлення через PowerShell + COM ────────────
    # (той самий підхід, що й у фолбеку яскравості: реальний запит/зміна стану ОС,
    # а не локальний лічильник, що ні з чим не синхронізований)
    import tempfile as _tempfile

    _AUDIO_PS1_SOURCE = r'''
Add-Type -TypeDefinition @"
using System.Runtime.InteropServices;

[Guid("5CDF2C82-841E-4546-9722-0CF74078229A"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
public interface IAudioEndpointVolume {
    int NotImpl1(); int NotImpl2(); int NotImpl3();
    int SetMasterVolumeLevel(float level, System.Guid eventContext);
    int SetMasterVolumeLevelScalar(float level, System.Guid eventContext);
    int NotImpl4();
    int GetMasterVolumeLevelScalar(out float level);
    int NotImpl5(); int NotImpl6(); int NotImpl7();
    int SetMute([MarshalAs(UnmanagedType.Bool)] bool mute, System.Guid eventContext);
    int GetMute(out bool mute);
}
[Guid("D666063F-1587-4E43-81F1-B948E807363F"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
public interface IMMDevice {
    int Activate(ref System.Guid iid, int clsCtx, int activationParams, out IAudioEndpointVolume endpoint);
}
[Guid("A95664D2-9614-4F35-A746-DE8DB63617E6"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
public interface IMMDeviceEnumerator {
    int NotImpl0();
    int GetDefaultAudioEndpoint(int dataFlow, int role, out IMMDevice endpoint);
}
[ComImport, Guid("BCDE0395-E52F-467C-8E3D-C4579291692E")] public class DeviceEnumComObj { }

public class SysAudio {
    static IAudioEndpointVolume GetVol() {
        var enumerator = (IMMDeviceEnumerator)(new DeviceEnumComObj());
        IMMDevice dev;
        enumerator.GetDefaultAudioEndpoint(0, 1, out dev);
        var iid = typeof(IAudioEndpointVolume).GUID;
        IAudioEndpointVolume epv;
        dev.Activate(ref iid, 23, 0, out epv);
        return epv;
    }
    public static float GetLevel() { float l; GetVol().GetMasterVolumeLevelScalar(out l); return l; }
    public static void SetLevel(float l) { GetVol().SetMasterVolumeLevelScalar(l, System.Guid.Empty); }
    public static bool GetMuted() { bool m; GetVol().GetMute(out m); return m; }
    public static void SetMuted(bool m) { GetVol().SetMute(m, System.Guid.Empty); }
}
"@

switch ($args[0]) {
    "get"  { "{0}|{1}" -f [SysAudio]::GetLevel(), [SysAudio]::GetMuted() }
    "set"  { [SysAudio]::SetLevel([float]$args[1]); "{0}|{1}" -f [SysAudio]::GetLevel(), [SysAudio]::GetMuted() }
    "mute" { [SysAudio]::SetMuted(-not [SysAudio]::GetMuted()); "{0}|{1}" -f [SysAudio]::GetLevel(), [SysAudio]::GetMuted() }
}
'''.strip()

    _audio_ps1_path_cache = None

    def _audio_ps1_path() -> str:
        global _audio_ps1_path_cache
        if _audio_ps1_path_cache is None or not os.path.exists(_audio_ps1_path_cache):
            folder = os.path.join(_tempfile.gettempdir(), "tgbot_audio")
            os.makedirs(folder, exist_ok=True)
            path = os.path.join(folder, "audio.ps1")
            with open(path, "w", encoding="utf-8") as f:
                f.write(_AUDIO_PS1_SOURCE)
            _audio_ps1_path_cache = path
        return _audio_ps1_path_cache

    def _run_audio_ps1(*args) -> tuple[int, bool]:
        CREATE_NO_WINDOW = 0x08000000
        result = subprocess.run(
            ["powershell", "-NonInteractive", "-WindowStyle", "Hidden", "-ExecutionPolicy", "Bypass",
             "-File", _audio_ps1_path(), *[str(a) for a in args]],
            capture_output=True, text=True,
            creationflags=CREATE_NO_WINDOW
        )
        out = result.stdout.strip().splitlines()[-1] if result.stdout.strip() else ""
        try:
            level_str, mute_str = out.split("|")
            return round(float(level_str) * 100), mute_str.strip().lower() == "true"
        except Exception:
            raise RuntimeError(result.stderr.strip() or "не вдалося прочитати гучність з PowerShell")

    def get_volume_status() -> tuple[int, bool]:
        return _run_audio_ps1("get")

    def volume_up() -> tuple[int, bool]:
        pct, _ = _run_audio_ps1("get")
        new_level = min(1.0, (pct + 10) / 100)
        return _run_audio_ps1("set", round(new_level, 2))

    def volume_down() -> tuple[int, bool]:
        pct, _ = _run_audio_ps1("get")
        new_level = max(0.0, (pct - 10) / 100)
        return _run_audio_ps1("set", round(new_level, 2))

    def volume_mute() -> tuple[int, bool]:
        return _run_audio_ps1("mute")

    def volume_zero() -> tuple[int, bool]:
        return _run_audio_ps1("set", 0)

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

def cancel_shutdown():
    subprocess.run(["shutdown", "/a"])

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

def windows_keyboard():
    kb = []
    _WINDOW_TITLES.clear()

    for idx, w in enumerate(gw.getAllWindows()):
        if w.title.strip():
            _WINDOW_TITLES[idx] = w.title
            kb.append([
                InlineKeyboardButton(
                    f"🗔 {w.title[:40]}",
                    callback_data=f"closewin|{idx}"
                )
            ])

    kb.append([
        InlineKeyboardButton("🔄 Оновити", callback_data="windows"),
        InlineKeyboardButton("⬅️ Назад", callback_data="back_main"),
    ])

    return InlineKeyboardMarkup(kb)

# ──────────── КЛАВІАТУРИ (нова структура: головне меню + підменю) ────────────
def main_keyboard():
    kb = [
        [
            InlineKeyboardButton("🔊 Звук", callback_data="menu_sound"),
            InlineKeyboardButton("💡 Екран", callback_data="menu_brightness"),
        ],
        [
            InlineKeyboardButton("🖥️ Система", callback_data="menu_system"),
            InlineKeyboardButton("🪟 Вікна", callback_data="windows"),
        ],
        [
            InlineKeyboardButton("📋 Додатки", callback_data="amenu"),
            InlineKeyboardButton("🎬 YouTube", callback_data="menu_yt"),
        ],
        [
            InlineKeyboardButton("🌐 Відкрити URL", callback_data="ask_url"),
            InlineKeyboardButton("🔎 Пошук", callback_data="ask_search"),
        ],
        [
            InlineKeyboardButton("✏️ Написати на екран", callback_data="ask_write"),
        ],
    ]
    return InlineKeyboardMarkup(kb)

def sound_keyboard():
    pct, muted = get_volume_status()
    status = "🔇 Вимкнено" if muted else f"{pct}%"
    kb = [
        [InlineKeyboardButton(f"📊 Гучність: {status}", callback_data="menu_sound")],
        [
            InlineKeyboardButton("🔉 −10%", callback_data="vol_down"),
            InlineKeyboardButton("🔊 +10%", callback_data="vol_up"),
        ],
        [
            InlineKeyboardButton("🔇 Заглушити/Увімкнути", callback_data="vol_mute"),
        ],
        [
            InlineKeyboardButton("🔕 Звук = 0", callback_data="vol_zero"),
        ],
        [InlineKeyboardButton("⬅️ Назад", callback_data="back_main")],
    ]
    return InlineKeyboardMarkup(kb)

def brightness_keyboard():
    level = _get_brightness()
    kb = [
        [InlineKeyboardButton(f"📊 Яскравість: {level}%", callback_data="menu_brightness")],
        [
            InlineKeyboardButton("🌑 −10%", callback_data="br_down"),
            InlineKeyboardButton("☀️ +10%", callback_data="br_up"),
        ],
        [InlineKeyboardButton("⬅️ Назад", callback_data="back_main")],
    ]
    return InlineKeyboardMarkup(kb)

def system_keyboard():
    kb = [
        [
            InlineKeyboardButton("␣ Пробіл", callback_data="space"),
            InlineKeyboardButton("🗕 Згорнути все", callback_data="minimize"),
        ],
        [
            InlineKeyboardButton("🔒 Блокувати ПК", callback_data="lock"),
            InlineKeyboardButton("⚡ Вимкнути ПК", callback_data="theend"),
        ],
        [InlineKeyboardButton("⬅️ Назад", callback_data="back_main")],
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
            InlineKeyboardButton("⏮ Попереднє", callback_data="yt_prev"),
            InlineKeyboardButton("⏯ Пауза", callback_data="yt_pause"),
            InlineKeyboardButton("⏭ Наступне", callback_data="yt_next"),
        ],
        [
            InlineKeyboardButton("⏪ -10с", callback_data="yt_back"),
            InlineKeyboardButton("⏩ +10с", callback_data="yt_forward"),
        ],
        [
            InlineKeyboardButton("📺 Повний екран", callback_data="yt_full"),
        ],
        [
            InlineKeyboardButton("⬅️ Назад", callback_data="back_main"),
        ]
    ])

MAIN_MENU_TEXT = "🖥️ *PC Control Bot*\n\nВибери розділ або введи команду \\(/help\\):"

# ──────────── HANDLERS ────────────
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not guard(update): return
    ctx.user_data.pop("awaiting", None)
    await update.message.reply_text(
        "🖥️ *PC Control Bot*\n\nВибери розділ або введи команду (/help):",
        parse_mode="Markdown",
        reply_markup=main_keyboard()
    )

async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not guard(update): return
    text = (
        "📖 *Список команд:*\n\n"
        "`/start` — головне меню з кнопками\n"
        "`/help` — цей список команд\n\n"
        "*Текстові команди:*\n"
        "`write <текст>` — показати текст у вікні на ПК\n"
        "  _Приклад:_ `write Привіт зі смартфону!`\n\n"
        "`open <програма>` — відкрити програму / файл / .url\n"
        "  _Приклад:_ `open notepad.exe`\n\n"
        "`url <посилання>` — відкрити в браузері\n"
        "  _Приклад:_ `url google.com`\n\n"
        "`aurl <посилання>` — відкрити в режимі інкогніто\n"
        "  _Приклад:_ `aurl youtube.com`\n\n"
        "`search <запит>` — пошук у Google\n"
        "  _Приклад:_ `search погода Варшава`\n\n"
        "`amenu` — швидке меню додатків (Steam, Discord тощо)\n"
        "`windows` — список відкритих вікон із можливістю закрити\n"
        "`yt` — меню керування YouTube (пауза, перемотка, наступне відео)\n"
        "`lock` — заблокувати ПК\n"
        "`theend` — вимкнути ПК (з підтвердженням)\n"
        "`cancel` — скасувати заплановане вимкнення ПК\n\n"
        "*Кнопки в /start:*\n"
        "🔊 Звук — гучність +/−10%, заглушити, звук = 0\n"
        "💡 Екран — яскравість +/−10%\n"
        "🖥️ Система — пробіл, згорнути все, блокувати, вимкнути\n"
        "🪟 Вікна — список відкритих вікон, закриття з підтвердженням\n"
        "📋 Додатки — швидкий запуск улюблених програм\n"
        "🎬 YouTube — керування відео з клавіатури\n"
        "🌐 Відкрити URL / 🔎 Пошук / ✏️ Написати на екран — бот запитає текст наступним повідомленням"
    )
    await update.message.reply_text(text, parse_mode="Markdown")

async def cmd_cancel_shutdown(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not guard(update): return
    cancel_shutdown()
    await update.message.reply_text("🛑 Вимкнення скасовано")

async def on_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not guard(update): return
    text = (update.message.text or "").strip()
    lower = text.lower()

    # ── обробка відповіді на запит із кнопки (write/url/search) ──
    awaiting = ctx.user_data.pop("awaiting", None)
    if awaiting == "write":
        show_text_window(text)
        await update.message.reply_text("🪟 Показано у вікні на ПК", reply_markup=main_keyboard())
        return
    if awaiting == "url":
        open_url(text, incognito=False)
        await update.message.reply_text(f"🌐 Відкриваю: `{text}`", parse_mode="Markdown", reply_markup=main_keyboard())
        return
    if awaiting == "search":
        search_web(text)
        await update.message.reply_text(f"🔎 Пошук: `{text}`", parse_mode="Markdown", reply_markup=main_keyboard())
        return

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

    if lower.startswith("aurl "):
        link = text[5:].strip()
        if link:
            open_url(link, incognito=True)
            await update.message.reply_text(f"🕵️ Інкогніто: `{link}`", parse_mode="Markdown")
        return

    if lower.startswith("url "):
        link = text[4:].strip()
        if link:
            open_url(link, incognito=False)
            await update.message.reply_text(f"🌐 Відкриваю: `{link}`", parse_mode="Markdown")
        return

    if lower.startswith("search "):
        query = text[7:].strip()
        if query:
            search_web(query)
            await update.message.reply_text(f"🔎 Пошук: `{query}`", parse_mode="Markdown")
        return

    if lower == "amenu":
        await update.message.reply_text(
            "📋 *Швидке меню*\nВибери програму:",
            parse_mode="Markdown",
            reply_markup=amenu_keyboard()
        )
        return

    if lower == "windows":
        await update.message.reply_text(
            "🖥 Відкриті програми:",
            reply_markup=windows_keyboard()
        )
        return

    if lower == "yt":
        await update.message.reply_text(
            "🎬 Керування YouTube",
            reply_markup=yt_keyboard()
        )
        return

    if lower == "lock":
        lock_pc()
        await update.message.reply_text("🔒 ПК заблоковано")
        return

    if lower == "theend":
        await update.message.reply_text("⚡ Вимкнення через 10 секунд... (`cancel` щоб скасувати)", parse_mode="Markdown")
        shutdown_pc()
        return

    if lower == "cancel":
        cancel_shutdown()
        await update.message.reply_text("🛑 Вимкнення скасовано")
        return

    await update.message.reply_text(
        "❓ Не розумію. Введи `/help` для списку команд або `/start` для меню.",
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

    simple_actions = {
        "minimize": (minimize_all, "🗕 Всі вікна згорнуто"),
        "lock":     (lock_pc,      "🔒 ПК заблоковано"),
    }

    # ── навігація між меню ──
    if data == "back_main":
        await q.answer()
        try:
            await q.edit_message_text(
                "🖥️ *PC Control Bot*\nВибери розділ:",
                parse_mode="Markdown",
                reply_markup=main_keyboard()
            )
        except Exception:
            pass
        return

    if data == "menu_sound":
        await q.answer()
        try:
            await q.edit_message_text(
                "🔊 *Керування звуком*",
                parse_mode="Markdown",
                reply_markup=sound_keyboard()
            )
        except Exception:
            pass
        return

    if data == "menu_brightness":
        await q.answer()
        try:
            await q.edit_message_text(
                "💡 *Керування яскравістю*",
                parse_mode="Markdown",
                reply_markup=brightness_keyboard()
            )
        except Exception:
            pass
        return

    if data == "menu_system":
        await q.answer()
        try:
            await q.edit_message_text(
                "🖥️ *Системні дії*",
                parse_mode="Markdown",
                reply_markup=system_keyboard()
            )
        except Exception:
            pass
        return

    if data == "menu_yt":
        await q.answer()
        try:
            await q.edit_message_text(
                "🎬 *Керування YouTube*",
                parse_mode="Markdown",
                reply_markup=yt_keyboard()
            )
        except Exception:
            pass
        return

    if data == "amenu":
        await q.answer()
        try:
            await q.edit_message_text(
                "📋 *Швидке меню*\nВибери програму:",
                parse_mode="Markdown",
                reply_markup=amenu_keyboard()
            )
        except Exception:
            pass
        return

    # ── запити тексту (замінюють ForceReply-повідомленням) ──
    if data == "ask_write":
        ctx.user_data["awaiting"] = "write"
        await q.answer()
        await q.message.reply_text(
            "✏️ Напиши текст, який показати на екрані ПК:",
            reply_markup=ForceReply(selective=True)
        )
        return

    if data == "ask_url":
        ctx.user_data["awaiting"] = "url"
        await q.answer()
        await q.message.reply_text(
            "🌐 Надішли посилання, яке відкрити:",
            reply_markup=ForceReply(selective=True)
        )
        return

    if data == "ask_search":
        ctx.user_data["awaiting"] = "search"
        await q.answer()
        await q.message.reply_text(
            "🔎 Що шукати в Google?",
            reply_markup=ForceReply(selective=True)
        )
        return

    # ── звук (з оновленням підменю, щоб бачити актуальний %) ──
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
            try:
                await q.edit_message_reply_markup(reply_markup=sound_keyboard())
            except Exception:
                pass
        except Exception as e:
            log.exception("Помилка дії %s", data)
            await q.answer(f"❌ Помилка: {e}", show_alert=True)
        return

    # ── яскравість (з оновленням підменю) ──
    if data in ("br_up", "br_down"):
        try:
            level = brightness_up() if data == "br_up" else brightness_down()
            await q.answer(f"💡 Яскравість: {level}%", show_alert=False)
            try:
                await q.edit_message_reply_markup(reply_markup=brightness_keyboard())
            except Exception:
                pass
        except Exception as e:
            log.exception("Помилка дії %s", data)
            await q.answer(f"❌ Помилка: {e}", show_alert=True)
        return

    if data in simple_actions:
        fn, msg = simple_actions[data]
        try:
            fn()
            await q.answer(msg, show_alert=False)
        except Exception as e:
            log.exception("Помилка дії %s", data)
            await q.answer(f"❌ Помилка: {e}", show_alert=True)
        return

    if data == "theend":
        await q.answer()
        kb = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✅ Так", callback_data="shutdown_yes", style="danger"),
                InlineKeyboardButton("❌ Ні", callback_data="shutdown_no", style="success"),
            ]
        ])
        await q.edit_message_text(
            "⚠️ Ви справді хочете вимкнути комп'ютер?",
            reply_markup=kb
        )
        return

    if data == "shutdown_yes":
        await q.answer("Вимикаю ПК...")
        await q.edit_message_text("⚡ Комп'ютер буде вимкнений через 10 секунд...")
        shutdown_pc()
        return

    if data == "shutdown_no":
        await q.answer("Скасовано")
        await q.edit_message_text(
            "🖥️ *PC Control Bot*\nВибери розділ:",
            parse_mode="Markdown",
            reply_markup=main_keyboard()
        )
        return

    if data.startswith("open__"):
        try:
            idx = int(data[6:])
            label, app = AMENU_APPS[idx]
            open_app(app)
            await q.answer(f"✅ Відкриваю: {label}")
        except Exception as e:
            log.exception("Помилка відкриття за index %s", data)
            await q.answer(f"❌ {e}", show_alert=True)
        return

    if data == "space":
        try:
            press_space()
            await q.answer("␣ Пробіл натиснуто", show_alert=False)
        except Exception as e:
            await q.answer(f"❌ Помилка: {e}", show_alert=True)
        return

    yt_actions = {
        "yt_pause":   (VK_K, "⏯ Пауза"),
        "yt_forward": (VK_L, "+10 секунд"),
        "yt_back":    (VK_J, "-10 секунд"),
        "yt_full":    (VK_F, "Повний екран"),
        "yt_next":    (VK_N, "Наступне відео"),
        "yt_prev":    (VK_P, "Попереднє відео"),
    }
    if data in yt_actions:
        vk, msg = yt_actions[data]
        press_key(vk)
        await q.answer(msg)
        return

    if data == "windows":
        try:
            await q.edit_message_text(
                "🖥 Відкриті програми:",
                reply_markup=windows_keyboard()
            )
            await q.answer()
        except Exception as e:
            log.exception("Помилка відкриття списку вікон")
            await q.answer(f"❌ Помилка: {e}", show_alert=True)
        return

    if data.startswith("closewin|"):
        try:
            idx = int(data.split("|", 1)[1])
        except (ValueError, IndexError):
            await q.answer("❌ Некоректні дані", show_alert=True)
            return

        title = _WINDOW_TITLES.get(idx)
        if title is None:
            await q.answer("❌ Вікно вже не існує, онови список", show_alert=True)
            return

        kb = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("Так", callback_data=f"closeyes|{idx}", style="danger"),
                InlineKeyboardButton("Ні", callback_data="windows", style="success")
            ]
        ])
        try:
            await q.edit_message_text(f"❓ Закрити\n\n{title}?", reply_markup=kb)
            await q.answer()
        except Exception as e:
            log.exception("Помилка підтвердження закриття вікна")
            await q.answer(f"❌ Помилка: {e}", show_alert=True)
        return

    if data.startswith("closeyes|"):
        try:
            idx = int(data.split("|", 1)[1])
        except (ValueError, IndexError):
            await q.answer("❌ Некоректні дані", show_alert=True)
            return

        title = _WINDOW_TITLES.get(idx)
        try:
            if title:
                for w in gw.getAllWindows():
                    if w.title == title:
                        w.close()
                        break
            await q.answer("Закрито")
            await q.edit_message_text(
                "🖥 Відкриті програми:",
                reply_markup=windows_keyboard()
            )
        except Exception as e:
            log.exception("Помилка закриття вікна")
            await q.answer(f"❌ Помилка: {e}", show_alert=True)
        return

# ──────────── MAIN ────────────
async def startup_notify(app):
    await app.bot.send_message(
        chat_id=ALLOWED_ID,
        text="🟢 Комп'ютер увімкнувся та бот запущений."
    )

def main():
    if BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        print("❌  Встав свій токен у файлі bot.py!")
        sys.exit(1)

    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(startup_notify)
        .build()
    )
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help",  cmd_help))
    app.add_handler(CommandHandler("cancel", cmd_cancel_shutdown))
    app.add_handler(CallbackQueryHandler(on_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_message))

    log.info("Бот запущено ✅")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
