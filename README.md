🇺🇦 [Українська версія](./uk.md)

# 🖥️ PC Control Bot — Telegram Bot for PC Control

Control your computer via Telegram: volume, brightness, launching apps, open windows, and much more.

## 📋 Installation

### 1. Install Python
Download from https://python.org (3.10+), make sure to check "Add to PATH"

### 2. Install dependencies
Open the bot's folder in PowerShell and run:
```
pip install -r requirements.txt
```

### 3. Configure bot.py
Open `bot.py` and insert your data:
```python
BOT_TOKEN  = "token_from_BotFather"   # @BotFather → /newbot
ALLOWED_ID = 123456789                # your ID from @userinfobot
```

### 4. Run the bot
```
python bot.py
```

---

## 🎮 Text Commands

| Command | Action |
|---------|--------|
| `/start` | Main menu with buttons |
| `/help` | List of all commands |
| `write <text>` | Show text in a window on the PC |
| `open <program>` | Open a program |
| `url <link>` | Open a website in the browser |
| `aurl <link>` | Open a website in **incognito** mode |
| `search <query>` | Search on Google |
| `amenu` | Quick apps menu |
| `yt` | YouTube player control menu |
| `lock` | Lock the PC (Win+L) |
| `theend` | Shut down the PC (after 10 sec) |

### Examples
```
write Buy some milk!
open notepad.exe
open C:\Program Files (x86)\Steam\steam.exe
url youtube.com
aurl instagram.com
search weather Warsaw
```

---

## 🔘 Main Menu Buttons

| Button | Action |
|--------|--------|
| 🔊 Louder | +10% volume → shows current % |
| 🔉 Quieter | −10% volume → shows current % |
| 🔇 Mute/Unmute | Toggle mute → shows status |
| 🔕 Volume = 0 | Sets volume to 0 immediately |
| ☀️ Brighter | +10% brightness → shows current % |
| 🌑 Darker | −10% brightness → shows current % |
| _SPACE | Presses spacebar (play/pause) |
| 🗕 Minimize all | Minimizes all windows |
| 🔒 Lock | Locks the PC |
| 📋 Quick menu | Opens `amenu` |
| ⚡ Shut down PC | Shuts down the PC after 10 sec (with Yes/No confirmation) |
| 🪟 Windows | List of open windows with the ability to close any of them |

---

## 📋 Quick Menu (amenu)

| Button | Program |
|--------|---------|
| 🎮 Steam | `C:\Program Files (x86)\Steam\steam.exe` |
| 💬 Discord | `AppData\Local\Discord\...` |
| ⛏️ TLauncher | `AppData\Roaming\.minecraft\TLauncher.exe` |
| 🧅 Tor Browser | `Desktop\Tor Browser\Browser\firefox.exe` |

### Adding your own program to amenu
In `bot.py`, find the `AMENU_APPS` list and add a line:
```python
("🎯 Name", r"C:\full\path\to\program.exe"),
```
> **How to find the path:** right-click the shortcut → Properties → the "Target" field

---

## 🪟 Window Control

The **🪟 Windows** button shows a list of all open windows on the PC.
- Tap a window from the list → the bot will ask for confirmation
- Confirm ✅ Yes → the window closes and the list refreshes automatically
- ❌ No — returns to the list with no changes

---

## 🎬 YouTube Control (yt)

The `yt` command or button menu simulates player key presses (works if the relevant video window is in focus):

| Button | Action |
|--------|--------|
| ⏯ Pause | K |
| ⏪ −10s | J |
| ⏩ +10s | L |
| ⏭ Next | N |
| ⏮ Previous | P |
| 📺 Fullscreen | F |

---

## 🔊 Volume Logic

After every volume change, the bot shows a popup message:
- `🔊 Volume: 70%` — after increasing
- `🔉 Volume: 40%` — after decreasing
- `🔇 Sound muted` — if mute is enabled
- `🔕 Volume: 0% (muted)` — after setting to zero

The bot uses **pycaw** for precise volume level reading.
If pycaw is unavailable, it automatically falls back to WinAPI (less precise, but always works).

---

## 🔁 Auto-start on Windows Boot

1. Press `Win + R`, type `shell:startup`
2. Create a file `start_bot.bat` with the content:
```bat
@echo off
pythonw "C:\path\to\bot.py"
```
3. Copy the `.bat` file into the startup folder

On every launch, the bot sends the message `🟢 Computer turned on and bot started.`

---

## ⚠️ Important

- The bot works **only on Windows**
- Brightness control only works on **laptops** or monitors with WMI support
- `aurl` opens Chrome in incognito mode (requires Chrome)
- `theend` shuts down the PC after 10 seconds → to cancel: `shutdown /a` in CMD
- Check the paths to TLauncher and Tor Browser in the `AMENU_APPS` list
- Only the user with `ALLOWED_ID` has access to the bot — all other requests are ignored
