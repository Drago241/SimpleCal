#!/usr/bin/python3
import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk, Gdk, GLib, Pango, Gio

try:
    from gi.repository import GdkX11
except ImportError:
    GdkX11 = None

_AppIndicator = None
for _ind_name in ('AyatanaAppIndicator3', 'AppIndicator3', 'yad'):
    try:
        gi.require_version(_ind_name, '0.1')
        from gi.repository import AyatanaAppIndicator3 as _AppIndicator  
        break
    except Exception:
        try:
            gi.require_version(_ind_name, '0.1')
            import importlib
            _AppIndicator = importlib.import_module(f'gi.repository.{_ind_name}')
            break
        except Exception:
            pass

import sys, urllib.request, threading, datetime, argparse
import os, re, signal, json, webbrowser, calendar as cal_lib
from urllib.parse import quote
import subprocess
import time

ICS_FEEDS = [
    dict(
        url="<insert ical url from https://calendar.google.com/calendar/>",
        name="<custom name>",
        color=None,
        holiday=False,
    ),
]

SIZES = {
    "mini": {
        "window_width":     140,            
        "window_height":    80,             
        "pos_x":            16,
        "pos_y":            500,
        "day_btn_w":        26,
        "day_btn_h":        26,
        "margins":          (4, 4, 4, 4),   
        "spacing":          2,              
        "grid_col_spacing": 0,              
        "grid_row_spacing": 0,              
        "font_month":      "15000",         
        "font_year":       "13000",         
        "font_dow":        "11pt",          
        "font_day":        "14pt",         
        "font_dot":         "4pt",          
        "font_pop_title":   "13000",
        "font_pop_event":   "11000",
    },
    "compact": {
        "window_width":     620,
        "window_height":    310,
        "pos_x":            15,
        "pos_y":            375,
        "day_btn_w":        26,
        "day_btn_h":        30,
        "margins":          (8, 10, 10, 8),
        "spacing":          3,
        "grid_col_spacing": 1,
        "grid_row_spacing": 1,
        "font_month":       "11000",
        "font_year":        "11000",
        "font_dow":         "7.5pt",
        "font_day":         "9pt",
        "font_dot":         "3pt",
        "font_pop_title":   "12000",
        "font_pop_event":   "10000",
        "event_pane_width": 230,
    },
    "full": {
        "window_width":     800,
        "window_height":    680,
        "pos_x":            None,
        "pos_y":            400,
        "day_btn_w":        42,
        "day_btn_h":        48,
        "margins":          (16, 20, 20, 12),
        "spacing":          12,
        "grid_col_spacing": 6,
        "grid_row_spacing": 6,
        "font_month":       "16000",
        "font_year":        "14000",
        "font_dow":         "11pt",
        "font_day":         "13pt",
        "font_dot":         "5pt",
        "agenda_width":     360,
        "cal_pane_height":  400,
    },
    "agenda": {
        "date_header": "16000",
        "month_badge": "11000",
        "day_badge":   "18000",
        "title":       "13000",
        "time":        "11000",
        "location":    "11000",
    },
    "tasks": {
        "date_header": "14000",
        "title":       "13000",
        "time":        "11000",
        "location":    "11000",
        "note":        "11000",
    },
}

CONFIG_DIR         = os.path.expanduser("~/.config/simplecal")
LOCAL_FILE         = os.path.join(CONFIG_DIR, "tasks.txt")
MATUGEN_THEME_FILE = os.path.join(CONFIG_DIR, "matugen.theme")
THEME_FILE         = os.path.join(CONFIG_DIR, "theme.txt")
SETTINGS_FILE      = os.path.join(CONFIG_DIR, "settings.json")
DAEMON_PID_FILE    = os.path.join(CONFIG_DIR, "daemon.pid")

def load_settings() -> dict:
    try:
        with open(SETTINGS_FILE) as f:
            return json.load(f)
    except Exception:
        return {"view_mode": "full", "agenda_visible": True,
                "font_name": None, "opacity_override": None,
                "notifications_enabled": True, "notification_minutes": 15,
                "geometry": {}}

def save_settings(s: dict):
    try:
        os.makedirs(CONFIG_DIR, exist_ok=True)
        with open(SETTINGS_FILE, 'w') as f:
            json.dump(s, f, indent=2)
    except Exception:
        pass

def esc(s: str) -> str:
    return s.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')

def unfold(text: str) -> str:
    return re.sub(r'\r?\n[ \t]', '', text)

def hex_to_rgba(hex_color: str, alpha: float) -> str:
    if not hex_color or not hex_color.startswith('#'):
        return hex_color or 'rgba(0,0,0,0)'
    h = hex_color.lstrip('#')
    if len(h) == 3:
        h = ''.join(c * 2 for c in h)
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"rgba({r},{g},{b},{alpha:.3f})"

def fmt_time(ev: dict) -> str | None:
    return f"{ev['time']} {ev['ampm']}" if ev.get('time') and ev.get('ampm') else None

def fmt_end_time(ev: dict) -> str | None:
    return f"{ev['end_time']} {ev.get('end_ampm','')}" if ev.get('end_time') else None

def relative_label(date: datetime.date, today: datetime.date) -> str:
    delta = (date - today).days
    if delta == 0:   return 'Today'
    if delta == 1:   return 'Tomorrow'
    if delta < 7:    return date.strftime('%A')
    if delta < 60:   return date.strftime('%B %d')
    return date.strftime('%b %d, %Y')

