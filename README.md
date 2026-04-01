***

```markdown
SimpleCal

A lightweight, beautifully themed calendar and task management application for Linux, written in Python and GTK4. SimpleCal features full iCalendar (`.ics`) integration, local task management, and a robust background notification daemon to ensure you never miss an event.

✨ Features

📅 Multiple Views: Choose between Full (calendar + agenda), Compact (calendar + event sidebar), or Mini (floating calendar widget) modes.
🔔 Background Daemon: Runs quietly in the background, firing off desktop notifications for your upcoming events and tasks.
🎨 Stunning Themes: Includes 8 pre-built color palettes (Catppuccin Mocha/Latte, Nord, Tokyo Night, Rosé Pine, OLED Black, Minimal White) plus dynamic Material You support via Matugen.
☁️ Cloud Syncing: Read-only integration with iCalendar (`.ics`) feeds like Google Calendar.
📝 Local Tasks: Create, edit, and delete local tasks directly within the app, complete with custom reminder times.
⚙️ Tray Icon Integration: Quick access to your calendar and daemon controls via your desktop environment's system tray.

📦 Prerequisites

Ensure you have the following dependencies installed on your system. 

**Debian/Ubuntu-based systems:**
```bash
sudo apt install python3 python3-gi gir1.2-gtk-4.0 libnotify-bin
```

**Arch-based systems:**
```bash
sudo pacman -S python python-gobject gtk4 libnotify
```

**Optional but recommended:**
* `gir1.2-ayatanaappindicator3-0.1` / `libayatana-appindicator` (For system tray icon support).
* `xdotool` (For precise window positioning on X11).

## 🚀 Installation

1. Clone this repository or download the script:
   ```bash
   git clone [https://github.com/Drago241/simplecal.git](https://github.com/Drago241/simplecal.git)
   cd simplecal
   ```
2. Make the script executable:
   ```bash
   chmod +x simplecal.py
   ```

## ⚙️ Configuration (Adding Google Calendar)

By default, the script includes a placeholder for an iCalendar feed. To sync your own Google Calendar (or any other `.ics` provider):

1. Open `simplecal.py` in your favorite text editor.
2. Locate the `ICS_FEEDS` list near the top of the file (around line 29).
3. Replace the placeholder URL with your secret iCal link:
   ```python
   ICS_FEEDS = [
       dict(
           url="[https://calendar.google.com/calendar/ical/.../basic.ics](https://calendar.google.com/calendar/ical/.../basic.ics)",
           name="My Personal Calendar",
           color="#89b4fa", # Optional custom hex color
           holiday=False,
       ),
       # You can add as many dictionary entries as you want here
   ]
   ```

*Note: To get your Google Calendar iCal link, go to Google Calendar Settings -> Settings for my calendars -> [Your Calendar] -> Integrate calendar -> Secret address in iCal format.*

## 💻 Usage

Run SimpleCal directly from your terminal:

```bash
# Open the full application (default)
./simplecal.py

# Open in Mini widget mode
./simplecal.py -c

# Open in Compact mode
./simplecal.py -C
```

### Notification Daemon

To receive event notifications without keeping the calendar window open, you can start the background daemon:

```bash
./simplecal.py --daemon
```

**Autostart on Login (XFCE/Standard Linux environments):**
You can easily add the daemon to your system's startup applications using the built-in flag:
```bash
./simplecal.py --install-autostart
```

### Command Line Options
```text
  -c, --calendar       Mini calendar only (no header, locked position)
  -C, --compact-cal    Compact calendar + event sidebar
  -d, --daemon         Start background notification daemon
  --install-autostart  Install autostart entry for notification daemon
  -l, --local PATH     Specify a custom path for the local tasks text file
  -t, --theme THEME    Override the current theme (e.g., mocha, nord, tokyo)
  -m, --maximized      Start the window maximized
```

*Geometry flags (e.g., `-w`, `-H`, `-x`, `-y`) are also available to explicitly set the window size and position. Run `./simplecal.py --help` for the full list.*

## ⌨️ Keyboard Shortcuts

| Shortcut | Action |
| :--- | :--- |
| `Esc` | Close the calendar window |
| `T` | Jump to Today |
| `C` | Toggle between Full and Mini view modes |
| `F5` | Manually refresh external `.ics` calendar feeds |

## 📁 File Structure

SimpleCal stores its configuration and local data in your user directory:
* `~/.config/simplecal/settings.json`: Stores your UI preferences and geometry state.
* `~/.config/simplecal/tasks.txt`: Stores your local tasks and reminders.
* `~/.config/simplecal/theme.txt`: Stores your currently selected theme.
* `~/.config/simplecal/daemon.pid`: Keeps track of the running background daemon.
```