def relative_time_str(ev: dict, now: datetime.datetime) -> str | None:
    t24 = ev.get('time_24h')
    if not t24 or ev.get('allday'):
        return None
    try:
        ev_dt = datetime.datetime.combine(ev['date'],
                    datetime.time.fromisoformat(t24))
        delta = ev_dt - now
        s = delta.total_seconds()
        if s < -3600:  return 'Past'
        if s < 0:      return 'Now'
        h = int(s // 3600)
        m = int((s % 3600) // 60)
        if h >= 48:    return f"In {delta.days}d"
        if h > 0:      return f"In {h}h {m}m" if m else f"In {h}h"
        return f"In {m}m"
    except Exception:
        return None

def _pick(*vals):
    for v in vals:
        if v is not None:
            return v
    return None

def send_desktop_notification(title: str, body: str = '',
                              urgency: str = 'normal', timeout_ms: int = 6000):
    try:
        cmd = ['notify-send', '-u', urgency, '-t', str(timeout_ms),
               '-a', 'SimpleCal', '-i', 'x-office-calendar', '--', title]
        if body:
            cmd.append(body)
        subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except (FileNotFoundError, OSError):
        pass

def install_xfce_autostart():
    autostart_dir = os.path.expanduser("~/.config/autostart")
    desktop_path  = os.path.join(autostart_dir, "simplecal-daemon.desktop")
    script_path   = os.path.abspath(__file__)
    content = (
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Name=SimpleCal Daemon\n"
        "Comment=SimpleCal background notification daemon\n"
        f"Exec={sys.executable} {script_path} --daemon\n"
        "Icon=x-office-calendar\n"
        "Categories=Utility;\n"
        "X-GNOME-Autostart-enabled=true\n"
        "X-XFCE-Autostart-Override=true\n"
        "Hidden=false\n"
        "NoDisplay=false\n"
    )
    try:
        os.makedirs(autostart_dir, exist_ok=True)
        with open(desktop_path, 'w') as f:
            f.write(content)
        return desktop_path
    except Exception as e:
        return None

_TRAY_SCRIPT_TEMPLATE = r"""
import gi, sys, os, signal, subprocess
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, GLib

pid_file  = {pid_file!r}
script    = {script!r}

def _get_daemon_pid():
    try:
        with open(pid_file) as f: return int(f.read().strip())
    except: return None

def open_calendar(*_):
    subprocess.Popen([sys.executable, script], start_new_session=True,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def stop_daemon(*_):
    pid = _get_daemon_pid()
    if pid:
        try: os.kill(pid, signal.SIGTERM)
        except: pass
    Gtk.main_quit()

def on_activate(icon, *_):
    open_calendar()

def on_popup(icon, button, t):
    menu.popup(None, None, Gtk.StatusIcon.position_menu, icon, button, t)

menu = Gtk.Menu()
mi_open = Gtk.MenuItem(label='\U0001f4c5  Open Calendar')
mi_open.connect('activate', open_calendar)
menu.append(mi_open)
menu.append(Gtk.SeparatorMenuItem())
mi_stop = Gtk.MenuItem(label='\u23f9  Stop Daemon')
mi_stop.connect('activate', stop_daemon)
menu.append(mi_stop)
menu.show_all()

icon = Gtk.StatusIcon()
icon.set_from_icon_name('x-office-calendar')
icon.set_title('SimpleCal')
icon.set_tooltip_text('SimpleCal \u2014 notifications active\nLeft-click to open calendar')
icon.connect('activate', on_activate)
icon.connect('popup-menu', on_popup)
icon.set_visible(True)

def _heartbeat():
    if _get_daemon_pid() is None:
        Gtk.main_quit()
        return False
    return True
GLib.timeout_add_seconds(10, _heartbeat)

Gtk.main()
"""

def _check_daemon_running() -> int | None:
    try:
        with open(DAEMON_PID_FILE) as f:
            pid = int(f.read().strip())
        os.kill(pid, 0)
        return pid
    except Exception:
        return None

_MAT = dict(
    crust='#09090b', mantle='#121214', base='#18181b', surface0='#27272a',
    surface1='#3f3f46', surface2='#52525b', overlay0='#71717a', overlay1='#a1a1aa',
    overlay2='#d4d4d8', subtext0='#e4e4e7', subtext1='#f4f4f5', text='#fafafa',
    lavender='#a78bfa', blue='#60a5fa', sapphire='#22d3ee', sky='#38bdf8',
    teal='#2dd4bf', green='#4ade80', yellow='#facc15', peach='#fb923c',
    maroon='#fb7185', red='#f87171', mauve='#c084fc', pink='#f472b6',
    opacity=0.95, event_mark_color='#facc15',
    selected_day_bg='#60a5fa', selected_day_fg='#09090b',
    highlight_bg='#60a5fa', highlight_border='#60a5fa', highlight_alpha=0.16,
)

THEMES = {
    'mocha':    dict(crust='#11111b', mantle='#181825', base='#1e1e2e', surface0='#313244', surface1='#45475a', surface2='#585b70', overlay0='#6c7086', overlay1='#7f849c', overlay2='#9399b2', subtext0='#a6adc8', subtext1='#bac2de', text='#cdd6f4', lavender='#b4befe', blue='#89b4fa', sapphire='#74c7ec', sky='#89dceb', teal='#94e2d5', green='#a6e3a1', yellow='#f9e2af', peach='#fab387', maroon='#eba0ac', red='#f38ba8', mauve='#cba6f7', pink='#f5c2e7', opacity=0.92, event_mark_color='#fab387', selected_day_bg='#cba6f7', selected_day_fg='#11111b', highlight_bg='#cba6f7', highlight_border='#cba6f7', highlight_alpha=0.17),
    'nord':     dict(crust='#191d24', mantle='#1e2430', base='#242933', surface0='#2e3440', surface1='#3b4252', surface2='#434c5e', overlay0='#4c566a', overlay1='#616e7c', overlay2='#7b8ea1', subtext0='#9caabb', subtext1='#cdd6e0', text='#eceff4', lavender='#81a1c1', blue='#5e81ac', sapphire='#88c0d0', sky='#8fbcbb', teal='#8fbcbb', green='#a3be8c', yellow='#ebcb8b', peach='#d08770', maroon='#bf616a', red='#bf616a', mauve='#b48ead', pink='#d8a9c8', opacity=0.94, event_mark_color='#ebcb8b', selected_day_bg='#88c0d0', selected_day_fg='#191d24', highlight_bg='#88c0d0', highlight_border='#88c0d0', highlight_alpha=0.15),
    'tokyo':    dict(crust='#0d0e14', mantle='#11121a', base='#1a1b26', surface0='#1f2335', surface1='#24283b', surface2='#292e42', overlay0='#414868', overlay1='#565f89', overlay2='#737aa2', subtext0='#a9b1d6', subtext1='#c0caf5', text='#c0caf5', lavender='#bb9af7', blue='#7aa2f7', sapphire='#2ac3de', sky='#7dcfff', teal='#73daca', green='#9ece6a', yellow='#e0af68', peach='#ff9e64', maroon='#f7768e', red='#f7768e', mauve='#bb9af7', pink='#ff007c', opacity=0.93, event_mark_color='#e0af68', selected_day_bg='#7aa2f7', selected_day_fg='#0d0e14', highlight_bg='#bb9af7', highlight_border='#7aa2f7', highlight_alpha=0.18),
    'dawn':     dict(crust='#e8dfd0', mantle='#f0e8df', base='#faf4ed', surface0='#f2e9de', surface1='#e4dfde', surface2='#d1cdd1', overlay0='#a8a0b8', overlay1='#9893a5', overlay2='#797593', subtext0='#6e6a86', subtext1='#575279', text='#575279', lavender='#907aa9', blue='#286983', sapphire='#56949f', sky='#39a0c4', teal='#56949f', green='#286983', yellow='#ea9d34', peach='#d7827e', maroon='#b4637a', red='#b4637a', mauve='#907aa9', pink='#d7827e', opacity=0.97, event_mark_color='#ea9d34', selected_day_bg='#907aa9', selected_day_fg='#faf4ed', highlight_bg='#907aa9', highlight_border='#56949f', highlight_alpha=0.14),
    'latte':    dict(crust='#dce0e8', mantle='#e6e9ef', base='#eff1f5', surface0='#ccd0da', surface1='#bcc0cc', surface2='#acb0be', overlay0='#9ca0b0', overlay1='#8c8fa1', overlay2='#7c7f93', subtext0='#6c6f85', subtext1='#5c5f77', text='#4c4f69', lavender='#7287fd', blue='#1e66f5', sapphire='#209fb5', sky='#04a5e5', teal='#179299', green='#40a02b', yellow='#df8e1d', peach='#fe640b', maroon='#e64553', red='#d20f39', mauve='#8839ef', pink='#ea76cb', opacity=0.97, event_mark_color='#df8e1d', selected_day_bg='#8839ef', selected_day_fg='#eff1f5', highlight_bg='#8839ef', highlight_border='#1e66f5', highlight_alpha=0.13),
    'abyss':    dict(crust='#000000', mantle='#04040a', base='#0a0a14', surface0='#10101e', surface1='#181828', surface2='#222236', overlay0='#3a3a5c', overlay1='#555577', overlay2='#7777aa', subtext0='#9999cc', subtext1='#bbbbdd', text='#e0e0ff', lavender='#9b7af7', blue='#4488ff', sapphire='#22bbff', sky='#33ddff', teal='#00ffc0', green='#44ff88', yellow='#ffdd00', peach='#ff9900', maroon='#ff3366', red='#ff2244', mauve='#cc44ff', pink='#ff44bb', opacity=0.97, event_mark_color='#ffdd00', selected_day_bg='#4488ff', selected_day_fg='#000000', highlight_bg='#cc44ff', highlight_border='#4488ff', highlight_alpha=0.20),
    'eternity': dict(crust='#f2f2f7', mantle='#e8e8f0', base='#ffffff', surface0='#dcdce8', surface1='#ccccdc', surface2='#bcbccc', overlay0='#8888aa', overlay1='#666688', overlay2='#444466', subtext0='#333355', subtext1='#111133', text='#0a0a1a', lavender='#6644cc', blue='#1144dd', sapphire='#0077cc', sky='#0099dd', teal='#008877', green='#116622', yellow='#aa6600', peach='#bb4400', maroon='#880022', red='#cc0011', mauve='#7722cc', pink='#cc1188', opacity=0.98, event_mark_color='#aa6600', selected_day_bg='#1144dd', selected_day_fg='#ffffff', highlight_bg='#1144dd', highlight_border='#6644cc', highlight_alpha=0.12),
    'matugen':  _MAT.copy(),
}

THEME_ENTRIES = [
    ('mocha',    '󰌆', 'Mocha',    'Catppuccin · Dark'),
    ('nord',     '󰮄', 'Nord',     'Arctic · Dark'),
    ('tokyo',    '󰻃', 'Tokyo',    'Tokyo Night · Dark'),
    ('abyss',    '󰎚', 'Abyss',    'OLED Black · Vivid'),
    ('latte',    '󰖨', 'Latte',    'Catppuccin · Light'),
    ('dawn',     '󰖛', 'Dawn',     'Rosé Pine · Light'),
    ('eternity', '󰃚', 'Eternity', 'Pure White · Minimal'),
    ('matugen',  '󰔎', 'Matugen',  'Material You · Dynamic'),
]

def _load_saved_theme() -> str:
    try:
        with open(THEME_FILE) as f:
            t = f.read().strip()
            if t in THEMES:
                return t
    except Exception:
        pass
    return 'mocha'

def save_theme(name: str):
    try:
        os.makedirs(CONFIG_DIR, exist_ok=True)
        with open(THEME_FILE, 'w') as f:
            f.write(name)
    except Exception:
        pass

CURRENT_THEME = _load_saved_theme()

def load_matugen_theme() -> dict:
    theme = _MAT.copy()
    try:
        with open(MATUGEN_THEME_FILE) as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith('#') or '=' not in line:
                    continue
                key, _, val = line.partition('=')
                key, val = key.strip(), val.strip()
                if key in ('opacity', 'highlight_alpha'):
                    try:
                        theme[key] = max(0.0, min(1.0, float(val)))
                    except ValueError:
                        pass
                elif val.startswith('#') or val.startswith('@'):
                    theme[key] = val

        _md3 = {
            'background': 'crust', 'surface': 'mantle', 'surface_container': 'base',
            'surface_variant': 'surface0', 'outline_variant': 'surface1', 'outline': 'overlay0',
            'on_surface_variant': 'subtext0', 'on_surface': 'subtext1', 'on_background': 'text',
            'primary': 'blue', 'on_primary': 'selected_day_fg', 'primary_container': 'sky',
            'secondary': 'teal', 'secondary_container': 'green', 'on_secondary_container': 'yellow',
            'tertiary': 'lavender', 'tertiary_container': 'mauve', 'on_tertiary': 'pink',
            'error': 'red', 'error_container': 'maroon',
        }
        for md3_key, sc_key in _md3.items():
            if md3_key in theme:
                theme[sc_key] = theme[md3_key]

        if 'primary' in theme:
            p = theme['primary']
            for k in ('highlight_bg', 'highlight_border', 'selected_day_bg'):
                if theme.get(k) == _MAT.get(k):
                    theme[k] = p
    except (FileNotFoundError, OSError):
        pass
    return theme

def get_theme(name: str) -> dict:
    if name == 'matugen':
        THEMES['matugen'] = load_matugen_theme()
    return THEMES.get(name, THEMES['mocha'])

C = get_theme(CURRENT_THEME)

def _parse_dt(line: str):
    val = line.split(':', 1)[-1].strip()
    try:
        if 'T' in val:
            dt = datetime.datetime.strptime(val[:15].rstrip('Z'), '%Y%m%dT%H%M%S')
            return dt.date(), dt.strftime('%I:%M'), dt.strftime('%p'), False, dt.strftime('%H:%M')
        else:
            return datetime.datetime.strptime(val[:8], '%Y%m%d').date(), None, None, True, None
    except ValueError:
        return None, None, None, True, None

def parse_ical(raw: str, feed: dict) -> list:
    raw = unfold(raw)
    src_color  = feed.get('color')
    is_holiday = feed.get('holiday', False)
    src_name   = feed.get('name', '')
    events, ev = [], None

    for line in raw.splitlines():
        tag = line.split(':', 1)[0].split(';')[0]
        if line == 'BEGIN:VEVENT':
            ev = {'is_local': False, 'source_name': src_name,
                  'source_color': src_color, 'is_holiday': is_holiday}
        elif line == 'END:VEVENT':
            if ev and 'date' in ev and 'summary' in ev:
                events.append(ev)
            ev = None
        elif ev is None:
            continue
        elif tag == 'DTSTART':
            d, t12, ampm, allday, t24 = _parse_dt(line)
            if d:
                ev.update(date=d, time=t12, ampm=ampm, allday=allday,
                          time_24h=t24, date_key=d.strftime('%Y%m%d'))
        elif tag == 'DTEND':
            d, t12, ampm, _, _ = _parse_dt(line)
            if d:
                ev.update(end_date=d, end_time=t12, end_ampm=ampm)
        elif tag == 'SUMMARY':
            ev['summary'] = line.split(':', 1)[-1].strip()
        elif tag == 'DESCRIPTION':
            ev['description'] = (line.split(':', 1)[-1]
                                 .replace('\\n', '\n').replace('\\,', ',').strip())
        elif tag == 'LOCATION':
            ev['location'] = line.split(':', 1)[-1].strip()
    return events

def _ensure_local_file(path: str):
    if not os.path.exists(path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w', encoding='utf-8') as fh:
            fh.write("# SimpleCal Local Tasks\n")

def parse_local_tasks(path: str) -> list:
    if not path:
        path = LOCAL_FILE
    _ensure_local_file(path)
    events = []
    with open(path, 'r', encoding='utf-8') as fh:
        for orig_line in fh:
            line = orig_line.strip()
            if not line or line.startswith('#'):
                continue
            parts_main = line.split(' || ')
            task_part  = parts_main[0]
            note = ''
            silent_task      = False
            reminder_minutes = None
            end_time_24h     = None
            for extra in parts_main[1:]:
                _es = extra.strip()
                if _es == '[silent]':
                    silent_task = True
                elif _es.startswith('[remind=') and _es.endswith(']'):
                    try:
                        reminder_minutes = int(_es[8:-1])
                    except ValueError:
                        pass
                elif _es.startswith('[end=') and _es.endswith(']'):
                    try:
                        end_time_24h = _es[5:-1]
                        datetime.datetime.strptime(end_time_24h, '%H:%M')
                    except ValueError:
                        end_time_24h = None
                elif not note:
                    note = _es
            parts = task_part.split(maxsplit=2)
            if len(parts) < 2:
                continue
            try:
                d = datetime.datetime.strptime(parts[0], '%Y-%m-%d').date()
                t12 = t24 = ampm = None
                allday  = True
                summary = ''
                if len(parts) >= 2 and ':' in parts[1] and len(parts[1]) == 5:
                    t = datetime.datetime.strptime(parts[1], '%H:%M')
                    t12    = t.strftime('%I:%M')
                    ampm   = t.strftime('%p')
                    t24    = t.strftime('%H:%M')
                    allday = False
                    summary = parts[2] if len(parts) > 2 else 'Local Task'
                else:
                    summary = ' '.join(parts[1:])
                events.append({
                    'date': d, 'time': t12, 'ampm': ampm, 'allday': allday,
                    'time_24h': t24, 'date_key': d.strftime('%Y%m%d'),
                    'summary': summary, 'is_local': True, 'is_holiday': False,
                    'source_color': None, 'source_name': 'Local',
                    'raw_line': orig_line,
                    'note': note,
                    'silent': silent_task,
                    'reminder_minutes': reminder_minutes,
                    'end_time_24h': end_time_24h,
                    'end_time': (datetime.datetime.strptime(end_time_24h, '%H:%M').strftime('%I:%M')
                                 if end_time_24h else None),
                    'end_ampm': (datetime.datetime.strptime(end_time_24h, '%H:%M').strftime('%p')
                                 if end_time_24h else None),
                })
            except Exception:
                continue
    return events

def check_and_fire_notifications(all_events: list, notified_keys: set,
                                  settings: dict):
    if not settings.get('notifications_enabled', True):
        return notified_keys
    now   = datetime.datetime.now()
    today = now.date()

    for ev in all_events:
        if ev.get('allday') or ev.get('is_holiday'):
            continue
        if ev['date'] != today:
            continue
        t24 = ev.get('time_24h')
        if not t24:
            continue
        try:
            ev_dt = datetime.datetime.combine(today, datetime.time.fromisoformat(t24))
        except Exception:
            continue

        remind_mins  = ev.get('reminder_minutes') or settings.get('notification_minutes', 15)
        window_start = now + datetime.timedelta(minutes=remind_mins - 1)
        window_end   = now + datetime.timedelta(minutes=remind_mins + 1)
        if not (window_start <= ev_dt <= window_end):
            continue

        key = f"{ev['date_key']}-{t24}-{ev['summary']}"
        if key in notified_keys:
            continue
        notified_keys.add(key)

        if ev.get('silent'):
            continue

        t_str = fmt_time(ev) or t24
        body  = f"\uf0550 {t_str}"
        if ev.get('note'):
            body += f"\n{ev['note']}"
        send_desktop_notification(
            title=ev['summary'], body=body,
            urgency='normal' if not ev.get('is_local') else 'low',
        )
    return notified_keys

class NotificationDaemon:
    def __init__(self, args):
        self.args          = args
        self.settings      = load_settings()
        self._all_events   = []
        self._local_events = []
        self._notified     : set = set()
        self._pending      = 0
        self._fetched      : list = []
        self._loop         : GLib.MainLoop | None = None
        self._indicator    = None

    def run(self):
        os.makedirs(CONFIG_DIR, exist_ok=True)

        with open(DAEMON_PID_FILE, 'w') as f:
            f.write(str(os.getpid()))

        print(f"[SimpleCal daemon] PID {os.getpid()} — "
              f"notifications active, tray: {'yes' if _AppIndicator else 'no'}")

        self._loop = GLib.MainLoop()

        GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGTERM,  self._on_term)
        GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGHUP,   self._on_term)
        GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGUSR1,  self._on_sigusr1)
        GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGUSR2,  self._show_window)

        self._local_events = parse_local_tasks(self.args.local or LOCAL_FILE)
        self._fetch_all()
        GLib.timeout_add_seconds(60,  self._tick)
        GLib.timeout_add_seconds(900, self._refetch)

        self._setup_tray()

        try:
            self._loop.run()
        finally:
            self._cleanup()

    def _setup_tray(self):
        try:
            script_code = _TRAY_SCRIPT_TEMPLATE.format(
                pid_file=DAEMON_PID_FILE,
                script=os.path.abspath(__file__),
            )
            self._tray_proc = subprocess.Popen(
                [sys.executable, '-c', script_code],
                start_new_session=True,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            print(f"[SimpleCal daemon] Tray icon spawned (PID {self._tray_proc.pid})")
        except Exception as e:
            print(f"[SimpleCal daemon] Tray unavailable: {e}")
            self._tray_proc = None

    def _tick(self):
        self.settings      = load_settings()
        self._local_events = parse_local_tasks(self.args.local or LOCAL_FILE)
        combined = self._all_events
        ical_events = [e for e in combined if not e.get('is_local')]
        self._all_events = sorted(
            ical_events + self._local_events,
            key=lambda e: (e['date'], e.get('time_24h') or '')
        )
        self._notified = check_and_fire_notifications(
            self._all_events, self._notified, self.settings)
        return GLib.SOURCE_CONTINUE

    def _refetch(self):
        self._fetch_all()
        return GLib.SOURCE_CONTINUE

    def _fetch_all(self):
        self._pending  = len(ICS_FEEDS)
        self._fetched  = []
        for feed in ICS_FEEDS:
            threading.Thread(target=self._fetch_one, args=(feed,), daemon=True).start()

    def _fetch_one(self, feed: dict):
        try:
            req = urllib.request.Request(feed['url'],
                                         headers={'User-Agent': 'SimpleCal/15.0'})
            with urllib.request.urlopen(req, timeout=15) as r:
                raw = r.read().decode('utf-8', errors='replace')
            events = parse_ical(raw, feed)
            GLib.idle_add(self._on_feed_done, events)
        except Exception:
            GLib.idle_add(self._on_feed_done, [])

    def _on_feed_done(self, events: list):
        self._fetched.extend(events)
        self._pending -= 1
        if self._pending == 0:
            combined = self._fetched + self._local_events
            self._all_events = sorted(combined,
                                       key=lambda e: (e['date'], e.get('time_24h') or ''))
            self._notified = check_and_fire_notifications(
                self._all_events, self._notified, self.settings)
        return False

    def _on_term(self, *_):
        print("[SimpleCal daemon] Shutting down")
        self._cleanup()
        if self._loop:
            self._loop.quit()
        return GLib.SOURCE_REMOVE

    def _on_sigusr1(self, *_):
        global CURRENT_THEME, C
        CURRENT_THEME = _load_saved_theme()
        C = get_theme(CURRENT_THEME)
        return GLib.SOURCE_CONTINUE

    def _show_window(self, *_):
        try:
            subprocess.Popen(
                [sys.executable, os.path.abspath(__file__)],
                start_new_session=True,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        except Exception as e:
            print(f"[SimpleCal daemon] Could not launch window: {e}")
        return GLib.SOURCE_CONTINUE

    def _cleanup(self):
        try:
            os.unlink(DAEMON_PID_FILE)
        except Exception:
            pass
        if getattr(self, '_tray_proc', None):
            try:
                self._tray_proc.terminate()
            except Exception:
                pass

class MiniCalendar(Gtk.Box):
    def __init__(self, on_nav, on_day_click, mode='mini'):
        self.mode = mode
        sz = SIZES.get(mode, SIZES['mini'])

        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=sz['spacing'])

        self.on_nav      = on_nav
        self.on_day_click = on_day_click

        self.month_font = sz['font_month']
        margins         = sz['margins']

        today = datetime.date.today()
        self.year          = today.year
        self.month         = today.month
        self.selected_date = today
        self.event_days    : set = set()
        self.holiday_days  : set = set()
        self.local_days    : set = set()

        self.set_margin_top(margins[0])
        self.set_margin_end(margins[1])
        self.set_margin_bottom(margins[2])
        self.set_margin_start(margins[3])

        if mode == 'mini':
            hdr = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=2)

            self.prev_btn = Gtk.Button(label="‹")
            self.prev_btn.add_css_class("cal-nav-btn")
            self.prev_btn.connect("clicked", self._prev_month)

            self.month_lbl = Gtk.Label()
            self.month_lbl.add_css_class("cal-month-lbl")
            self.month_lbl.set_hexpand(True)
            self.month_lbl.set_halign(Gtk.Align.CENTER)

            self.next_btn = Gtk.Button(label="›")
            self.next_btn.add_css_class("cal-nav-btn")
            self.next_btn.connect("clicked", self._next_month)

            sep_lbl = Gtk.Label(label=" │ ")
            sep_lbl.add_css_class("cal-nav-sep")

            self.prev_yr_btn = Gtk.Button(label="‹")
            self.prev_yr_btn.add_css_class("cal-nav-btn")
            self.prev_yr_btn.connect("clicked", self._prev_year)

            self.year_lbl = Gtk.Label()
            self.year_lbl.add_css_class("cal-month-lbl")
            self.year_lbl.set_halign(Gtk.Align.CENTER)

            self.next_yr_btn = Gtk.Button(label="›")
            self.next_yr_btn.add_css_class("cal-nav-btn")
            self.next_yr_btn.connect("clicked", self._next_year)

            for w in (self.prev_btn, self.month_lbl, self.next_btn,
                      sep_lbl,
                      self.prev_yr_btn, self.year_lbl, self.next_yr_btn):
                hdr.append(w)
        elif mode == 'compact':
            hdr = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=2)

            self.prev_btn = Gtk.Button(label="‹")
            self.prev_btn.add_css_class("cal-nav-btn")
            self.prev_btn.connect("clicked", self._prev_month)

            self.month_lbl = Gtk.Label()
            self.month_lbl.add_css_class("cal-month-lbl")
            self.month_lbl.set_hexpand(True)
            self.month_lbl.set_halign(Gtk.Align.CENTER)

            self.next_btn = Gtk.Button(label="›")
            self.next_btn.add_css_class("cal-nav-btn")
            self.next_btn.connect("clicked", self._next_month)

            sep_lbl = Gtk.Label(label=" │ ")
            sep_lbl.add_css_class("cal-nav-sep")

            self.prev_yr_btn = Gtk.Button(label="‹")
            self.prev_yr_btn.add_css_class("cal-nav-btn")
            self.prev_yr_btn.connect("clicked", self._prev_year)

            self.year_lbl = Gtk.Label()
            self.year_lbl.add_css_class("cal-month-lbl")
            self.year_lbl.set_halign(Gtk.Align.CENTER)

            self.next_yr_btn = Gtk.Button(label="›")
            self.next_yr_btn.add_css_class("cal-nav-btn")
            self.next_yr_btn.connect("clicked", self._next_year)

            for w in (self.prev_btn, self.month_lbl, self.next_btn,
                      sep_lbl,
                      self.prev_yr_btn, self.year_lbl, self.next_yr_btn):
                hdr.append(w)
        else:
            hdr = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=2)

            self.prev_btn = Gtk.Button(label="‹")
            self.prev_btn.add_css_class("cal-nav-btn")
            self.prev_btn.connect("clicked", self._prev_month)

            self.month_lbl = Gtk.Label()
            self.month_lbl.set_hexpand(True)
            self.month_lbl.set_halign(Gtk.Align.CENTER)
            self.month_lbl.add_css_class("cal-month-lbl")

            self.next_btn = Gtk.Button(label="›")
            self.next_btn.add_css_class("cal-nav-btn")
            self.next_btn.connect("clicked", self._next_month)

            sep_lbl = Gtk.Label(label=" │ ")
            sep_lbl.add_css_class("cal-nav-sep")

            self.prev_yr_btn = Gtk.Button(label="‹")
            self.prev_yr_btn.add_css_class("cal-nav-btn")
            self.prev_yr_btn.connect("clicked", self._prev_year)

            self.year_lbl = Gtk.Label()
            self.year_lbl.add_css_class("cal-month-lbl")
            self.year_lbl.set_halign(Gtk.Align.CENTER)

            self.next_yr_btn = Gtk.Button(label="›")
            self.next_yr_btn.add_css_class("cal-nav-btn")
            self.next_yr_btn.connect("clicked", self._next_year)

            for w in (self.prev_btn, self.month_lbl, self.next_btn,
                      sep_lbl,
                      self.prev_yr_btn, self.year_lbl, self.next_yr_btn):
                hdr.append(w)

        self.append(hdr)

        self.grid = Gtk.Grid(
            column_homogeneous=True,
            row_homogeneous=False,
            column_spacing=sz['grid_col_spacing'],
            row_spacing=sz['grid_row_spacing'],
        )
        self.append(self.grid)

        for i, d in enumerate(["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"]):
            lbl = Gtk.Label(label=d)
            lbl.add_css_class("cal-dow")
            lbl.add_css_class(f"{self.mode}-cal-dow")
            self.grid.attach(lbl, i, 0, 1, 1)

        bw = sz['day_btn_w']
        bh = sz['day_btn_h']
        self.day_btns = []

        for row in range(1, 7):
            for col in range(7):
                btn = Gtk.Button()
                btn.set_size_request(bw, bh)
                
                if self.mode == 'mini':
                    btn.set_halign(Gtk.Align.CENTER)
                    btn.set_valign(Gtk.Align.CENTER)
                
                btn.add_css_class("cal-day-btn")
                btn.connect("clicked", self._day_clicked)

                inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
                inner.set_halign(Gtk.Align.CENTER)
                inner.set_valign(Gtk.Align.CENTER)

                num_lbl = Gtk.Label()
                num_lbl.add_css_class('day-num-lbl')
                num_lbl.add_css_class(f'{self.mode}-day-num-lbl')
                num_lbl.set_halign(Gtk.Align.CENTER)
                num_lbl.set_valign(Gtk.Align.CENTER)

                dot_lbl = Gtk.Label()
                dot_lbl.add_css_class('day-dot-lbl')
                dot_lbl.add_css_class(f'{self.mode}-day-dot-lbl')
                dot_lbl.set_halign(Gtk.Align.CENTER)

                inner.append(num_lbl)
                if self.mode != 'mini':
                    inner.append(dot_lbl)
                else:
                    inner.append(dot_lbl)
                btn.set_child(inner)
                btn._num_lbl = num_lbl
                btn._dot_lbl = dot_lbl

                self.grid.attach(btn, col, row, 1, 1)
                self.day_btns.append(btn)

        self._render()

    def set_margins(self, top, right, bottom, left):
        self.set_margin_top(top)
        self.set_margin_end(right)
        self.set_margin_bottom(bottom)
        self.set_margin_start(left)

    def set_event_days(self, event_days: set, holiday_days: set):
        self.event_days   = event_days
        self.holiday_days = holiday_days
        self._render()

    def set_local_days(self, local_days: set):
        self.local_days = local_days
        self._render()

    def select_date(self, d: datetime.date):
        self.year, self.month, self.selected_date = d.year, d.month, d
        self._render()

    def _prev_month(self, *_):
        if self.month == 1:
            self.month, self.year = 12, self.year - 1
        else:
            self.month -= 1
        self._render(); self.on_nav()

    def _next_month(self, *_):
        if self.month == 12:
            self.month, self.year = 1, self.year + 1
        else:
            self.month += 1
        self._render(); self.on_nav()

    def _prev_year(self, *_):
        self.year -= 1; self._render(); self.on_nav()

    def _next_year(self, *_):
        self.year += 1; self._render(); self.on_nav()

    def _day_clicked(self, btn):
        day = getattr(btn, '_day', 0)
        if day > 0:
            self.selected_date = datetime.date(self.year, self.month, day)
            self._render()
            self.on_day_click(self.selected_date, btn)

    def _render(self):
        d1 = datetime.date(self.year, self.month, 1)

        if self.mode == 'mini':
            self.month_lbl.set_markup(
                f"<span weight='bold' size='{self.month_font}'>"
                f"{d1.strftime('%B')}</span>"
            )
            _yr_font = SIZES['mini']['font_year']
            self.year_lbl.set_markup(
                f"<span weight='bold' size='{_yr_font}'>{self.year}</span>"
            )
        elif self.mode == 'compact':
            self.month_lbl.set_markup(
                f"<span weight='bold' size='{self.month_font}'>"
                f"{d1.strftime('%B')}</span>"
            )
            _yr_font = SIZES['compact']['font_year']
            self.year_lbl.set_markup(
                f"<span weight='bold' size='{_yr_font}'>{self.year}</span>"
            )
        else:
            self.month_lbl.set_markup(
                f"<span weight='bold' size='{self.month_font}'>"
                f"{d1.strftime('%B')}</span>"
            )
            _yr_font = SIZES['full']['font_year']
            self.year_lbl.set_markup(
                f"<span weight='bold' size='{_yr_font}'>{self.year}</span>"
            )

        flat = [day for week in cal_lib.Calendar().monthdayscalendar(self.year, self.month)
                for day in week]
        while len(flat) < 42:
            flat.append(0)

        today = datetime.date.today()
        sel   = self.selected_date
        hol_clr   = C['green']
        local_clr = C['blue']
        ev_clr    = C['event_mark_color']
        dot_sz    = SIZES.get(self.mode, SIZES['mini']).get('font_dot', '4pt')

        for i, btn in enumerate(self.day_btns):
            day   = flat[i]
            btn._day = day

            for cls in ("has-events", "has-holiday", "has-local-events",
                        "selected-day", "today-day", "empty-day", "weekend-day"):
                btn.remove_css_class(cls)

            if day == 0:
                btn._num_lbl.set_label('')
                btn._dot_lbl.set_label('')
                btn.set_sensitive(False)
                btn.add_css_class("empty-day")
            else:
                btn.set_sensitive(True)
                btn._num_lbl.set_label(str(day))

                dots = ''
                if day in self.holiday_days:
                    dots += f"<span color='{hol_clr}' size='{dot_sz}'>●</span>"
                    btn.add_css_class("has-holiday")
                if day in self.local_days:
                    dots += f"<span color='{local_clr}' size='{dot_sz}'>●</span>"
                    btn.add_css_class("has-local-events")
                if day in self.event_days:
                    dots += f"<span color='{ev_clr}' size='{dot_sz}'>●</span>"
                    btn.add_css_class("has-events")

                if dots:
                    btn._dot_lbl.set_markup(dots)
                else:
                    btn._dot_lbl.set_label('')

                is_sel   = sel and sel.year == self.year and sel.month == self.month and sel.day == day
                is_today = today.year == self.year and today.month == self.month and today.day == day
                col = i % 7
                if col >= 5:
                    btn.add_css_class("weekend-day")

                if is_sel:
                    btn.add_css_class("selected-day")
                elif is_today:
                    btn.add_css_class("today-day")

class SimpleCalWindow(Gtk.ApplicationWindow):
    def __init__(self, app, args):
        super().__init__(application=app)
        self.args       = args
        self.local_file = args.local or LOCAL_FILE
        self.settings   = load_settings()

        self._font_name = _pick(args.font_name, self.settings.get('font_name'), "sans-serif")

        if args.compact_cal:
            self.view_mode = 'compact'
        elif args.calendar:
            self.view_mode = 'mini'
        else:
            self.view_mode = self.settings.get('view_mode', 'full')

        self.is_mini_view = (self.view_mode == 'mini')

        self.set_title("SimpleCal")
        self.set_resizable(True)
        self.add_css_class('main-window')

        if args.calendar:
            self.add_css_class('calendar-only')

        self._update_window_hint()

        self.all_events           = []
        self.local_events         = parse_local_tasks(self.local_file)
        self.row_map              = {}
        self._current_highlighted = []
        self._selected_date       = None
        self._dialog_open         = False
        self._active_pop          = None
        self._pending             = 0
        self._fetched_ical        = []
        self._theme_btns          = {}
        self._compact_date_hdr    = None
        self._compact_day_lbl     = None
        self._compact_date_sub    = None
        self._compact_event_list  = None
        self._notified_keys       : set = set()

        self._build_ui()
        self._apply_css()

        key_ctrl = Gtk.EventControllerKey.new()
        key_ctrl.connect("key-pressed", self._on_key)
        self.add_controller(key_ctrl)

        self.connect("notify::is-active", self._on_focus_change)
        self.connect("close-request", self._on_close_request)

        GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGUSR1, self._on_sigusr1)

        if args.calendar:
            self.hdr_container.set_visible(False)
            self.hline_top.set_visible(False)
            self._mini_footer.set_visible(False)

        self._apply_view_state()
        self.set_visible(True)

        self._update_clock()
        GLib.timeout_add_seconds(1,   self._update_clock)
        GLib.timeout_add_seconds(60,  self._check_notifications)
        GLib.timeout_add_seconds(900, self._auto_refresh)
        self._fetch_all()

        if not self.settings.get('agenda_visible', True) and self.view_mode == 'full':
            self.agenda_pane.set_visible(False)

        if args.maximized:
            self.maximize()

    def _update_window_hint(self):
        if self.view_mode in ('mini', 'compact'):
            try:
                self.set_property('type-hint', Gdk.WindowTypeHint.UTILITY)
            except AttributeError:
                pass
        else:
            try:
                self.set_property('type-hint', Gdk.WindowTypeHint.NORMAL)
            except AttributeError:
                pass

    def _on_focus_change(self, win, _param):
        def _check():
            if not self.props.is_active and not self._dialog_open \
                    and self.view_mode in ('mini', 'compact'):
                self._quit()
            return False
        GLib.timeout_add(200, _check)

    def _on_close_request(self, win):
        self._quit()
        return True

    def _on_sigusr1(self):
        self._retheme('matugen')
        return GLib.SOURCE_CONTINUE

    def _auto_refresh(self):
        self._fetch_all()
        return GLib.SOURCE_CONTINUE

    def _get_xid(self):
        try:
            native = self.get_native()
            if native:
                surface = native.get_surface()
                if surface and GdkX11:
                    return GdkX11.X11Surface.get_xid(surface)
        except Exception:
            pass
        return None

    def _move_window(self, x, y):
        def _do():
            if x is None or y is None:
                return False
            xid = self._get_xid()
            if xid:
                try:
                    subprocess.run(['xdotool', 'windowmove', str(xid), str(x), str(y)],
                                   check=True, capture_output=True)
                    return False
                except (subprocess.SubprocessError, FileNotFoundError):
                    pass
            native = self.get_native()
            if native:
                surface = native.get_surface()
                if surface and hasattr(surface, 'move'):
                    try:
                        surface.move(x, y)
                    except Exception:
                        pass
            return False
        GLib.idle_add(_do)

    def _get_geometry_value(self, mode, key, default):
        if mode == 'full':
            if key == 'window_width'    and self.args.width         is not None: return self.args.width
            if key == 'window_height'   and self.args.height        is not None: return self.args.height
            if key == 'pos_x'           and self.args.pos_x         is not None: return self.args.pos_x
            if key == 'pos_y'           and self.args.pos_y         is not None: return self.args.pos_y
            if key == 'agenda_width'    and self.args.agenda_width  is not None: return self.args.agenda_width
            if key == 'cal_pane_height' and self.args.cal_height    is not None: return self.args.cal_height
        elif mode == 'mini':
            if key == 'window_width'    and self.args.mini_width    is not None: return self.args.mini_width
            if key == 'window_height'   and self.args.mini_height   is not None: return self.args.mini_height
            if key == 'pos_x'           and self.args.mini_x        is not None: return self.args.mini_x
            if key == 'pos_y'           and self.args.mini_y        is not None: return self.args.mini_y
        elif mode == 'compact':
            if key == 'window_width'    and self.args.compact_width  is not None: return self.args.compact_width
            if key == 'window_height'   and self.args.compact_height is not None: return self.args.compact_height
            if key == 'pos_x'           and self.args.compact_x      is not None: return self.args.compact_x
            if key == 'pos_y'           and self.args.compact_y      is not None: return self.args.compact_y

        geo = self.settings.get('geometry', {}).get(mode, {})
        if key in geo and geo[key] is not None:
            return geo[key]
        return default

    def _apply_geometry(self):
        mode = self.view_mode
        sz   = SIZES[mode]
        w = self._get_geometry_value(mode, 'window_width',  sz['window_width'])
        h = self._get_geometry_value(mode, 'window_height', sz['window_height'])
        x = self._get_geometry_value(mode, 'pos_x',         sz.get('pos_x'))
        y = self._get_geometry_value(mode, 'pos_y',         sz.get('pos_y'))
        self.set_default_size(w, h)
        if x is not None and y is not None:
            self._move_window(x, y)

        if mode == 'full':
            aw  = self._get_geometry_value('full', 'agenda_width',    SIZES['full']['agenda_width'])
            cph = self._get_geometry_value('full', 'cal_pane_height', SIZES['full']['cal_pane_height'])
            self.agenda_pane.set_size_request(aw, -1)
            self.vpaned.set_position(cph)

        self._apply_margins()

    def _apply_margins(self):
        mode = self.view_mode
        geo  = self.settings.get('geometry', {}).get(mode, {})
        top    = geo.get('margin_top',    SIZES[mode]['margins'][0])
        right  = geo.get('margin_right',  SIZES[mode]['margins'][1])
        bottom = geo.get('margin_bottom', SIZES[mode]['margins'][2])
        left   = geo.get('margin_left',   SIZES[mode]['margins'][3])
        for cal in (self.cal_mini, self.cal_full, self.cal_compact):
            if cal is not None and cal.mode == mode:
                cal.set_margins(top, right, bottom, left)

    def _build_ui(self):
        self.drag = Gtk.WindowHandle()
        self.hdr_container = self._build_header()
        self.drag.set_child(self.hdr_container)
        self.set_titlebar(self.drag)

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        root.set_name('root')
        self.set_child(root)

        self.hline_top = Gtk.Separator()
        self.hline_top.set_name('hline_top')
        root.append(self.hline_top)

        self.stack = Gtk.Stack()
        self.stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)

        self.mini_container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.cal_mini = MiniCalendar(
            on_nav=self._update_marks,
            on_day_click=self._on_cal_date_selected,
            mode='mini',
        )
        self.mini_container.append(self.cal_mini)

        self._mini_footer = Gtk.Label()
        self._mini_footer.set_name('mini_footer')
        self._mini_footer.set_halign(Gtk.Align.CENTER)
        self._mini_footer.set_margin_bottom(6)
        self._mini_footer.set_markup(
            f"<span color='{C['overlay0']}' size='7500'>"
            f"{datetime.date.today().strftime('%A, %-d %B %Y')}</span>"
        )
        self.mini_container.append(self._mini_footer)
        self.stack.add_named(self.mini_container, 'mini')

        self.compact_container = self._build_compact_view()
        self.stack.add_named(self.compact_container, 'compact')

        self.full_container = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        self.full_container.set_name('body')

        self.hpaned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        self.hpaned.set_wide_handle(True)

        self.agenda_pane = self._build_agenda()
        self.hpaned.set_start_child(self.agenda_pane)

        right_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.vpaned = Gtk.Paned(orientation=Gtk.Orientation.VERTICAL)
        self.vpaned.set_wide_handle(True)

        top_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.cal_full = MiniCalendar(
            on_nav=self._update_marks,
            on_day_click=self._on_cal_date_selected,
            mode='full',
        )
        top_box.append(self.cal_full)
        self.vpaned.set_start_child(top_box)

        bot_box = self._build_task_pane()
        self.vpaned.set_end_child(bot_box)

        right_box.append(self.vpaned)
        self.hpaned.set_end_child(right_box)
        self.full_container.append(self.hpaned)
        self.stack.add_named(self.full_container, 'full')

        root.append(self.stack)

    def _build_header(self):
        hdr = Gtk.CenterBox()
        hdr.set_name('hdr')

        left = Gtk.Box(spacing=6)
        left.set_margin_start(14)

        self.agenda_toggle_btn = Gtk.Button(label='󰍜')
        self.agenda_toggle_btn.set_name('hdr_btn')
        self.agenda_toggle_btn.set_tooltip_text('Toggle Agenda')
        self.agenda_toggle_btn.set_valign(Gtk.Align.CENTER)
        self.agenda_toggle_btn.connect('clicked', self._toggle_agenda)
        left.append(self.agenda_toggle_btn)

        self.view_toggle_btn = Gtk.Button(label='󰃭')
        self.view_toggle_btn.set_name('hdr_btn')
        self.view_toggle_btn.set_tooltip_text('Toggle Mini/Full (C)')
        self.view_toggle_btn.set_valign(Gtk.Align.CENTER)
        self.view_toggle_btn.connect('clicked', self._toggle_view)
        left.append(self.view_toggle_btn)

        self.badge = Gtk.Label(label='')
        self.badge.set_name('badge')
        self.badge.set_valign(Gtk.Align.CENTER)
        left.append(self.badge)

        self.clock_lbl = Gtk.Label()
        self.clock_lbl.set_name('hdr_clock')
        self.clock_lbl.set_valign(Gtk.Align.CENTER)

        right = Gtk.Box(spacing=4)
        right.set_margin_end(12)

        def _hbtn(label, tip, cb, name='hdr_btn'):
            b = Gtk.Button(label=label)
            b.set_name(name)
            b.set_tooltip_text(tip)
            b.set_valign(Gtk.Align.CENTER)
            b.connect('clicked', lambda *_: cb())
            return b

        today_btn   = _hbtn('󰃨', 'Go to today (T)', self._goto_today)
        refresh_btn = _hbtn('󰑐', 'Refresh (F5)',    self._fetch_all)

        notif_on = self.settings.get('notifications_enabled', True)
        self._notif_btn = Gtk.Button(label='󰂚' if notif_on else '󰂛')
        self._notif_btn.set_name('hdr_btn')
        self._notif_btn.set_tooltip_text('Toggle Notifications')
        self._notif_btn.set_valign(Gtk.Align.CENTER)
        if not notif_on:
            self._notif_btn.add_css_class('notif-off')
        self._notif_btn.connect('clicked', self._toggle_notifications)

        self.theme_btn = Gtk.MenuButton(label='󰔎')
        self.theme_btn.set_name('hdr_btn')
        self.theme_btn.set_tooltip_text('Theme & Settings')
        self.theme_btn.set_valign(Gtk.Align.CENTER)
        self._build_theme_popover()

        minimize_btn = _hbtn('', 'Minimize',           lambda: self.minimize(),           name='hdr_btn')
        maximize_btn = _hbtn('', 'Maximize / Restore', self._toggle_maximize,             name='hdr_btn')
        close_btn    = _hbtn('', 'Close (Esc)',         lambda: self._quit(),              name='close_btn')

        for w in (today_btn, refresh_btn, self._notif_btn, self.theme_btn,
                  minimize_btn, maximize_btn, close_btn):
            right.append(w)

        hdr.set_start_widget(left)
        hdr.set_center_widget(self.clock_lbl)
        hdr.set_end_widget(right)
        return hdr

    def _toggle_maximize(self):
        if self.is_maximized(): self.unmaximize()
        else:                   self.maximize()

    def _toggle_notifications(self, *_):
        on = not self.settings.get('notifications_enabled', True)
        self.settings['notifications_enabled'] = on
        save_settings(self.settings)
        self._notif_btn.set_label('󰂚' if on else '󰂛')
        if on: self._notif_btn.remove_css_class('notif-off')
        else:  self._notif_btn.add_css_class('notif-off')

    def _check_notifications(self):
        self._notified_keys = check_and_fire_notifications(
            self.all_events, self._notified_keys, self.settings)
        return GLib.SOURCE_CONTINUE

    def _build_theme_popover(self):
        pop = Gtk.Popover()
        self.theme_btn.set_popover(pop)
        pop.connect('show',   self._on_theme_popover_show)
        pop.connect('closed', lambda _: setattr(self, '_dialog_open', False))
        self.theme_popover = pop

    def _on_theme_popover_show(self, pop):
        self._dialog_open = True
        while child := pop.get_child():
            pop.set_child(None)

        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        vbox.set_margin_start(10); vbox.set_margin_end(10)
        vbox.set_margin_top(10);   vbox.set_margin_bottom(10)
        vbox.set_size_request(290, -1)

        theme_label = Gtk.Label()
        theme_label.set_markup(f"<span weight='bold' size='10000' color='{C['overlay0']}'>THEMES</span>")
        theme_label.set_halign(Gtk.Align.START)
        vbox.append(theme_label)

        themes_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self._theme_btns = {}
        for t_name, ico, label, desc in THEME_ENTRIES:
            active = (t_name == CURRENT_THEME)
            lbl = Gtk.Label()
            lbl.set_markup(
                f'<span weight="{("bold" if active else "normal")}">{ico}  {label}</span>'
                f"  <span size='small' alpha='70%'>{desc}</span>"
            )
            lbl.set_halign(Gtk.Align.START)
            btn = Gtk.Button()
            btn.set_name('theme_opt_btn')
            if active:
                btn.add_css_class('active-theme')
            btn.set_child(lbl)
            btn.connect('clicked', lambda _, n=t_name: (self._retheme(n), pop.popdown()))
            themes_box.append(btn)
            self._theme_btns[t_name] = (btn, lbl)
        vbox.append(themes_box)

        sep = Gtk.Separator()
        sep.set_margin_top(8); sep.set_margin_bottom(4)
        vbox.append(sep)

        notif_header = Gtk.Label()
        notif_header.set_markup(
            f"<span weight='bold' size='10000' color='{C['overlay0']}'>REMINDERS</span>")
        notif_header.set_halign(Gtk.Align.START)
        vbox.append(notif_header)

        notif_row = Gtk.Box(spacing=10)
        notif_row.set_margin_top(4)
        notif_chk = Gtk.CheckButton(label="Desktop notifications")
        notif_chk.set_active(self.settings.get('notifications_enabled', True))

        def _on_notif_toggle(btn):
            on = btn.get_active()
            self.settings['notifications_enabled'] = on
            save_settings(self.settings)
            self._notif_btn.set_label('󰂚' if on else '󰂛')
            if on: self._notif_btn.remove_css_class('notif-off')
            else:  self._notif_btn.add_css_class('notif-off')

        notif_chk.connect('toggled', _on_notif_toggle)
        notif_row.append(notif_chk)
        vbox.append(notif_row)

        remind_row = Gtk.Box(spacing=8)
        remind_row.set_margin_top(4)
        remind_lbl = Gtk.Label(label="Remind")
        remind_lbl.set_halign(Gtk.Align.START)

        remind_spin = Gtk.SpinButton()
        remind_spin.set_range(1, 120)
        remind_spin.set_increments(5, 15)
        remind_spin.set_value(self.settings.get('notification_minutes', 15))
        remind_spin.set_size_request(70, -1)

        def _on_remind_changed(spin):
            self.settings['notification_minutes'] = int(spin.get_value())
            save_settings(self.settings)

        remind_spin.connect('value-changed', _on_remind_changed)
        remind_row.append(remind_lbl)
        remind_row.append(remind_spin)
        remind_row.append(Gtk.Label(label="min before"))
        vbox.append(remind_row)

        sep2 = Gtk.Separator()
        sep2.set_margin_top(8); sep2.set_margin_bottom(4)
        vbox.append(sep2)

        daemon_hdr = Gtk.Label()
        daemon_hdr.set_markup(
            f"<span weight='bold' size='10000' color='{C['overlay0']}'>DAEMON</span>")
        daemon_hdr.set_halign(Gtk.Align.START)
        vbox.append(daemon_hdr)

        daemon_lbl = Gtk.Label()
        dpid = _check_daemon_running()
        if dpid:
            daemon_lbl.set_markup(
                f"<span size='9000' color='{C['green']}'>󰄴  Notification daemon active  (PID {dpid})</span>"
            )
        else:
            daemon_lbl.set_markup(
                f"<span size='9000' color='{C['overlay0']}'>󰂛  No daemon — launching one now…</span>"
            )
            try:
                subprocess.Popen(
                    [sys.executable, os.path.abspath(__file__), '--daemon'],
                    start_new_session=True,
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
            except Exception:
                pass
        daemon_lbl.set_halign(Gtk.Align.START)
        daemon_lbl.set_wrap(True)
        vbox.append(daemon_lbl)

        autostart_lbl = Gtk.Label()
        autostart_desktop = os.path.expanduser("~/.config/autostart/simplecal-daemon.desktop")
        if os.path.exists(autostart_desktop):
            autostart_lbl.set_markup(
                f"<span size='8500' color='{C['teal']}'>󰕥  Autostart on login enabled</span>"
            )
        else:
            autostart_lbl.set_markup(
                f"<span size='8500' color='{C['overlay0']}'>  Not in XFCE autostart</span>"
            )
        autostart_lbl.set_halign(Gtk.Align.START)
        autostart_lbl.set_margin_top(2)
        vbox.append(autostart_lbl)

        autostart_btn = Gtk.Button(label='󰕥  Enable Autostart on Login')
        autostart_btn.add_css_class('pop-add-btn')
        autostart_btn.set_margin_top(6)

        def _on_install_autostart(*_):
            path = install_xfce_autostart()
            if path:
                autostart_lbl.set_markup(
                    f"<span size='8500' color='{C['green']}'>󰄴  Autostart installed: {path}</span>"
                )
                autostart_btn.set_sensitive(False)

        autostart_btn.connect('clicked', _on_install_autostart)
        if os.path.exists(autostart_desktop):
            autostart_btn.set_sensitive(False)
        vbox.append(autostart_btn)

        pop.set_child(vbox)

    def _build_compact_view(self) -> Gtk.Box:
        outer = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        outer.set_name('compact_outer')

        left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        left.set_name('compact_left')
        epw = SIZES['compact']['event_pane_width']
        left.set_size_request(epw, -1)

        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_vexpand(True)

        self._compact_event_list = Gtk.ListBox(name='compact_event_list')
        self._compact_event_list.set_selection_mode(Gtk.SelectionMode.NONE)
        scroll.set_child(self._compact_event_list)
        left.append(scroll)

        task_row = Gtk.Box(spacing=8)
        task_row.set_margin_start(12); task_row.set_margin_end(8)
        task_row.set_margin_top(6);   task_row.set_margin_bottom(8)

        self._compact_add_btn = Gtk.Button(label='+ Task')
        self._compact_add_btn.add_css_class('pop-add-btn')
        self._compact_add_btn.connect('clicked', self._compact_add_task)
        task_row.append(self._compact_add_btn)

        self._compact_edit_btn = Gtk.Button(label='Edit Task')
        self._compact_edit_btn.add_css_class('pop-add-btn')
        self._compact_edit_btn.set_visible(False)
        self._compact_edit_btn.connect('clicked', self._compact_edit_task)
        task_row.append(self._compact_edit_btn)

        self._compact_del_btn = Gtk.Button(label='Delete Task')
        self._compact_del_btn.add_css_class('pop-del-btn')
        self._compact_del_btn.set_visible(False)
        self._compact_del_btn.connect('clicked', self._compact_del_task)
        task_row.append(self._compact_del_btn)
        left.append(task_row)

        vsep = Gtk.Separator(orientation=Gtk.Orientation.VERTICAL)
        vsep.set_name('compact_vsep')

        right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        right.set_name('compact_right')
        right.set_hexpand(True)

        self._compact_day_lbl = Gtk.Label()
        self._compact_day_lbl.set_name('compact_day_lbl')
        self._compact_day_lbl.set_halign(Gtk.Align.CENTER)
        self._compact_day_lbl.set_margin_top(10)
        right.append(self._compact_day_lbl)

        self._compact_date_sub = Gtk.Label()
        self._compact_date_sub.set_name('compact_date_sub')
        self._compact_date_sub.set_halign(Gtk.Align.CENTER)
        self._compact_date_sub.set_margin_bottom(4)
        right.append(self._compact_date_sub)

        self.cal_compact = MiniCalendar(
            on_nav=self._update_marks,
            on_day_click=self._on_cal_date_selected,
            mode='compact',
        )
        right.append(self.cal_compact)

        outer.append(left); outer.append(vsep); outer.append(right)
        self._update_compact_day(datetime.date.today())
        return outer

    def _update_compact_day(self, date: datetime.date):
        if self._compact_day_lbl:
            self._compact_day_lbl.set_markup(
                f"<span weight='heavy' size='22000' color='{C['text']}'>"
                f"{date.strftime('%A')}</span>"
            )
        if self._compact_date_sub:
            self._compact_date_sub.set_markup(
                f"<span size='11000' color='{C['overlay1']}'>"
                f"{date.strftime('%B %-d, %Y')}</span>"
            )
        self._populate_compact_events(date)

    def _populate_compact_events(self, date: datetime.date):
        if self._compact_event_list is None:
            return
        lb = self._compact_event_list
        while child := lb.get_first_child():
            lb.remove(child)

        events = [e for e in self.all_events if e['date'] == date]
        now    = datetime.datetime.now()

        if not events:
            row = Gtk.ListBoxRow(); row.set_selectable(False)
            lbl = Gtk.Label()
            lbl.set_markup(f"<span color='{C['overlay0']}' size='10000'>No events today</span>")
            lbl.set_halign(Gtk.Align.START)
            lbl.set_margin_start(14); lbl.set_margin_top(12)
            row.set_child(lbl); lb.append(row)
        else:
            for ev in events:
                row = Gtk.ListBoxRow(); row.set_selectable(False)
                hbox = Gtk.Box(spacing=8)
                hbox.set_margin_start(12); hbox.set_margin_end(8)
                hbox.set_margin_top(8);   hbox.set_margin_bottom(8)

                if   ev.get('is_local'):    dot_color = C['blue']
                elif ev.get('is_holiday'):  dot_color = C['green']
                elif ev.get('source_color'): dot_color = ev['source_color']
                else:                        dot_color = C['event_mark_color']

                dot = Gtk.Label()
                dot.set_markup(f"<span color='{dot_color}' size='7000'>●</span>")
                dot.set_valign(Gtk.Align.CENTER)

                mid = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
                mid.set_hexpand(True)

                t_str  = fmt_time(ev)
                end_s  = f" – {ev['end_time']} {ev.get('end_ampm','')}" if ev.get('end_time') else ''
                time_lbl = Gtk.Label()
                if t_str:
                    time_lbl.set_markup(f"<span color='{C['overlay1']}' size='9000'>󰥔 {t_str}{end_s}</span>")
                else:
                    time_lbl.set_markup(f"<span color='{C['overlay0']}' size='9000'>󰥔 All Day</span>")
                time_lbl.set_halign(Gtk.Align.START)

                title_lbl = Gtk.Label()
                title_lbl.set_markup(
                    f"<span weight='semibold' color='{dot_color}' size='10000'>"
                    f"{esc(ev['summary'])}</span>"
                )
                title_lbl.set_halign(Gtk.Align.START)
                title_lbl.set_ellipsize(Pango.EllipsizeMode.END)
                title_lbl.set_max_width_chars(20)

                mid.append(time_lbl); mid.append(title_lbl)

                rel = relative_time_str(ev, now)
                rel_lbl = Gtk.Label()
                if rel:
                    rel_lbl.set_markup(f"<span color='{C['sapphire']}' size='8500'>{esc(rel)}</span>")
                rel_lbl.set_valign(Gtk.Align.CENTER)

                hbox.append(dot); hbox.append(mid); hbox.append(rel_lbl)
                row.set_child(hbox); lb.append(row)

        day_locals = [e for e in self.local_events if e['date'] == date]
        if hasattr(self, '_compact_del_btn'):
            self._compact_del_btn.set_visible(bool(day_locals))
        if hasattr(self, '_compact_edit_btn'):
            self._compact_edit_btn.set_visible(bool(day_locals))

    def _compact_add_task(self, *_):
        if self._selected_date: self._show_add_task_dialog(self._selected_date)

    def _compact_edit_task(self, *_):
        if self._selected_date: self._show_edit_task_dialog(self._selected_date)

    def _compact_del_task(self, *_):
        if self._selected_date: self._show_del_task_dialog(self._selected_date)

    def _toggle_view(self, *_):
        if self.args.calendar or self.args.compact_cal:
            return
        if self.view_mode == 'full':
            self.view_mode    = 'mini'
            self.is_mini_view = True
        else:
            self.view_mode    = 'full'
            self.is_mini_view = False
        self.settings['view_mode'] = self.view_mode
        save_settings(self.settings)
        self._apply_view_state()
        self._update_window_hint()

    def _toggle_agenda(self, *_):
        if self.view_mode != 'full':
            return
        vis = self.agenda_pane.get_visible()
        self.agenda_pane.set_visible(not vis)
        self.settings['agenda_visible'] = not vis
        save_settings(self.settings)

    def _apply_view_state(self):
        if self.view_mode == 'mini':
            self.stack.set_visible_child_name('mini')
            self._apply_geometry()
            if self._selected_date:
                self.cal_mini.select_date(self._selected_date)
            self.agenda_toggle_btn.set_visible(False)
            self.view_toggle_btn.set_visible(not self.args.calendar)
            self.theme_btn.set_visible(False)

        elif self.view_mode == 'compact':
            self.stack.set_visible_child_name('compact')
            self._apply_geometry()
            if self._selected_date:
                self.cal_compact.select_date(self._selected_date)
                self._update_compact_day(self._selected_date)
            self.agenda_toggle_btn.set_visible(False)
            self.view_toggle_btn.set_visible(False)
            self.theme_btn.set_visible(False)

        else:
            self.stack.set_visible_child_name('full')
            self._apply_geometry()
            if self._selected_date:
                self.cal_full.select_date(self._selected_date)
                self._show_day(self._selected_date)
            self.agenda_toggle_btn.set_visible(True)
            self.view_toggle_btn.set_visible(True)
            self.theme_btn.set_visible(True)
            if not self.settings.get('agenda_visible', True):
                self.agenda_pane.set_visible(False)

    def _build_agenda(self):
        pane = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        pane.set_name('agenda_pane')

        subhdr = Gtk.Box(spacing=6)
        subhdr.set_name('subhdr')
        subhdr.set_margin_start(20); subhdr.set_margin_top(16)
        subhdr.set_margin_bottom(12)

        self.agenda_date = Gtk.Label()
        self.agenda_date.set_name('subhdr_date')
        self.agenda_date.set_markup(
            f"<span weight='heavy' size='{SIZES['agenda']['date_header']}'>"
            f"{datetime.datetime.now().strftime('%A, %d %B')}</span>"
        )
        subhdr.append(self.agenda_date)
        pane.append(subhdr)
        pane.append(Gtk.Separator(name='agenda_sep'))

        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_vexpand(True)

        self.listbox = Gtk.ListBox(name='agenda_list')
        self.listbox.set_selection_mode(Gtk.SelectionMode.NONE)
        self.listbox.connect('row-activated', self._on_agenda_row_activated)
        scroll.set_child(self.listbox)
        pane.append(scroll)
        return pane

    def _build_task_pane(self):
        bot_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        bot_box.set_name('task_bot_box')
        bot_box.append(Gtk.Separator(name='detail_sep'))

        hdr_box = Gtk.Box(spacing=10)
        hdr_box.set_margin_start(20); hdr_box.set_margin_end(20)
        hdr_box.set_margin_top(16);   hdr_box.set_margin_bottom(8)

        self.detail_hdr = Gtk.Label()
        self.detail_hdr.set_name('detail_hdr')
        self.detail_hdr.set_halign(Gtk.Align.START)
        self.detail_hdr.set_hexpand(True)
        self.detail_hdr.set_markup(
            f"<span color='{C['overlay0']}' size='{SIZES['tasks']['date_header']}'>"
            f"Select a date to see tasks</span>"
        )

        btns_box = Gtk.Box(spacing=8)
        self.del_task_btn = Gtk.Button(label='Delete')
        self.del_task_btn.set_name('del_task_btn')
        self.del_task_btn.set_visible(False)
        self.del_task_btn.connect('clicked', lambda *_: self._on_del_task_clicked())

        self.edit_task_btn = Gtk.Button(label='Edit')
        self.edit_task_btn.set_name('edit_task_btn')
        self.edit_task_btn.set_visible(False)
        self.edit_task_btn.connect('clicked', lambda *_: self._on_edit_task_clicked())

        self.add_task_btn = Gtk.Button(label='Add Task')
        self.add_task_btn.set_name('add_task_btn')
        self.add_task_btn.set_visible(False)
        self.add_task_btn.connect('clicked', lambda *_: self._on_add_task_clicked())

        btns_box.append(self.del_task_btn)
        btns_box.append(self.edit_task_btn)
        btns_box.append(self.add_task_btn)
        hdr_box.append(self.detail_hdr)
        hdr_box.append(btns_box)
        bot_box.append(hdr_box)

        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_margin_start(16); scroll.set_margin_end(16)
        scroll.set_margin_top(4);   scroll.set_margin_bottom(16)
        scroll.set_vexpand(True)

        self.task_listbox = Gtk.ListBox(name='task_list')
        self.task_listbox.set_selection_mode(Gtk.SelectionMode.NONE)
        scroll.set_child(self.task_listbox)
        bot_box.append(scroll)
        return bot_box

    def _retheme(self, name: str):
        global CURRENT_THEME, C
        old = CURRENT_THEME

        def _meta(key):
            return next(((t, i, d) for t, i, _l, d in THEME_ENTRIES if t == key), ('', '', ''))

        if old in self._theme_btns:
            ob, ol = self._theme_btns[old]
            ob.remove_css_class('active-theme')
            t, i, d = _meta(old)
            ol.set_markup(f"<span weight='normal'>{i}  {t}</span>  <span size='small' alpha='70%'>{d}</span>")

        CURRENT_THEME = name
        save_theme(name)
        C = get_theme(name)

        if name in self._theme_btns:
            nb, nl = self._theme_btns[name]
            nb.add_css_class('active-theme')
            t, i, d = _meta(name)
            nl.set_markup(f"<span weight='bold'>{i}  {t}</span>  <span size='small' alpha='70%'>{d}</span>")

        self._apply_css()
        self._update_clock()
        if hasattr(self, '_mini_footer') and self._mini_footer:
            self._mini_footer.set_markup(
                f"<span color='{C['overlay0']}' size='7500'>"
                f"{datetime.date.today().strftime('%A, %-d %B %Y')}</span>"
            )
        self.detail_hdr.set_markup(
            f"<span color='{C['overlay0']}' size='{SIZES['tasks']['date_header']}'>"
            f"Select a date to see tasks</span>"
        )
        self._rebuild_agenda()
        self._update_marks()
        if self._selected_date:
            if self.view_mode == 'full':
                self._show_day(self._selected_date)
            elif self.view_mode == 'compact':
                self._update_compact_day(self._selected_date)

    def _fetch_all(self, *_):
        self._pending      = len(ICS_FEEDS)
        self._fetched_ical = []
        for feed in ICS_FEEDS:
            threading.Thread(target=self._fetch_one, args=(feed,), daemon=True).start()

    def _fetch_one(self, feed: dict):
        try:
            req = urllib.request.Request(feed['url'], headers={'User-Agent': 'SimpleCal/15.0'})
            with urllib.request.urlopen(req, timeout=12) as r:
                raw = r.read().decode('utf-8', errors='replace')
            events = parse_ical(raw, feed)
            GLib.idle_add(self._on_feed_done, events)
        except Exception:
            GLib.idle_add(self._on_feed_done, [])

    def _on_feed_done(self, events: list):
        self._fetched_ical.extend(events)
        self._pending -= 1
        if self._pending == 0:
            combined = self._fetched_ical + self.local_events
            self.all_events = sorted(combined,
                                     key=lambda e: (e['date'], e.get('time_24h') or ''))
            self._rebuild_agenda()
            self._update_marks()
            self._goto_today()
            self._check_notifications()
        return False

    def _clear_agenda(self):
        while child := self.listbox.get_first_child():
            self.listbox.remove(child)
        self.row_map = {}
        self._current_highlighted = []

    def _append_info_row(self, text: str, color: str):
        row = Gtk.ListBoxRow(); row.set_selectable(False)
        lbl = Gtk.Label()
        lbl.set_halign(Gtk.Align.START)
        lbl.set_margin_start(16); lbl.set_margin_top(12); lbl.set_margin_bottom(12)
        lbl.set_markup(f"<span color='{color}'>{text}</span>")
        row.set_child(lbl); self.listbox.append(row)

    def _rebuild_agenda(self):
        self._clear_agenda()
        today = datetime.date.today()

        upcoming_all   = [e for e in self.all_events if e['date'] >= today]
        upcoming_badge = [e for e in upcoming_all if not e.get('is_holiday')]

        self.badge.set_markup(
            f"<span color='{C['blue']}' size='9000'>{len(upcoming_badge)} upcoming</span>"
            if upcoming_badge else ''
        )

        if not upcoming_all:
            self._append_info_row('No upcoming events', C['overlay0'])
            return

        last_date = None
        for ev in upcoming_all:
            d, dk = ev['date'], ev['date_key']

            if d != last_date:
                last_date = d
                rel = relative_label(d, today)
                extra = (
                    f"  <span color='{C['overlay1']}' size='{SIZES['agenda']['time']}'>"
                    f"{d.strftime('%b %d')}</span>"
                    if rel not in ('Today', 'Tomorrow', d.strftime('%A')) else ''
                )
                color = C['peach'] if rel == 'Today' else C['blue'] if rel == 'Tomorrow' else C['mauve']

                sep_row = Gtk.ListBoxRow()
                sep_row._dk = dk; sep_row.set_selectable(False)
                sep_box = Gtk.Box()
                sep_box.set_margin_start(18); sep_box.set_margin_top(18); sep_box.set_margin_bottom(6)
                lbl = Gtk.Label()
                lbl.set_markup(
                    f"<span color='{color}' weight='bold' size='{SIZES['agenda']['time']}'>"
                    f"{rel.upper()}</span>{extra}"
                )
                sep_box.append(lbl); sep_row.set_child(sep_box)
                self.listbox.append(sep_row)

            row = Gtk.ListBoxRow(name='ev_row')
            row._ev = ev
            tip = ev['summary']
            if ev.get('note'):     tip += f"\n󱞁 {ev['note']}"
            if ev.get('location'): tip += f"\n📍 {ev['location']}"
            row.set_tooltip_text(tip)

            outer = Gtk.Box(spacing=14)
            outer.set_margin_start(16); outer.set_margin_end(12)
            outer.set_margin_top(10);   outer.set_margin_bottom(10)

            date_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
            date_box.set_valign(Gtk.Align.START)
            date_box.set_size_request(36, -1)
            mon_lbl = Gtk.Label()
            mon_lbl.set_markup(
                f"<span color='{C['blue']}' size='{SIZES['agenda']['month_badge']}' weight='bold'>"
                f"{d.strftime('%b').upper()}</span>"
            )
            mon_lbl.set_halign(Gtk.Align.START)
            day_lbl = Gtk.Label()
            day_lbl.set_markup(
                f"<span color='{C['peach'] if d == today else C['text']}'"
                f" weight='bold' size='{SIZES['agenda']['day_badge']}'>{d.strftime('%d')}</span>"
            )
            day_lbl.set_halign(Gtk.Align.START)
            date_box.append(mon_lbl); date_box.append(day_lbl)

            col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            if   ev.get('is_local'):    title_color, prefix = C['blue'],             '󰒋 '
            elif ev.get('is_holiday'):  title_color, prefix = C['green'],             ''
            elif ev.get('source_color'): title_color, prefix = ev['source_color'],   ''
            else:                        title_color, prefix = C['event_mark_color'], ''

            title = Gtk.Label()
            title.set_markup(
                f"<span color='{title_color}' weight='bold' size='{SIZES['agenda']['title']}'>"
                f"{prefix}{esc(ev['summary'])}</span>"
            )
            title.set_halign(Gtk.Align.START)
            title.set_ellipsize(Pango.EllipsizeMode.END)
            title.set_max_width_chars(26)
            col.append(title)

            t_str = fmt_time(ev)
            if t_str:
                end_s = f" – {ev['end_time']} {ev.get('end_ampm','')}" if ev.get('end_time') else ''
                tl = Gtk.Label()
                tl.set_markup(
                    f"<span color='{C['overlay1']}' size='{SIZES['agenda']['time']}'>"
                    f" 󰥔 {t_str}{end_s}</span>"
                )
                tl.set_halign(Gtk.Align.START); col.append(tl)
            elif ev.get('allday'):
                al = Gtk.Label()
                al.set_markup(
                    f"<span color='{C['overlay0']}' size='{SIZES['agenda']['time']}'> 󰥔 All Day</span>"
                )
                al.set_halign(Gtk.Align.START); col.append(al)

            if ev.get('location') and not ev.get('is_local'):
                loc = ev['location']
                if len(loc) > 32: loc = loc[:30] + '…'
                ll = Gtk.Label()
                ll.set_markup(
                    f"<span color='{C['teal']}' size='{SIZES['agenda']['location']}'> 󰍎 {esc(loc)}</span>"
                )
                ll.set_halign(Gtk.Align.START); col.append(ll)

            outer.append(date_box); outer.append(col)
            row.set_child(outer)
            self.listbox.append(row)
            self.row_map.setdefault(dk, []).append(row)

    def _update_marks(self):
        for cal in (self.cal_mini, self.cal_full, self.cal_compact):
            y, m = cal.year, cal.month
            ev_days, hol_days, local_days = set(), set(), set()
            for ev in self.all_events:
                d = ev['date']
                if d.year == y and d.month == m:
                    if   ev.get('is_holiday'): hol_days.add(d.day)
                    elif ev.get('is_local'):   local_days.add(d.day)
                    else:                       ev_days.add(d.day)
            cal.set_event_days(ev_days, hol_days)
            cal.set_local_days(local_days)

    def _on_cal_date_selected(self, date: datetime.date | None, anchor: Gtk.Widget | None):
        if date is None:
            return
        self._selected_date = date
        self.cal_mini.select_date(date)
        self.cal_full.select_date(date)
        self.cal_compact.select_date(date)

        if self.view_mode == 'mini':
            if anchor is not None:
                self._show_event_popover(date, anchor)
        elif self.view_mode == 'compact':
            self._update_compact_day(date)
        else:
            self._show_day(date)

    def _show_day(self, date: datetime.date):
        dk = date.strftime('%Y%m%d')
        for r in self._current_highlighted:
            r.remove_css_class('selected-agenda-row')

        targets = self.row_map.get(dk, [])
        self._current_highlighted = targets
        for r in targets:
            r.add_css_class('selected-agenda-row')

        if targets:
            adj = self.listbox.get_parent().get_vadjustment()
            if adj:
                def _scroll():
                    y = targets[0].get_allocation().y
                    adj.set_value(max(0, y - 50))
                GLib.idle_add(_scroll)

        self._populate_task_list(date)
        self.detail_hdr.set_markup(
            f"<span color='{C['pink']}' weight='bold' size='{SIZES['tasks']['date_header']}'>"
            f"Tasks for {date.strftime('%A, %-d %B')}</span>"
        )
        day_locals = [e for e in self.local_events if e['date'] == date]
        self.del_task_btn.set_visible(len(day_locals) > 0)
        self.edit_task_btn.set_visible(len(day_locals) > 0)
        self.add_task_btn.set_visible(True)

    def _goto_today(self, *_):
        today = datetime.date.today()
        self._selected_date = today
        self.cal_mini.select_date(today)
        self.cal_full.select_date(today)
        self.cal_compact.select_date(today)
        self._update_marks()
        if self.view_mode == 'full':
            self._show_day(today)
        elif self.view_mode == 'compact':
            self._update_compact_day(today)

    def _on_agenda_row_activated(self, lb, row):
        if row and hasattr(row, '_ev'):
            d = row._ev['date']
            self._selected_date = d
            self.cal_mini.select_date(d)
            self.cal_full.select_date(d)
            self.cal_compact.select_date(d)
            self._update_marks()
            self._show_day(d)

    def _populate_task_list(self, date: datetime.date):
        while child := self.task_listbox.get_first_child():
            self.task_listbox.remove(child)

        events_for_date = [e for e in self.all_events if e['date'] == date]
        if not events_for_date:
            lbl = Gtk.Label()
            lbl.set_markup(f"<span color='{C['overlay0']}'>No tasks for this day</span>")
            lbl.set_halign(Gtk.Align.CENTER)
            lbl.set_margin_top(28); lbl.set_margin_bottom(28)
            row = Gtk.ListBoxRow(); row.set_child(lbl)
            self.task_listbox.append(row); return

        for ev in events_for_date:
            vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
            vbox.set_margin_start(16); vbox.set_margin_end(16)
            vbox.set_margin_top(14);   vbox.set_margin_bottom(14)

            hbox = Gtk.Box(spacing=8)
            if   ev.get('is_local'):    title_color, prefix = C['blue'],             '󰒋 '
            elif ev.get('is_holiday'):  title_color, prefix = C['green'],             ''
            elif ev.get('source_color'): title_color, prefix = ev['source_color'],   ''
            else:                        title_color, prefix = C['event_mark_color'], ''

            title = Gtk.Label()
            title.set_markup(
                f"<span color='{title_color}' weight='bold' size='{SIZES['tasks']['title']}'>"
                f"{prefix}{esc(ev['summary'])}</span>"
            )
            title.set_halign(Gtk.Align.START)
            hbox.append(title); vbox.append(hbox)

            t_str = fmt_time(ev)
            if t_str:
                end_s = f" – {ev['end_time']} {ev.get('end_ampm','')}" if ev.get('end_time') else ''
                tl = Gtk.Label()
                tl.set_markup(
                    f"<span color='{C['overlay1']}' size='{SIZES['tasks']['time']}'>"
                    f"󰥔 {t_str}{end_s}</span>"
                )
                tl.set_halign(Gtk.Align.START); vbox.append(tl)
            else:
                al = Gtk.Label()
                al.set_markup(
                    f"<span color='{C['overlay0']}' size='{SIZES['tasks']['time']}'>󰥔 All Day</span>"
                )
                al.set_halign(Gtk.Align.START); vbox.append(al)

            if ev.get('location') and not ev.get('is_local'):
                loc_lbl = Gtk.Label()
                loc_lbl.set_markup(
                    f"<span color='{C['teal']}' size='{SIZES['tasks']['location']}'>"
                    f"󰍎 {esc(ev['location'])}</span>"
                )
                loc_lbl.set_halign(Gtk.Align.START); vbox.append(loc_lbl)

            note = ev.get('note') or ev.get('description')
            if note:
                note_lbl = Gtk.Label()
                note_lbl.set_markup(
                    f"<span color='{C['overlay2']}' size='{SIZES['tasks']['note']}'>"
                    f"󱞁 {esc(note)}</span>"
                )
                note_lbl.set_halign(Gtk.Align.START)
                note_lbl.set_wrap(True); note_lbl.set_max_width_chars(48)
                vbox.append(note_lbl)

            row = Gtk.ListBoxRow(name='task_row')
            row.set_child(vbox); self.task_listbox.append(row)

    def _show_event_popover(self, date: datetime.date, anchor: Gtk.Widget):
        if self._active_pop:
            self._active_pop.popdown()

        events     = [e for e in self.all_events   if e['date'] == date]
        day_locals = [e for e in self.local_events if e['date'] == date]

        pop = Gtk.Popover()
        pop.set_parent(anchor)
        pop.set_autohide(True)
        pop.add_css_class('event-pop')
        self._active_pop = pop
        self._dialog_open = True
        pop.connect('closed', self._on_pop_closed)

        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        vbox.set_margin_top(14); vbox.set_margin_bottom(12)
        vbox.set_margin_start(16); vbox.set_margin_end(16)
        vbox.set_size_request(260, -1)

        title_lbl = Gtk.Label()
        title_lbl.set_markup(
            f"<span weight='bold' size='{SIZES['mini']['font_pop_title']}' color='{C['text']}'>"
            f"{date.strftime('%A, %-d %B')}</span>"
        )
        title_lbl.set_halign(Gtk.Align.START)
        title_lbl.set_margin_bottom(10)
        vbox.append(title_lbl)

        if events:
            sep1 = Gtk.Separator(); sep1.set_margin_bottom(8); vbox.append(sep1)
            for ev in events:
                ev_row = Gtk.Box(spacing=8); ev_row.set_margin_bottom(6)

                if   ev.get('is_local'):    dot_color = C['blue']
                elif ev.get('is_holiday'):  dot_color = C['green']
                elif ev.get('source_color'): dot_color = ev['source_color']
                else:                        dot_color = C['event_mark_color']

                dot = Gtk.Label()
                dot.set_markup(f"<span color='{dot_color}'>●</span>")
                dot.set_valign(Gtk.Align.START)
                ev_row.append(dot)

                meta = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
                summ = Gtk.Label()
                summ.set_markup(
                    f"<span weight='semibold' color='{C['text']}'"
                    f" size='{SIZES['mini']['font_pop_event']}'>{esc(ev['summary'])}</span>"
                )
                summ.set_halign(Gtk.Align.START)
                summ.set_ellipsize(Pango.EllipsizeMode.END)
                summ.set_max_width_chars(28)
                meta.append(summ)

                t_str = fmt_time(ev)
                if t_str:
                    end_s = f" – {ev['end_time']} {ev.get('end_ampm','')}" if ev.get('end_time') else ''
                    tl = Gtk.Label()
                    tl.set_markup(
                        f"<span color='{C['overlay1']}' size='{SIZES['mini']['font_pop_event']}'>"
                        f"󰥔 {t_str}{end_s}</span>"
                    )
                    tl.set_halign(Gtk.Align.START); meta.append(tl)
                elif ev.get('allday'):
                    al = Gtk.Label()
                    al.set_markup(
                        f"<span color='{C['overlay0']}' size='{SIZES['mini']['font_pop_event']}'>All Day</span>"
                    )
                    al.set_halign(Gtk.Align.START); meta.append(al)

                if ev.get('source_name') and not ev.get('is_local'):
                    src = Gtk.Label()
                    src.set_markup(
                        f"<span color='{C['overlay0']}' size='{SIZES['mini']['font_pop_event']}'>"
                        f"{ev['source_name']}</span>"
                    )
                    src.set_halign(Gtk.Align.START); meta.append(src)

                ev_row.append(meta); vbox.append(ev_row)
        else:
            empty = Gtk.Label()
            empty.set_markup(f"<span color='{C['overlay0']}'>No events today</span>")
            empty.set_margin_top(4); empty.set_margin_bottom(8)
            vbox.append(empty)

        sep2 = Gtk.Separator()
        sep2.set_margin_top(8); sep2.set_margin_bottom(8)
        vbox.append(sep2)

        btn_row = Gtk.Box(spacing=8)
        add_btn = Gtk.Button(label='+ Task')
        add_btn.add_css_class('pop-add-btn')
        add_btn.connect('clicked', lambda *_: (pop.popdown(), self._show_add_task_dialog(date)))
        btn_row.append(add_btn)

        if day_locals:
            del_btn = Gtk.Button(label='Delete Task')
            del_btn.add_css_class('pop-del-btn')
            del_btn.connect('clicked', lambda *_: (pop.popdown(), self._show_del_task_dialog(date)))
            btn_row.append(del_btn)

        vbox.append(btn_row)
        pop.set_child(vbox)
        pop.popup()

    def _on_pop_closed(self, pop):
        self._active_pop  = None
        self._dialog_open = False

    def _merge_local(self):
        ical = [e for e in self.all_events if not e.get('is_local')]
        self.all_events = sorted(
            ical + self.local_events,
            key=lambda e: (e['date'], e.get('time_24h') or '')
        )
        self._rebuild_agenda()
        self._update_marks()

    def _on_add_task_clicked(self):
        if self._selected_date: self._show_add_task_dialog(self._selected_date)

    def _on_del_task_clicked(self):
        if self._selected_date: self._show_del_task_dialog(self._selected_date)

    def _on_edit_task_clicked(self):
        if self._selected_date: self._show_edit_task_dialog(self._selected_date)

    def _show_add_task_dialog(self, date: datetime.date):
        dlg = Gtk.Dialog(
            title=f'New Task — {date.strftime("%A, %-d %B %Y")}',
            transient_for=self, modal=True, use_header_bar=1,
        )
        dlg.add_css_class('sd-dialog')
        dlg.set_default_size(480, -1)
        dlg.add_button('Cancel', Gtk.ResponseType.CANCEL)
        ok_btn = dlg.add_button('Add', Gtk.ResponseType.OK)
        ok_btn.get_style_context().add_class('suggested-action')

        area = dlg.get_content_area()
        grid = Gtk.Grid(column_spacing=14, row_spacing=12)
        grid.set_margin_start(20); grid.set_margin_end(20)
        grid.set_margin_top(16);   grid.set_margin_bottom(16)

        local_radio = Gtk.CheckButton.new_with_label("Local")
        cloud_radio = Gtk.CheckButton.new_with_label("Cloud (Google Calendar)")
        cloud_radio.set_group(local_radio)
        local_radio.set_active(True)
        rbox = Gtk.Box(spacing=12)
        rbox.append(local_radio); rbox.append(cloud_radio)
        grid.attach(rbox, 0, 0, 2, 1)

        def lbl(text):
            l = Gtk.Label(label=text); l.set_halign(Gtk.Align.END); return l

        grid.attach(lbl('Task *'), 0, 1, 1, 1)
        name_entry = Gtk.Entry()
        name_entry.set_placeholder_text('e.g. Team stand-up')
        name_entry.set_hexpand(True)
        grid.attach(name_entry, 1, 1, 1, 1)

        allday_chk = Gtk.CheckButton(label='All Day')
        allday_chk.set_active(True)
        grid.attach(allday_chk, 1, 2, 1, 1)

        use_12h = self.settings.get('use_12h', False)
        fmt_row = Gtk.Box(spacing=8)
        fmt_24_radio = Gtk.CheckButton.new_with_label('24h')
        fmt_12_radio = Gtk.CheckButton.new_with_label('12h')
        fmt_12_radio.set_group(fmt_24_radio)
        fmt_12_radio.set_active(use_12h)
        fmt_24_radio.set_active(not use_12h)
        fmt_row.append(fmt_24_radio); fmt_row.append(fmt_12_radio)
        grid.attach(lbl('Time Format'), 0, 3, 1, 1)
        grid.attach(fmt_row, 1, 3, 1, 1)

        grid.attach(lbl('Start Time'), 0, 4, 1, 1)
        time_box = Gtk.Box(spacing=6)
        time_entry = Gtk.Entry()
        time_entry.set_sensitive(False); time_entry.set_max_length(5); time_entry.set_width_chars(6)
        ampm_combo = Gtk.DropDown.new_from_strings(['AM', 'PM'])
        ampm_combo.set_sensitive(False)
        ampm_combo.set_visible(use_12h)
        time_box.append(time_entry); time_box.append(ampm_combo)
        grid.attach(time_box, 1, 4, 1, 1)

        grid.attach(lbl('End Time'), 0, 5, 1, 1)
        end_box = Gtk.Box(spacing=6)
        end_entry = Gtk.Entry()
        end_entry.set_sensitive(False); end_entry.set_max_length(5); end_entry.set_width_chars(6)
        end_ampm_combo = Gtk.DropDown.new_from_strings(['AM', 'PM'])
        end_ampm_combo.set_sensitive(False)
        end_ampm_combo.set_visible(use_12h)
        end_box.append(end_entry); end_box.append(end_ampm_combo)
        grid.attach(end_box, 1, 5, 1, 1)

        def _update_placeholders():
            if fmt_12_radio.get_active():
                time_entry.set_placeholder_text('hh:mm')
                end_entry.set_placeholder_text('hh:mm')
                ampm_combo.set_visible(True)
                end_ampm_combo.set_visible(True)
            else:
                time_entry.set_placeholder_text('HH:MM')
                end_entry.set_placeholder_text('HH:MM')
                ampm_combo.set_visible(False)
                end_ampm_combo.set_visible(False)

        fmt_12_radio.connect('toggled', lambda *_: _update_placeholders())
        fmt_24_radio.connect('toggled', lambda *_: _update_placeholders())
        _update_placeholders()

        grid.attach(lbl('Notes'), 0, 6, 1, 1)
        notes_buf  = Gtk.TextBuffer()
        notes_view = Gtk.TextView(buffer=notes_buf)
        notes_view.set_wrap_mode(Gtk.WrapMode.WORD); notes_view.set_size_request(-1, 70)
        notes_scroll = Gtk.ScrolledWindow()
        notes_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        notes_scroll.set_child(notes_view)
        grid.attach(notes_scroll, 1, 6, 1, 1)

        remind_box  = Gtk.Box(spacing=8)
        remind_chk  = Gtk.CheckButton(label='Remind me'); remind_chk.set_active(True); remind_chk.set_sensitive(False)
        remind_spin2= Gtk.SpinButton(); remind_spin2.set_range(1,120); remind_spin2.set_increments(5,15)
        remind_spin2.set_value(self.settings.get('notification_minutes', 15)); remind_spin2.set_size_request(65,-1); remind_spin2.set_sensitive(False)
        remind_unit = Gtk.Label(label='min before'); remind_unit.set_sensitive(False)
        remind_box.append(remind_chk); remind_box.append(remind_spin2); remind_box.append(remind_unit)
        grid.attach(remind_box, 1, 7, 1, 1)

        silent_chk = Gtk.CheckButton(label='Silent  (no desktop notification)')
        grid.attach(silent_chk, 1, 8, 1, 1)

        def _on_allday_toggled(b):
            not_allday = not b.get_active()
            time_entry.set_sensitive(not_allday)
            end_entry.set_sensitive(not_allday)
            ampm_combo.set_sensitive(not_allday)
            end_ampm_combo.set_sensitive(not_allday)
            remind_chk.set_sensitive(not_allday)
            remind_spin2.set_sensitive(not_allday)
            remind_unit.set_sensitive(not_allday)

        allday_chk.connect('toggled', _on_allday_toggled)

        area.append(grid)
        self._dialog_open = True

        def _parse_time_input(entry, ampm_cb, is_12h):
            raw = entry.get_text().strip()
            if not raw:
                return None
            h, _, m = raw.partition(':')
            h, m = int(h), int(m) if m else 0
            if is_12h:
                period = ['AM', 'PM'][ampm_cb.get_selected()]
                if period == 'PM' and h != 12: h += 12
                if period == 'AM' and h == 12: h = 0
            return (h, m)

        def on_response(dialog, resp):
            if resp == Gtk.ResponseType.OK:
                task_name = name_entry.get_text().strip()
                if task_name:
                    is_12h = fmt_12_radio.get_active()
                    self.settings['use_12h'] = is_12h
                    save_settings(self.settings)

                    if cloud_radio.get_active():
                        base = "https://calendar.google.com/calendar/u/0/r/eventedit"
                        if allday_chk.get_active():
                            ds = f"{date.year:04d}{date.month:02d}{date.day:02d}"
                            url = f"{base}?dates={ds}/{ds}&text={quote(task_name)}"
                        else:
                            try:
                                hm = _parse_time_input(time_entry, ampm_combo, is_12h)
                                s  = datetime.datetime(date.year, date.month, date.day, *hm)
                                hm_e = _parse_time_input(end_entry, end_ampm_combo, is_12h)
                                e  = (datetime.datetime(date.year, date.month, date.day, *hm_e)
                                      if hm_e else s + datetime.timedelta(hours=1))
                                url = (f"{base}?dates={s.strftime('%Y%m%dT%H%M%S')}/"
                                       f"{e.strftime('%Y%m%dT%H%M%S')}&text={quote(task_name)}")
                            except Exception:
                                ds = f"{date.year:04d}{date.month:02d}{date.day:02d}"
                                url = f"{base}?dates={ds}/{ds}&text={quote(task_name)}"
                        note = notes_buf.get_text(notes_buf.get_start_iter(), notes_buf.get_end_iter(), False).strip()
                        if note: url += f"&details={quote(note)}"
                        webbrowser.open(url)
                    else:
                        parts = [date.strftime('%Y-%m-%d')]
                        end_token = ''
                        if not allday_chk.get_active():
                            try:
                                hm = _parse_time_input(time_entry, ampm_combo, is_12h)
                                if hm:
                                    t24 = f"{hm[0]:02d}:{hm[1]:02d}"
                                    parts.append(t24)
                                    hm_e = _parse_time_input(end_entry, end_ampm_combo, is_12h)
                                    if hm_e:
                                        end_token = f" || [end={hm_e[0]:02d}:{hm_e[1]:02d}]"
                            except Exception:
                                pass
                        note = notes_buf.get_text(notes_buf.get_start_iter(), notes_buf.get_end_iter(), False).strip()
                        extra = ''
                        if note: extra += f' || {note}'
                        if remind_chk.get_active() and not allday_chk.get_active():
                            extra += f' || [remind={int(remind_spin2.get_value())}]'
                        if silent_chk.get_active():
                            extra += ' || [silent]'
                        extra += end_token
                        parts.append(task_name + extra)
                        os.makedirs(CONFIG_DIR, exist_ok=True)
                        with open(self.local_file, 'a', encoding='utf-8') as fh:
                            fh.write(' '.join(parts) + '\n')
                        self.local_events = parse_local_tasks(self.local_file)
                        self._merge_local()
                        if self.view_mode == 'full': self._show_day(date)
                        elif self.view_mode == 'compact': self._update_compact_day(date)
            dialog.destroy()
            self._dialog_open = False

        dlg.connect('response', on_response)
        dlg.present()

    def _show_edit_task_dialog(self, date: datetime.date):
        day_locals = [e for e in self.local_events if e['date'] == date]
        if not day_locals: return

        dlg = Gtk.Dialog(
            title=f'Edit Tasks — {date.strftime("%-d %B %Y")}',
            transient_for=self, modal=True, use_header_bar=1,
        )
        dlg.add_css_class('sd-dialog')
        dlg.set_default_size(500, -1)
        dlg.add_button('Cancel', Gtk.ResponseType.CANCEL)
        save_btn = dlg.add_button('Save', Gtk.ResponseType.OK)
        save_btn.get_style_context().add_class('suggested-action')

        area = dlg.get_content_area()
        area.set_spacing(0)

        selected_ev = [day_locals[0]]

        is_12h = self.settings.get('use_12h', False)

        def build_edit_fields(ev):
            grid = Gtk.Grid(column_spacing=14, row_spacing=12)
            grid.set_margin_start(20); grid.set_margin_end(20)
            grid.set_margin_top(16);   grid.set_margin_bottom(16)

            def lbl(text):
                l = Gtk.Label(label=text); l.set_halign(Gtk.Align.END); return l

            grid.attach(lbl('Task *'), 0, 0, 1, 1)
            name_e = Gtk.Entry()
            name_e.set_text(ev.get('summary', ''))
            name_e.set_hexpand(True)
            grid.attach(name_e, 1, 0, 1, 1)

            allday_chk = Gtk.CheckButton(label='All Day')
            allday_chk.set_active(bool(ev.get('allday', True)))
            grid.attach(allday_chk, 1, 1, 1, 1)

            fmt_row = Gtk.Box(spacing=8)
            fmt_24_r = Gtk.CheckButton.new_with_label('24h')
            fmt_12_r = Gtk.CheckButton.new_with_label('12h')
            fmt_12_r.set_group(fmt_24_r)
            fmt_12_r.set_active(is_12h)
            fmt_24_r.set_active(not is_12h)
            fmt_row.append(fmt_24_r); fmt_row.append(fmt_12_r)
            grid.attach(lbl('Time Format'), 0, 2, 1, 1)
            grid.attach(fmt_row, 1, 2, 1, 1)

            existing_t24 = ev.get('time_24h') or ''
            existing_end = ev.get('end_time_24h') or ''
            _start_h, _start_m, _start_ampm = 0, 0, 0
            _end_h, _end_m, _end_ampm = 0, 0, 0
            if existing_t24:
                try:
                    _dt = datetime.datetime.strptime(existing_t24, '%H:%M')
                    _start_h, _start_m = _dt.hour, _dt.minute
                    _start_ampm = 1 if _dt.hour >= 12 else 0
                except Exception: pass
            if existing_end:
                try:
                    _dt2 = datetime.datetime.strptime(existing_end, '%H:%M')
                    _end_h, _end_m = _dt2.hour, _dt2.minute
                    _end_ampm = 1 if _dt2.hour >= 12 else 0
                except Exception: pass

            def _24_to_12(h): return (h % 12) or 12

            grid.attach(lbl('Start Time'), 0, 3, 1, 1)
            time_box = Gtk.Box(spacing=6)
            time_e = Gtk.Entry(); time_e.set_max_length(5); time_e.set_width_chars(6)
            time_e.set_sensitive(not ev.get('allday', True))
            ampm_cb = Gtk.DropDown.new_from_strings(['AM', 'PM'])
            ampm_cb.set_selected(_start_ampm)
            ampm_cb.set_sensitive(not ev.get('allday', True))
            ampm_cb.set_visible(is_12h)
            time_box.append(time_e); time_box.append(ampm_cb)
            grid.attach(time_box, 1, 3, 1, 1)

            grid.attach(lbl('End Time'), 0, 4, 1, 1)
            end_box = Gtk.Box(spacing=6)
            end_e = Gtk.Entry(); end_e.set_max_length(5); end_e.set_width_chars(6)
            end_e.set_sensitive(not ev.get('allday', True))
            end_ampm_cb = Gtk.DropDown.new_from_strings(['AM', 'PM'])
            end_ampm_cb.set_selected(_end_ampm)
            end_ampm_cb.set_sensitive(not ev.get('allday', True))
            end_ampm_cb.set_visible(is_12h)
            end_box.append(end_e); end_box.append(end_ampm_cb)
            grid.attach(end_box, 1, 4, 1, 1)

            def _set_time_texts():
                if fmt_12_r.get_active():
                    time_e.set_placeholder_text('hh:mm')
                    end_e.set_placeholder_text('hh:mm')
                    ampm_cb.set_visible(True)
                    end_ampm_cb.set_visible(True)
                    if existing_t24:
                        time_e.set_text(f"{_24_to_12(_start_h):02d}:{_start_m:02d}")
                    if existing_end:
                        end_e.set_text(f"{_24_to_12(_end_h):02d}:{_end_m:02d}")
                else:
                    time_e.set_placeholder_text('HH:MM')
                    end_e.set_placeholder_text('HH:MM')
                    ampm_cb.set_visible(False)
                    end_ampm_cb.set_visible(False)
                    if existing_t24:
                        time_e.set_text(f"{_start_h:02d}:{_start_m:02d}")
                    if existing_end:
                        end_e.set_text(f"{_end_h:02d}:{_end_m:02d}")

            fmt_12_r.connect('toggled', lambda *_: _set_time_texts())
            fmt_24_r.connect('toggled', lambda *_: _set_time_texts())
            _set_time_texts()

            grid.attach(lbl('Notes'), 0, 5, 1, 1)
            notes_buf  = Gtk.TextBuffer()
            notes_buf.set_text(ev.get('note') or '')
            notes_view = Gtk.TextView(buffer=notes_buf)
            notes_view.set_wrap_mode(Gtk.WrapMode.WORD); notes_view.set_size_request(-1, 60)
            notes_sc = Gtk.ScrolledWindow()
            notes_sc.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
            notes_sc.set_child(notes_view)
            grid.attach(notes_sc, 1, 5, 1, 1)

            remind_mins = ev.get('reminder_minutes') or self.settings.get('notification_minutes', 15)
            remind_box2 = Gtk.Box(spacing=8)
            remind_chk2 = Gtk.CheckButton(label='Remind me')
            remind_chk2.set_active(ev.get('reminder_minutes') is not None)
            remind_chk2.set_sensitive(not ev.get('allday', True))
            remind_sp = Gtk.SpinButton(); remind_sp.set_range(1,120); remind_sp.set_increments(5,15)
            remind_sp.set_value(remind_mins); remind_sp.set_size_request(65,-1)
            remind_sp.set_sensitive(not ev.get('allday', True))
            remind_unit2 = Gtk.Label(label='min before')
            remind_unit2.set_sensitive(not ev.get('allday', True))
            remind_box2.append(remind_chk2); remind_box2.append(remind_sp); remind_box2.append(remind_unit2)
            grid.attach(remind_box2, 1, 6, 1, 1)

            silent_chk2 = Gtk.CheckButton(label='Silent  (no desktop notification)')
            silent_chk2.set_active(ev.get('silent', False))
            grid.attach(silent_chk2, 1, 7, 1, 1)

            def _on_allday(b):
                not_allday = not b.get_active()
                for w in (time_e, end_e, ampm_cb, end_ampm_cb,
                          remind_chk2, remind_sp, remind_unit2):
                    w.set_sensitive(not_allday)

            allday_chk.connect('toggled', _on_allday)

            return grid, name_e, allday_chk, time_e, ampm_cb, end_e, end_ampm_cb, \
                   notes_buf, remind_chk2, remind_sp, silent_chk2, fmt_12_r

        picker_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        picker_box.set_margin_start(20); picker_box.set_margin_end(20)
        picker_box.set_margin_top(12); picker_box.set_margin_bottom(4)
        field_container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        current_fields  = [None]

        def _load_ev(ev):
            selected_ev[0] = ev
            while ch := field_container.get_first_child():
                field_container.remove(ch)
            fields = build_edit_fields(ev)
            current_fields[0] = fields
            field_container.append(fields[0])

        if len(day_locals) > 1:
            pick_lbl = Gtk.Label(label='Select task to edit:')
            pick_lbl.set_halign(Gtk.Align.START)
            picker_box.append(pick_lbl)
            for ev in day_locals:
                rb = Gtk.CheckButton(label=ev['summary'])
                rb.set_active(ev is day_locals[0])
                if ev is not day_locals[0]:
                    rb.set_group(picker_box.get_first_child().get_next_sibling()
                                 if picker_box.get_first_child() else rb)
                rb.connect('toggled', lambda b, e=ev: _load_ev(e) if b.get_active() else None)
                picker_box.append(rb)
            area.append(picker_box)

        _load_ev(day_locals[0])
        area.append(field_container)
        self._dialog_open = True

        def _parse_t(entry, cb, is12):
            raw = entry.get_text().strip()
            if not raw: return None
            h, _, m = raw.partition(':')
            h, m = int(h), int(m) if m else 0
            if is12:
                period = ['AM', 'PM'][cb.get_selected()]
                if period == 'PM' and h != 12: h += 12
                if period == 'AM' and h == 12: h = 0
            return (h, m)

        def on_response(dialog, resp):
            if resp == Gtk.ResponseType.OK:
                fields = current_fields[0]
                if fields is None:
                    dialog.destroy(); self._dialog_open = False; return
                (_, name_e, allday_chk, time_e, ampm_cb, end_e, end_ampm_cb,
                 notes_buf, remind_chk2, remind_sp, silent_chk2, fmt_12_r) = fields

                ev       = selected_ev[0]
                new_name = name_e.get_text().strip()
                if not new_name:
                    dialog.destroy(); self._dialog_open = False; return

                is_12h = fmt_12_r.get_active()
                self.settings['use_12h'] = is_12h
                save_settings(self.settings)

                parts = [date.strftime('%Y-%m-%d')]
                end_token = ''
                if not allday_chk.get_active():
                    try:
                        hm = _parse_t(time_e, ampm_cb, is_12h)
                        if hm:
                            parts.append(f"{hm[0]:02d}:{hm[1]:02d}")
                            hm_e = _parse_t(end_e, end_ampm_cb, is_12h)
                            if hm_e:
                                end_token = f" || [end={hm_e[0]:02d}:{hm_e[1]:02d}]"
                    except Exception:
                        pass

                note = notes_buf.get_text(notes_buf.get_start_iter(), notes_buf.get_end_iter(), False).strip()
                extra = ''
                if note: extra += f' || {note}'
                if remind_chk2.get_active() and not allday_chk.get_active():
                    extra += f' || [remind={int(remind_sp.get_value())}]'
                if silent_chk2.get_active():
                    extra += ' || [silent]'
                extra += end_token

                new_raw = ' '.join(parts) + ' ' + new_name + extra + '\n'

                try:
                    with open(self.local_file, 'r', encoding='utf-8') as fh:
                        lines = fh.readlines()
                    new_lines = [new_raw if l == ev['raw_line'] else l for l in lines]
                    with open(self.local_file, 'w', encoding='utf-8') as fh:
                        fh.writelines(new_lines)
                except Exception:
                    pass

                self.local_events = parse_local_tasks(self.local_file)
                self._merge_local()
                if self.view_mode == 'full': self._show_day(date)
                elif self.view_mode == 'compact': self._update_compact_day(date)

            dialog.destroy()
            self._dialog_open = False

        dlg.connect('response', on_response)
        dlg.present()

    def _show_del_task_dialog(self, date: datetime.date):
        day_locals = [e for e in self.local_events if e['date'] == date]
        if not day_locals: return

        dlg = Gtk.Dialog(
            title=f'Delete Tasks — {date.strftime("%-d %B %Y")}',
            transient_for=self, modal=True, use_header_bar=1,
        )
        dlg.add_css_class('sd-dialog')
        dlg.set_default_size(480, 350)
        dlg.add_button('Cancel', Gtk.ResponseType.CANCEL)
        del_btn = dlg.add_button('Delete Selected', Gtk.ResponseType.OK)
        del_btn.get_style_context().add_class('destructive-action')
        del_btn.set_sensitive(False)

        area = dlg.get_content_area()
        area.set_spacing(12); area.set_margin_start(16); area.set_margin_end(16)
        area.set_margin_top(14); area.set_margin_bottom(14)

        lbl = Gtk.Label(label="Select tasks to delete:")
        lbl.set_halign(Gtk.Align.START)
        area.append(lbl)

        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_min_content_height(200)
        listbox = Gtk.ListBox(); listbox.set_selection_mode(Gtk.SelectionMode.NONE)
        scroll.set_child(listbox)

        checkboxes = []
        for ev in day_locals:
            row = Gtk.ListBoxRow(); row._ev = ev; row.set_selectable(False)
            hbox = Gtk.Box(spacing=8)
            hbox.set_margin_start(12); hbox.set_margin_end(12)
            hbox.set_margin_top(8);    hbox.set_margin_bottom(8)

            chk = Gtk.CheckButton(); chk.set_valign(Gtk.Align.CENTER)
            chk.connect('toggled', self._on_task_selected, del_btn)
            checkboxes.append((chk, ev))

            dot = Gtk.Label()
            dot.set_markup(f"<span color='{C['blue']}' size='9000'>●</span>")
            dot.set_valign(Gtk.Align.CENTER)

            vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            title_lbl = Gtk.Label()
            title_lbl.set_markup(f"<span weight='bold' color='{C['text']}'>{esc(ev['summary'])}</span>")
            title_lbl.set_halign(Gtk.Align.START); vbox.append(title_lbl)

            if ev.get('time'):
                time_lbl = Gtk.Label()
                time_lbl.set_markup(f"<span color='{C['overlay1']}' size='small'>{ev['time']} {ev['ampm']}</span>")
                time_lbl.set_halign(Gtk.Align.START); vbox.append(time_lbl)

            hbox.append(chk); hbox.append(dot); hbox.append(vbox)
            row.set_child(hbox); listbox.append(row)

        area.append(scroll)
        dlg._task_checkboxes = checkboxes
        self._dialog_open = True

        def on_response(dialog, resp):
            if resp == Gtk.ResponseType.OK:
                selected_lines = [ev['raw_line'] for chk, ev in checkboxes if chk.get_active()]
                if selected_lines:
                    try:
                        with open(self.local_file, 'r', encoding='utf-8') as fh:
                            lines = fh.readlines()
                        new_lines = [l for l in lines if l not in selected_lines]
                        with open(self.local_file, 'w', encoding='utf-8') as fh:
                            fh.writelines(new_lines)
                    except Exception:
                        pass
                    self.local_events = parse_local_tasks(self.local_file)
                    self._merge_local()
                    if self.view_mode == 'full': self._show_day(date)
                    elif self.view_mode == 'compact': self._update_compact_day(date)
            dialog.destroy()
            self._dialog_open = False

        dlg.connect('response', on_response)
        dlg.present()

    def _on_task_selected(self, button, del_btn):
        dialog = button.get_root()
        if hasattr(dialog, '_task_checkboxes'):
            any_selected = any(cb.get_active() for cb, _ in dialog._task_checkboxes)
            del_btn.set_sensitive(any_selected)

    def _on_key(self, ctrl, keyval, keycode, state):
        if keyval == Gdk.KEY_Escape:
            self._quit()
        elif keyval in (Gdk.KEY_t, Gdk.KEY_T):
            self._goto_today()
        elif keyval in (Gdk.KEY_c, Gdk.KEY_C):
            if not self.args.calendar and not self.args.compact_cal:
                self._toggle_view()
        elif keyval == Gdk.KEY_F5:
            self._fetch_all()

    def _update_clock(self):
        now = datetime.datetime.now()
        t_str = now.strftime('%I:%M')
        s_str = now.strftime('%S')
        p_str = now.strftime('%p')

        if self.view_mode == 'compact':
            self.clock_lbl.set_markup(
                f"<span color='{C['blue']}' weight='bold' size='11000'>{t_str}</span>"
                f"<span color='{C['overlay0']}' size='8000'>:{s_str}</span>"
                f"<span color='{C['subtext0']}' size='9000'> {p_str}</span>"
            )
        else:
            d_str = now.strftime('%a %-d %b')
            self.clock_lbl.set_markup(
                f"<span color='{C['overlay1']}' size='9500'>{d_str}  </span>"
                f"<span color='{C['blue']}' weight='bold' size='11000'>{t_str}</span>"
                f"<span color='{C['overlay0']}' size='8000'>:{s_str}</span>"
                f"<span color='{C['subtext0']}' size='9000'> {p_str}</span>"
            )
        return True

    def _quit(self):
        self.destroy()

    def _apply_css(self):
        font_name = self._font_name or "sans-serif"
        op        = C.get('opacity', 0.95)
        op_s      = max(0.0, op - 0.06)
        hl_bg     = hex_to_rgba(C.get('highlight_bg', C['blue']),
                                C.get('highlight_alpha', 0.16) + 0.05)

        sz_mini    = SIZES['mini']
        sz_compact = SIZES['compact']
        sz_full    = SIZES['full']

        css = f"""
        * {{
            font-family: "{font_name}", "Noto Sans", "Segoe UI", "Nerd Font", "FontAwesome";
        }}
        button {{
            background: none; border: none; box-shadow: none; text-shadow: none;
            min-width: 0; min-height: 0; padding: 0; margin: 0;
        }}
        label {{ padding: 0; margin: 0; }}

        window {{ background-color: transparent; }}
        window > decoration {{ box-shadow: none; border-radius: 0; }}

        #hdr {{
            background-color: {hex_to_rgba(C['mantle'], op)};
            border-radius: 12px 12px 0 0;
            min-height: 48px; padding: 0 4px;
            border-bottom: 1px solid {hex_to_rgba(C['surface0'], 0.4)};
        }}
        #hdr_clock {{ font-family: monospace; font-size: 1.1em; }}
        #badge {{ font-weight: bold; margin-left: 6px; }}

        #close_btn, #hdr_btn {{
            background: transparent; border: none; box-shadow: none;
            color: {C['overlay1']}; font-size: 12pt;
            padding: 4px 8px; border-radius: 8px;
            min-width: 0; min-height: 0;
            transition: background-color 120ms ease, color 120ms ease;
        }}
        #hdr_btn:hover   {{ background-color: {hex_to_rgba(C['surface0'], 0.9)}; color: {C['text']}; }}
        #close_btn:hover {{ background-color: {hex_to_rgba(C['red'],     0.85)}; color: {C['crust']}; }}
        .notif-off {{ color: {C['overlay0']}; opacity: 0.55; }}

        #root {{
            background-color: {hex_to_rgba(C['crust'], op)};
            border-radius: 0 0 12px 12px;
            border: 1px solid {hex_to_rgba(C['surface1'], 0.40)};
            border-top: none;
            box-shadow: 0 14px 40px rgba(0,0,0,0.60), 0 2px 8px rgba(0,0,0,0.30);
        }}

        .calendar-only #root {{
            border-radius: 14px;
            border: 1px solid {hex_to_rgba(C['surface1'], 0.55)};
            border-top: 1px solid {hex_to_rgba(C['surface1'], 0.55)};
            box-shadow: 0 12px 36px rgba(0,0,0,0.65), 0 2px 8px rgba(0,0,0,0.30);
            background-color: {hex_to_rgba(C['base'], op)};
        }}
        .calendar-only .titlebar,
        .calendar-only windowhandle {{
            min-height: 0; max-height: 0; padding: 0; margin: 0;
            background: transparent; border: none; box-shadow: none;
            opacity: 0;
        }}

        #hline_top  {{ background-color: {hex_to_rgba(C['surface0'], 0.5)}; min-height: 1px; }}
        #agenda_sep, #detail_sep, #compact_sep {{ background-color: {hex_to_rgba(C['surface0'], 0.5)}; }}
        #compact_vsep {{ background-color: {hex_to_rgba(C['surface1'], 0.4)}; }}

        #agenda_pane {{ background-color: {hex_to_rgba(C['base'], op_s)}; border-radius: 0 0 0 12px; }}
        #agenda_list {{ background-color: transparent; }}
        #agenda_list > row {{
            background-color: transparent; border-radius: 10px; margin: 3px 12px;
            border: 1px solid transparent;
            transition: background-color 120ms ease, border-color 120ms ease;
        }}
        #agenda_list > row:hover {{ background-color: {hex_to_rgba(C['surface0'], 0.6)}; }}
        #agenda_list > row.selected-agenda-row {{
            background-color: {hl_bg};
            border: 1px solid {hex_to_rgba(C['highlight_border'], 0.6)};
        }}

        #task_bot_box {{ background-color: {hex_to_rgba(C['base'], op_s * 0.6)}; border-radius: 0 0 12px 0; }}

        #compact_outer {{ background-color: transparent; }}
        #compact_left  {{
            background-color: {hex_to_rgba(C['base'], op_s)};
            border-radius: 0 0 0 12px;
        }}
        #compact_right {{ background-color: transparent; }}
        #compact_event_list {{ background-color: transparent; }}
        #compact_event_list > row {{
            background-color: transparent; border-radius: 8px; margin: 2px 8px;
            transition: background-color 100ms ease;
        }}
        #compact_event_list > row:hover {{ background-color: {hex_to_rgba(C['surface0'], 0.5)}; }}

        #mini_footer {{
            color: {hex_to_rgba(C['overlay0'], 0.7)};
            border-top: 1px solid {hex_to_rgba(C['surface1'], 0.3)};
            padding-top: 5px;
            margin-top: 2px;
        }}

        .cal-month-lbl {{
            color: {C['lavender']};
            letter-spacing: 0.3px;
        }}
        .cal-nav-sep   {{ color: {hex_to_rgba(C['overlay0'], 0.5)}; font-size: 8pt; }}
        .cal-nav-btn {{
            background: transparent; border: none; box-shadow: none;
            color: {C['overlay1']}; font-size: 10pt; font-weight: bold;
            padding: 0px 3px; border-radius: 5px; min-width: 0; min-height: 0;
            transition: background-color 100ms ease, color 100ms ease;
        }}
        .cal-nav-btn:hover {{ background-color: {hex_to_rgba(C['surface0'], 0.85)}; color: {C['text']}; }}

        .cal-dow {{
            color: {hex_to_rgba(C['overlay0'], 0.9)};
            font-weight: bold;
            margin-bottom: 0px;
            letter-spacing: 0px;
        }}
        .mini-cal-dow    {{ font-size: {sz_mini['font_dow']}; }}
        .compact-cal-dow {{ font-size: {sz_compact['font_dow']}; }}
        .full-cal-dow    {{ font-size: {sz_full['font_dow']}; }}

        .cal-day-btn {{
            background: transparent; border: none; box-shadow: none;
            border-radius: 7px; padding: 0;
            transition: background-color 90ms ease;
            min-width: 0; min-height: 0;
        }}
        .cal-day-btn:hover {{ background-color: {hex_to_rgba(C['surface1'], 0.75)}; }}

        .mini-cal-day-btn {{
            border-radius: 14px;
        }}

        .day-num-lbl {{ color: {C['subtext1']}; font-weight: 500; }}
        .mini-day-num-lbl    {{ font-size: {sz_mini['font_day']}; }}
        .compact-day-num-lbl {{ font-size: {sz_compact['font_day']}; }}
        .full-day-num-lbl    {{ font-size: {sz_full['font_day']}; }}

        .day-dot-lbl {{ line-height: 1; }}
        .mini-day-dot-lbl    {{ font-size: {sz_mini['font_dot']}; opacity: 0.8; }}
        .compact-day-dot-lbl {{ font-size: {sz_compact['font_dot']}; }}
        .full-day-dot-lbl    {{ font-size: {sz_full['font_dot']}; }}

        .cal-day-btn.empty-day  {{ background: transparent; opacity: 0; pointer-events: none; }}

        .cal-day-btn.has-holiday .day-num-lbl {{
            color: {C['green']}; font-weight: 700;
        }}
        .cal-day-btn.has-events .day-num-lbl {{
            color: {C['event_mark_color']}; font-weight: 900;
        }}
        .cal-day-btn.has-local-events .day-num-lbl {{
            color: {C['blue']}; font-weight: 900;
        }}
        .cal-day-btn.weekend-day:not(.has-events):not(.has-holiday):not(.has-local-events) .day-num-lbl {{
            color: {hex_to_rgba(C['overlay2'], 0.65)};
        }}

        .cal-day-btn.selected-day {{
            background-color: {C['selected_day_bg']};
            border-radius: 7px;
        }}
        .cal-day-btn.selected-day .day-num-lbl {{
            color: {C['selected_day_fg']}; font-weight: bold;
        }}
        .cal-day-btn.selected-day .day-dot-lbl {{ opacity: 0.6; }}

        .cal-day-btn.today-day:not(.selected-day) {{
            background-color: {hex_to_rgba(C['lavender'], 0.12)};
            border: 1px solid {hex_to_rgba(C['lavender'], 0.5)};
        }}
        .cal-day-btn.today-day:not(.selected-day) .day-num-lbl {{
            color: {C['lavender']}; font-weight: bold;
        }}

        .event-pop > contents {{
            background-color: {hex_to_rgba(C['base'], 0.99)};
            border: 1px solid {hex_to_rgba(C['surface1'], 0.55)};
            border-radius: 14px; padding: 0;
            box-shadow: 0 10px 30px rgba(0,0,0,0.55), 0 2px 6px rgba(0,0,0,0.25);
        }}
        .pop-add-btn {{
            background-color: {hex_to_rgba(C['blue'], 0.14)}; color: {C['blue']};
            border: 1px solid {hex_to_rgba(C['blue'], 0.30)};
            border-radius: 8px; padding: 5px 12px;
            font-size: 9.5pt; font-weight: bold;
            transition: background-color 110ms ease;
        }}
        .pop-add-btn:hover {{ background-color: {hex_to_rgba(C['blue'], 0.28)}; }}
        .pop-del-btn {{
            background-color: {hex_to_rgba(C['red'], 0.10)}; color: {C['red']};
            border: 1px solid {hex_to_rgba(C['red'], 0.22)};
            border-radius: 8px; padding: 5px 12px; font-size: 9.5pt;
            transition: background-color 110ms ease;
        }}
        .pop-del-btn:hover {{ background-color: {hex_to_rgba(C['red'], 0.24)}; }}

        #task_list {{ background-color: transparent; }}
        #task_row {{
            background-color: {hex_to_rgba(C['surface0'], 0.4)};
            border-radius: 10px; margin: 0 0 10px 0;
            border-left: 3px solid {C['surface2']};
            transition: background-color 120ms ease, border-left-color 120ms ease;
        }}
        #task_row:hover {{
            background-color: {hex_to_rgba(C['surface0'], 0.8)};
            border-left: 3px solid {C['blue']};
        }}
        #add_task_btn, #del_task_btn, #edit_task_btn {{
            background-color: {hex_to_rgba(C['surface0'], 0.5)};
            border: 1px solid {hex_to_rgba(C['surface1'], 0.6)};
            border-radius: 8px; padding: 6px 14px; font-weight: bold;
            transition: background-color 120ms ease;
        }}
        #add_task_btn  {{ color: {C['green']}; }}
        #del_task_btn  {{ color: {C['red']};   }}
        #edit_task_btn {{ color: {C['peach']}; }}
        #add_task_btn:hover  {{ background-color: {hex_to_rgba(C['green'], 0.2)}; }}
        #del_task_btn:hover  {{ background-color: {hex_to_rgba(C['red'],   0.2)}; }}
        #edit_task_btn:hover {{ background-color: {hex_to_rgba(C['peach'], 0.2)}; }}

        #theme_opt_btn {{
            background: transparent; border: none; box-shadow: none;
            border-radius: 8px; padding: 6px 10px; color: {C['text']}; min-width: 0;
            transition: background-color 120ms ease;
        }}
        #theme_opt_btn:hover {{ background-color: {hex_to_rgba(C['surface0'], 0.9)}; }}
        #theme_opt_btn.active-theme {{
            background-color: {hl_bg};
            border-left: 3px solid {C['highlight_border']};
        }}

        .sd-dialog {{ background-color: {hex_to_rgba(C['base'], 0.99)}; color: {C['text']}; }}
        .sd-dialog label {{ color: {C['text']}; }}
        .sd-dialog entry {{
            background-color: {hex_to_rgba(C['surface0'], 0.9)};
            color: {C['text']}; border-radius: 6px;
            border: 1px solid {hex_to_rgba(C['surface1'], 0.6)};
        }}
        .sd-dialog spinbutton {{ background-color: {hex_to_rgba(C['surface0'], 0.9)}; color: {C['text']}; border-radius: 6px; }}
        .sd-dialog textview   {{ background-color: {hex_to_rgba(C['surface0'], 0.7)}; color: {C['text']}; border-radius: 6px; }}
        .sd-dialog textview text {{ background-color: transparent; color: {C['text']}; }}
        """.encode('utf-8')

        provider = Gtk.CssProvider()
        provider.load_from_data(css)
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_USER
        )

class SimpleCalApp(Gtk.Application):
    def __init__(self, args):
        super().__init__(
            application_id='com.github.simplecal.v15',
            flags=Gio.ApplicationFlags.NON_UNIQUE,
        )
        self.args = args
        self._win = None

    def do_activate(self):
        if self._win is None:
            self._win = SimpleCalWindow(self, self.args)
        self._win.present()

if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='SimpleCal v15 — Calendar + Notification Daemon',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Modes:
  (default)  Full calendar + agenda + tasks
  -c         Mini calendar widget only (no header, locked position)
  -C         Compact calendar with event sidebar
  -d         Background notification daemon (add to XFCE Autostart)

Geometry (CLI flags always override SIZES and saved settings):
  Full    : -w / -H / -x / -y
  Mini    : --mini-width / --mini-height / --mini-x / --mini-y
  Compact : --compact-width / --compact-height / --compact-x / --compact-y
  Panes   : --agenda-width  --cal-height

Daemon usage:
  python3 simplecal.py --daemon          # start in background
  python3 simplecal.py --daemon -t tokyo # with theme override
  kill $(cat ~/.config/simplecal/daemon.pid)  # stop

  The daemon is auto-started when you open the calendar.
  It shows a system tray icon in XFCE notification area.

XFCE Autostart (notifications always-on even after reboot):
  python3 simplecal.py --install-autostart
  (or manually add to XFCE Session & Startup → Application Autostart)
        """,
    )

    parser.add_argument('-c', '--calendar',     action='store_true',
                        help='Mini calendar only (no header, popup)')
    parser.add_argument('-C', '--compact-cal',  action='store_true',
                        help='Compact calendar + event sidebar')
    parser.add_argument('-d', '--daemon',       action='store_true',
                        help='Start background notification daemon')
    parser.add_argument('--install-autostart', action='store_true',
                        help='Install XFCE autostart entry for notification daemon')

    parser.add_argument('-l', '--local',        type=str,  default=None)
    parser.add_argument('-t', '--theme',        type=str,  default=None,
                        choices=list(THEMES.keys()))
    parser.add_argument('--font-name',          type=str,  default=None)
    parser.add_argument('-m', '--maximized',    action='store_true')

    parser.add_argument('-w', '--width',  type=int, default=None)
    parser.add_argument('-H', '--height', type=int, default=None)
    parser.add_argument('-x', '--pos-x',  type=int, default=None, dest='pos_x')
    parser.add_argument('-y', '--pos-y',  type=int, default=None, dest='pos_y')

    parser.add_argument('--mini-width',   type=int, default=None)
    parser.add_argument('--mini-height',  type=int, default=None)
    parser.add_argument('--mini-x',       type=int, default=None)
    parser.add_argument('--mini-y',       type=int, default=None)

    parser.add_argument('--compact-width',  type=int, default=None)
    parser.add_argument('--compact-height', type=int, default=None)
    parser.add_argument('--compact-x',      type=int, default=None)
    parser.add_argument('--compact-y',      type=int, default=None)

    parser.add_argument('--agenda-width', type=int, default=None)
    parser.add_argument('--cal-height',   type=int, default=None)

    args = parser.parse_args()

    if args.calendar and args.compact_cal:
        parser.error("-c and -C are mutually exclusive")
    if args.daemon and (args.calendar or args.compact_cal):
        parser.error("--daemon cannot be combined with -c / -C")

    if args.install_autostart:
        path = install_xfce_autostart()
        if path:
            print(f"[SimpleCal] Autostart entry installed: {path}")
            print("  SimpleCal daemon will now start automatically on XFCE login.")
        else:
            print("[SimpleCal] Failed to install autostart entry.")
        sys.exit(0)

    if args.theme:
        CURRENT_THEME = args.theme
    C = get_theme(CURRENT_THEME)

    if args.daemon:
        existing = _check_daemon_running()
        if existing:
            print(f"[SimpleCal daemon] Already running as PID {existing}")
            sys.exit(0)

        if os.fork() > 0:
            sys.exit(0)

        os.setsid()
        os.umask(0o022)

        devnull = open(os.devnull, 'r+b')
        os.dup2(devnull.fileno(), sys.stdin.fileno())
        os.dup2(devnull.fileno(), sys.stdout.fileno())
        os.dup2(devnull.fileno(), sys.stderr.fileno())

        daemon = NotificationDaemon(args)
        daemon.run()
        sys.exit(0)

    if not _check_daemon_running():
        try:
            subprocess.Popen(
                [sys.executable, os.path.abspath(__file__), '--daemon'],
                start_new_session=True,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        except Exception:
            pass

    app = SimpleCalApp(args)
    try:
        sys.exit(app.run([sys.argv[0]]))
    except KeyboardInterrupt:
        sys.exit(0)
