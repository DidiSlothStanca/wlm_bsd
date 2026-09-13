#!/usr/bin/env python3
"""
Wine Launcher Manager - FreeBSD / BSD Edition
Port dari launcher.py (Linux, versi matang) - fungsionalitas dijaga semirip
mungkin: tema, manajemen game (add/remove/rename/icon), prefix per-game,
log real-time via pty, mode HUD, dan menu Settings.

Perbedaan yang disesuaikan untuk ekosistem FreeBSD/BSD:
  - Script launcher memakai #!/bin/sh dan dijalankan lewat `sh` (bukan bash,
    yang tidak ada di base FreeBSD).
  - Tidak ada "Proton GE" / "Proton-CachyOS" ala Steam (itu binary Linux ELF,
    tidak jalan native di FreeBSD tanpa Linuxulator). Sebagai gantinya dipakai
    REGISTRY RUNNER: daftar binary wine yang terpasang di sistem (wine biasa,
    wine-proton, wine-devel, dst - semuanya build native FreeBSD lewat pkg/ports)
    yang bisa ditambah/dihapus sendiri oleh pengguna lewat menu Settings.
  - Membuka folder memakai xdg-open dengan fallback ke file manager umum,
    karena instalasi FreeBSD desktop minimal belum tentu punya xdg-utils.
  - Mode HUD memakai Gallium HUD (fitur Mesa, native jalan di FreeBSD).

Dependensi yang perlu terpasang di FreeBSD (lewat pkg):
    pkg install python3 py311-tkinter py311-pillow wine wine-proton \
                 winetricks xdg-utils mesa-dri
(sesuaikan nama versi python/py-tkinter/py-pillow dengan yang tersedia)
"""
import os
import re
import shlex
import shutil
import subprocess
import threading
import queue
import pty
import select
import errno
import tkinter as tk
from tkinter import ttk, filedialog, simpledialog, messagebox
from pathlib import Path
from PIL import Image, ImageTk
import json
from datetime import datetime

# =======================================================================
# KONFIGURASI PATH
# =======================================================================
directory = Path.home() / "wlm_bsd"
icon_dir = directory / "icons"
scripts_dir = directory / "scripts"
logs_dir = directory / "logs"
prefixes_root = directory / "prefixes"

theme_config_file = directory / "theme_config.json"
window_config_file = directory / "window_config.json"
runners_config_file = directory / "runners_config.json"          # daftar runner: {"wine": "/usr/local/bin/wine", ...}
game_runner_config_file = directory / "game_runner_config.json"  # pilihan runner & prefix per game
prefix_location_config_file = directory / "prefix_location_config.json"  # lokasi default prefix BARU, per runner
prefix_registry_file = directory / "prefix_registry.json"        # semua prefix yang pernah dibuat/dipakai

# Kandidat lokasi binary wine bawaan port/pkg FreeBSD - dipakai HANYA untuk
# seeding otomatis saat pertama kali dijalankan (runners_config.json belum ada).
CANDIDATE_RUNNER_PATHS = [
    ("wine", "/usr/local/bin/wine"),
    ("wine-proton", "/usr/local/wine-proton/bin/wine"),
    ("wine-devel", "/usr/local/wine-devel/bin/wine64"),
    ("wine-devel", "/usr/local/wine-devel/bin/wine"),
]

for d in (directory, icon_dir, scripts_dir, logs_dir, prefixes_root):
    d.mkdir(parents=True, exist_ok=True)


def get_clean_subprocess_env():
    """Salinan environment yang aman dipakai untuk memanggil wine/xdg-open/dll."""
    return os.environ.copy()


# =======================================================================
# LIVE LOG (game yang sedang berjalan)
# =======================================================================
# nama_game -> {"proc", "log_path", "queue", "buffer", "window",
#               "text_widget", "status_label", "finished"}
running_games = {}
MAX_LOG_BUFFER_LINES = 5000

# =======================================================================
# THEME SYSTEM
# =======================================================================
THEMES = {
    "default": {
        "name": "Default (Dark Blue)", "primary": "#1a1a2e", "secondary": "#16213e",
        "accent": "#0f3460", "highlight": "#e94560", "text": "#ffffff",
        "text_secondary": "#b0b0b0", "button_text": "#ffffff", "success": "#4CAF50",
        "warning": "#FF9800", "danger": "#F44336", "card_bg": "#2d3047",
        "border": "#3a3d5c", "button_bg": "#0f3460", "button_fg": "#ffffff",
        "tree_bg": "#2d3047", "tree_fg": "#ffffff", "tree_highlight": "#e94560",
        "tree_highlight_text": "#ffffff", "text_background": "#1e1e35"
    },
    "dark": {
        "name": "Dark", "primary": "#121212", "secondary": "#1e1e1e",
        "accent": "#2d2d2d", "highlight": "#BB86FC", "text": "#ffffff",
        "text_secondary": "#aaaaaa", "button_text": "#ffffff", "success": "#03DAC6",
        "warning": "#FFB74D", "danger": "#CF6679", "card_bg": "#2d2d2d",
        "border": "#404040", "button_bg": "#3700B3", "button_fg": "#ffffff",
        "tree_bg": "#2d2d2d", "tree_fg": "#ffffff", "tree_highlight": "#BB86FC",
        "tree_highlight_text": "#000000", "text_background": "#1e1e1e"
    },
    "light": {
        "name": "Light", "primary": "#f5f5f5", "secondary": "#ffffff",
        "accent": "#e0e0e0", "highlight": "#6200EE", "text": "#000000",
        "text_secondary": "#666666", "button_text": "#ffffff", "success": "#00897B",
        "warning": "#FF8F00", "danger": "#C62828", "card_bg": "#ffffff",
        "border": "#dddddd", "button_bg": "#6200EE", "button_fg": "#ffffff",
        "tree_bg": "#ffffff", "tree_fg": "#000000", "tree_highlight": "#6200EE",
        "tree_highlight_text": "#ffffff", "text_background": "#ffffff"
    },
    "pinky": {
        "name": "Pinky", "primary": "#2d1b2e", "secondary": "#3d2b3f",
        "accent": "#5d3d5f", "highlight": "#f06292", "text": "#ffffff",
        "text_secondary": "#e0c3e0", "button_text": "#ffffff", "success": "#8e24aa",
        "warning": "#ffb6c1", "danger": "#d81b60", "card_bg": "#4a3b4c",
        "border": "#6d5a6f", "button_bg": "#e91e63", "button_fg": "#ffffff",
        "tree_bg": "#4a3b4c", "tree_fg": "#ffffff", "tree_highlight": "#f06292",
        "tree_highlight_text": "#ffffff", "text_background": "#3d2b3f"
    },
    "bsd_red": {  # tema baru bernuansa "beastie" untuk edisi BSD
        "name": "BSD Red", "primary": "#1c0f0f", "secondary": "#2b1414",
        "accent": "#4a1c1c", "highlight": "#e2231a", "text": "#ffffff",
        "text_secondary": "#d3a3a0", "button_text": "#ffffff", "success": "#4CAF50",
        "warning": "#FF9800", "danger": "#F44336", "card_bg": "#331717",
        "border": "#5c2727", "button_bg": "#4a1c1c", "button_fg": "#ffffff",
        "tree_bg": "#331717", "tree_fg": "#ffffff", "tree_highlight": "#e2231a",
        "tree_highlight_text": "#ffffff", "text_background": "#241111"
    }
}

FONT_FAMILY = "DejaVu Sans"
FONTS = {
    "title": (FONT_FAMILY, 14, "bold"),
    "subtitle": (FONT_FAMILY, 11, "bold"),
    "normal": (FONT_FAMILY, 9),
    "small": (FONT_FAMILY, 8)
}

ICON_SIZE = 250
ICON_WIDTH = ICON_SIZE
ICON_HEIGHT = ICON_SIZE

# =======================================================================
# CONFIG: THEME & WINDOW
# =======================================================================
def load_config():
    config = {"theme": "default", "window_size": "1000x720", "window_position": None}
    if theme_config_file.exists():
        try:
            with open(theme_config_file, 'r') as f:
                config["theme"] = json.load(f).get('theme', 'default')
        except Exception:
            pass
    if window_config_file.exists():
        try:
            with open(window_config_file, 'r') as f:
                wc = json.load(f)
                size = wc.get('size', '1000x720')
                pos = wc.get('position', None)
                if 'x' in size and size.count('x') == 1:
                    config["window_size"] = size
                if pos and pos.startswith('+') and pos.count('+') == 2:
                    config["window_position"] = pos
        except Exception:
            pass
    return config


def save_window_config():
    if root.winfo_exists():
        size = f"{root.winfo_width()}x{root.winfo_height()}"
        position = f"+{root.winfo_x()}+{root.winfo_y()}"
        try:
            with open(window_config_file, 'w') as f:
                json.dump({"size": size, "position": position}, f, indent=4)
        except Exception as e:
            print(f"Error saving window config: {e}")


# =======================================================================
# REGISTRY RUNNER (wine / wine-proton / wine-devel / dst)
# =======================================================================
def load_runners():
    """Muat daftar runner {nama: path_binary_wine}. Seeding otomatis pada
    pemakaian pertama dengan binary yang benar-benar ada di disk."""
    if runners_config_file.exists():
        try:
            with open(runners_config_file, 'r') as f:
                data = json.load(f)
                if isinstance(data, dict) and data:
                    return data
        except Exception:
            pass
    seeded = {}
    for name, path in CANDIDATE_RUNNER_PATHS:
        if Path(path).exists() and name not in seeded:
            seeded[name] = path
    if not seeded:
        # Belum terdeteksi binary apapun - tetap seed 'wine' agar aplikasi tetap
        # bisa dipakai begitu pengguna memasang wine lewat pkg (PATH akan resolve).
        seeded = {"wine": "wine"}
    save_runners(seeded)
    return seeded


def save_runners(runners):
    try:
        with open(runners_config_file, 'w') as f:
            json.dump(runners, f, indent=4)
    except Exception as e:
        print(f"Error saving runners config: {e}")


def get_default_runner_name():
    runners = load_runners()
    if "wine" in runners:
        return "wine"
    return next(iter(runners), None)


def get_default_wine_bin():
    name = get_default_runner_name()
    runners = load_runners()
    return runners.get(name) if name else None


def sibling_tool(wine_bin, tool_name):
    """Cari 'winecfg'/'wineserver'/dst di folder yang sama dengan binary wine
    yang dipilih; jika tidak ada, andalkan PATH (pkg biasanya menaruh semua
    tool wine di direktori bin yang sama)."""
    try:
        p = Path(wine_bin)
        candidate = p.parent / tool_name
        if candidate.exists():
            return str(candidate)
    except Exception:
        pass
    return tool_name


def manage_runners_dialog():
    """Dialog untuk menambah/menghapus runner (binary wine) yang dikenal
    aplikasi. Menggantikan fitur 'Extract Proton GE Archive' di versi Linux -
    di FreeBSD, build wine/wine-proton dipasang lewat pkg, bukan diekstrak."""
    runners = load_runners()

    dialog = tk.Toplevel(root)
    dialog.title("Manage Runners")
    dialog.configure(bg=COLORS["primary"])
    dialog.resizable(False, False)
    dialog.transient(root)
    dialog.grab_set()

    frame = ttk.Frame(dialog, padding=15)
    frame.pack(fill=tk.BOTH, expand=True)

    ttk.Label(frame, text="Known wine-based runners:", font=FONTS["normal"]).pack(anchor="w", pady=(0, 6))

    list_frame = ttk.Frame(frame)
    list_frame.pack(fill=tk.BOTH, expand=True)
    scroll = ttk.Scrollbar(list_frame, orient=tk.VERTICAL)
    scroll.pack(side=tk.RIGHT, fill=tk.Y)
    listbox = tk.Listbox(list_frame, width=60, height=8, yscrollcommand=scroll.set,
                          bg=COLORS["text_background"], fg=COLORS["text"],
                          selectbackground=COLORS["highlight"])
    listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
    scroll.config(command=listbox.yview)

    def refresh_list():
        listbox.delete(0, tk.END)
        for name, path in sorted(runners.items()):
            exists = "OK" if Path(path).exists() or shutil.which(path) else "not found"
            listbox.insert(tk.END, f"{name}  ->  {path}   [{exists}]")

    refresh_list()

    btn_row = ttk.Frame(frame)
    btn_row.pack(fill=tk.X, pady=(10, 0))

    def do_add():
        name = simpledialog.askstring("Runner Name", "Name for this runner (e.g. wine-proton):", parent=dialog)
        if not name or not name.strip():
            return
        name = name.strip()
        path = filedialog.askopenfilename(
            title=f"Select the '{name}' wine binary",
            initialdir="/usr/local/bin"
        )
        if not path:
            return
        runners[name] = path
        save_runners(runners)
        refresh_list()

    def do_remove():
        sel = listbox.curselection()
        if not sel:
            messagebox.showinfo("Info", "Select a runner to remove.")
            return
        name = sorted(runners.keys())[sel[0]]
        if messagebox.askyesno("Confirm", f"Remove runner '{name}' from the list?\n"
                                           "(This does not uninstall wine itself, "
                                           "only forgets it here.)"):
            del runners[name]
            save_runners(runners)
            refresh_list()

    ttk.Button(btn_row, text="+ Add Runner...", style="Custom.TButton", command=do_add).pack(side=tk.LEFT)
    ttk.Button(btn_row, text="Remove Selected", style="Custom.TButton", command=do_remove).pack(side=tk.LEFT, padx=(8, 0))
    ttk.Button(btn_row, text="Close", style="Custom.TButton", command=dialog.destroy).pack(side=tk.RIGHT)

    dialog.update_idletasks()
    x = root.winfo_x() + (root.winfo_width() // 2) - (dialog.winfo_width() // 2)
    y = root.winfo_y() + (root.winfo_height() // 2) - (dialog.winfo_height() // 2)
    dialog.geometry(f"+{x}+{y}")


# =======================================================================
# MANAJEMEN PREFIX (per-game, per-runner)
# =======================================================================
def generate_next_prefix_code(runner_name):
    numbers = []
    for cfg in load_game_runner_config().values():
        if cfg.get("runner") == runner_name:
            code = cfg.get("prefix_code", "") or ""
            if code.startswith("GAME") and code[4:].isdigit():
                numbers.append(int(code[4:]))
    default_root = prefixes_root / runner_name
    if default_root.is_dir():
        for entry in default_root.iterdir():
            if entry.is_dir() and entry.name.startswith("GAME") and entry.name[4:].isdigit():
                numbers.append(int(entry.name[4:]))
    return f"GAME{max(numbers, default=0) + 1:03d}"


def load_prefix_location_config():
    if prefix_location_config_file.exists():
        try:
            with open(prefix_location_config_file, 'r') as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_prefix_location_config(cfg):
    try:
        with open(prefix_location_config_file, 'w') as f:
            json.dump(cfg, f, indent=4)
    except Exception as e:
        print(f"Error saving prefix location config: {e}")


def get_prefix_base_dir(runner_name):
    cfg = load_prefix_location_config()
    custom = cfg.get(runner_name)
    default_root = prefixes_root / runner_name
    if custom:
        p = Path(custom)
        try:
            p.mkdir(parents=True, exist_ok=True)
            return p
        except Exception:
            return default_root
    return default_root


def set_prefix_base_dir(runner_name, path):
    cfg = load_prefix_location_config()
    cfg[runner_name] = str(path)
    save_prefix_location_config(cfg)


def reset_prefix_base_dir(runner_name):
    cfg = load_prefix_location_config()
    if runner_name in cfg:
        del cfg[runner_name]
        save_prefix_location_config(cfg)


def load_prefix_registry():
    if prefix_registry_file.exists():
        try:
            with open(prefix_registry_file, 'r') as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_prefix_registry(reg):
    try:
        with open(prefix_registry_file, 'w') as f:
            json.dump(reg, f, indent=4)
    except Exception as e:
        print(f"Error saving prefix registry: {e}")


def record_prefix_usage(runner_name, prefix_code, prefix_path):
    reg = load_prefix_registry()
    reg[f"{runner_name}:{prefix_code}"] = {
        "runner": runner_name, "prefix_code": prefix_code, "prefix_path": str(prefix_path)
    }
    save_prefix_registry(reg)


def update_registry_prefix_path(runner_name, prefix_code, new_path):
    reg = load_prefix_registry()
    key = f"{runner_name}:{prefix_code}"
    if key in reg:
        reg[key]["prefix_path"] = str(new_path)
    else:
        reg[key] = {"runner": runner_name, "prefix_code": prefix_code, "prefix_path": str(new_path)}
    save_prefix_registry(reg)


def find_owning_prefix(exe_path):
    """Cek apakah exe_path berada didalam prefix yang sudah pernah dibuat -
    supaya game yang sudah diinstal (mis. lewat APPS SETUP) tidak diberi
    prefix baru yang kosong saat ditambahkan (+ ADD)."""
    try:
        exe_resolved = exe_path.resolve()
    except Exception:
        exe_resolved = exe_path

    registry = load_prefix_registry()
    candidates = []
    for entry in registry.values():
        p, r, c = entry.get("prefix_path"), entry.get("runner"), entry.get("prefix_code")
        if p and r and c:
            candidates.append((r, c, Path(p)))

    loc_cfg = load_prefix_location_config()
    scan_roots = [(name, prefixes_root / name) for name in load_runners().keys()]
    for name, _default in list(scan_roots):
        custom = loc_cfg.get(name)
        if custom:
            scan_roots.append((name, Path(custom)))

    known_paths = {str(p.resolve()) for _, _, p in candidates if p.exists()}
    for runner_name, base_dir in scan_roots:
        if not base_dir.is_dir():
            continue
        for entry in base_dir.iterdir():
            if entry.is_dir():
                try:
                    resolved = entry.resolve()
                except Exception:
                    continue
                if str(resolved) not in known_paths:
                    candidates.append((runner_name, entry.name, entry))

    for runner_name, prefix_code, prefix_dir in candidates:
        try:
            prefix_resolved = prefix_dir.resolve()
        except Exception:
            continue
        if prefix_resolved == exe_resolved or prefix_resolved in exe_resolved.parents:
            return {"runner": runner_name, "prefix_code": prefix_code, "prefix_path": str(prefix_resolved)}
    return None


def browse_folder_with_create_option(title, initialdir):
    chosen = filedialog.askdirectory(title=title, initialdir=initialdir, mustexist=True)
    if not chosen:
        return None
    chosen_path = Path(chosen)
    if not messagebox.askyesno(
        "Create New Folder?",
        f"Selected folder:\n{chosen_path}\n\nCreate a new folder inside it for the prefix(es)?\n"
        "(Recommended so prefixes stay organized.)"
    ):
        return chosen_path
    folder_name = simpledialog.askstring("New Folder", "New folder name:", parent=root)
    if not folder_name or not folder_name.strip():
        return chosen_path
    new_dir = chosen_path / folder_name.strip()
    try:
        new_dir.mkdir(parents=True, exist_ok=True)
        return new_dir
    except Exception as e:
        messagebox.showerror("Error", f"Failed to create folder:\n{str(e)}")
        return chosen_path


def move_prefix_folder_dialog(old_path, prefix_code, runner_name, on_done):
    initial_dir = str(old_path.parent) if old_path.parent.is_dir() else str(Path.home())
    new_base_path = browse_folder_with_create_option(
        title=f"Choose New Location for Prefix {prefix_code}", initialdir=initial_dir)
    if new_base_path is None:
        return
    new_path = new_base_path / prefix_code
    try:
        same = new_path.resolve() == old_path.resolve()
    except Exception:
        same = False
    if same:
        messagebox.showinfo("Info", "The prefix is already in this location.")
        return
    if new_path.exists():
        messagebox.showerror("Error", f"A folder named '{prefix_code}' already exists there.")
        return
    if not old_path.exists():
        messagebox.showerror("Error", f"Prefix folder not found on disk:\n{old_path}")
        return
    if not messagebox.askyesno("Confirm Move",
                                f"Move prefix '{prefix_code}' to:\n{new_path}\n\n"
                                "Make sure the game using this prefix is not currently running.\n"
                                "This may take a while for large prefixes. Continue?"):
        return

    loading = tk.Toplevel(root)
    loading.title("Moving Prefix")
    loading.configure(bg=COLORS["primary"])
    loading.resizable(False, False)
    loading.transient(root)
    loading.protocol("WM_DELETE_WINDOW", lambda: None)
    lf = ttk.Frame(loading, padding=20)
    lf.pack(fill=tk.BOTH, expand=True)
    ttk.Label(lf, text=f"Moving prefix '{prefix_code}'...", font=FONTS["subtitle"], justify=tk.CENTER).pack(pady=(0, 4))
    ttk.Label(lf, text="This can take a while for large prefixes.\nPlease wait.", font=FONTS["small"], justify=tk.CENTER).pack(pady=(0, 14))
    pbar = ttk.Progressbar(lf, mode="indeterminate", length=280)
    pbar.pack()
    pbar.start(12)
    loading.update_idletasks()
    x = root.winfo_rootx() + (root.winfo_width() - loading.winfo_width()) // 2
    y = root.winfo_rooty() + (root.winfo_height() - loading.winfo_height()) // 2
    loading.geometry(f"+{x}+{y}")
    loading.grab_set()

    result = {"error": None}

    def do_move():
        try:
            new_base_path.mkdir(parents=True, exist_ok=True)
            shutil.move(str(old_path), str(new_path))
        except Exception as e:
            result["error"] = e

    def finish():
        pbar.stop()
        loading.grab_release()
        loading.destroy()
        if result["error"] is None:
            status_label.config(text=f"Prefix '{prefix_code}' moved to {new_path}", fg=COLORS["success"])
            on_done(new_path)
        else:
            status_label.config(text=f"Error moving prefix: {result['error']}", fg=COLORS["danger"])
            messagebox.showerror("Error", f"Failed to move prefix:\n{result['error']}")

    def worker():
        do_move()
        root.after(0, finish)

    threading.Thread(target=worker, daemon=True).start()


# =======================================================================
# KONFIGURASI PER-GAME (runner + prefix + launch options)
# =======================================================================
def load_game_runner_config():
    if game_runner_config_file.exists():
        try:
            with open(game_runner_config_file, 'r') as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_game_runner_config(cfg):
    try:
        with open(game_runner_config_file, 'w') as f:
            json.dump(cfg, f, indent=4)
    except Exception as e:
        print(f"Error saving game runner config: {e}")


def parse_launch_options(launch_options_str):
    """Parse launch options ala Steam: 'KEY=VAL %command% -arg'."""
    if not launch_options_str or not launch_options_str.strip():
        return [], []
    try:
        tokens = shlex.split(launch_options_str)
    except ValueError:
        tokens = launch_options_str.split()

    env_vars, extra_args = [], []
    if "%command%" in tokens:
        idx = tokens.index("%command%")
        before, after = tokens[:idx], tokens[idx + 1:]
        for t in before:
            if "=" in t and not t.startswith("-"):
                k, v = t.split("=", 1)
                env_vars.append((k, v))
        extra_args = after
    else:
        for t in tokens:
            if "=" in t and not t.startswith("-"):
                k, v = t.split("=", 1)
                env_vars.append((k, v))
            else:
                extra_args.append(t)
    return env_vars, extra_args


def extract_exe_path_from_script(script_path):
    """Ambil path .exe dari baris eksekusi terakhir: "<wine_bin>" "<exe>" ..."""
    try:
        with open(script_path, 'r') as f:
            lines = f.readlines()
        for line in reversed(lines):
            m = re.match(r'^\s*"[^"]+"\s+"([^"]+)"', line)
            if m:
                return m.group(1)
    except Exception:
        pass
    return None


def extract_folder_path_from_script(script_path):
    """Baris ke-2 (index 1) selalu 'cd "..."'."""
    try:
        with open(script_path, 'r') as f:
            lines = f.readlines()
        if len(lines) >= 2:
            m = re.search(r'cd\s+"([^"]+)"', lines[1].strip())
            if m:
                return m.group(1)
    except Exception:
        pass
    return None


def build_script_content(folder_path, exe_path, choice):
    """Bangun ulang isi script .sh sesuai runner, prefix, dan launch options."""
    lines = ["#!/bin/sh", f'cd "{folder_path}"']

    comment = (choice.get("comment") or "").strip()
    if comment:
        for cline in comment.splitlines():
            lines.append(f'# {cline}')

    launch_options = (choice.get("launch_options") or "").strip()
    if launch_options:
        lines.append(f'# Launch Options: {launch_options}')

    env_vars, extra_args = parse_launch_options(launch_options)
    for key, val in env_vars:
        lines.append(f'export {key}={shlex.quote(val)}')

    if choice.get("prefix_path"):
        lines.append(f'export WINEPREFIX="{choice["prefix_path"]}"')

    wine_bin = choice.get("wine_bin") or load_runners().get(choice.get("runner"), "wine")
    extra_args_str = (" " + " ".join(shlex.quote(a) for a in extra_args)) if extra_args else ""
    lines.append(f'"{wine_bin}" "{exe_path}"{extra_args_str}')
    return "\n".join(lines) + "\n"


def build_prefix_panel(parent_frame, runner_key, runner_label_text, existing_cfg, parent_script_name):
    """Panel lokasi prefix untuk satu runner didalam dialog pemilihan runner."""
    state = {"existing_path": None, "existing_code": None, "new_base_dir": get_prefix_base_dir(runner_key)}
    if existing_cfg and existing_cfg.get("runner") == runner_key and existing_cfg.get("prefix_code") and existing_cfg.get("prefix_path"):
        state["existing_path"] = Path(existing_cfg["prefix_path"])
        state["existing_code"] = existing_cfg["prefix_code"]

    panel = ttk.Frame(parent_frame)
    info_var = tk.StringVar()
    ttk.Label(panel, textvariable=info_var, font=FONTS["small"], justify=tk.LEFT, wraplength=380).pack(anchor="w", pady=(2, 4))

    btn_row = ttk.Frame(panel)
    btn_row.pack(anchor="w", pady=(0, 8))

    move_btn = ttk.Button(btn_row, text="Move Prefix...", style="Custom.TButton")
    browse_btn = ttk.Button(btn_row, text="Browse Other Folder/Disk...", style="Custom.TButton")
    default_btn = ttk.Button(btn_row, text="Use Default (WLM Folder)", style="Custom.TButton")

    def refresh():
        for w in (move_btn, browse_btn, default_btn):
            w.pack_forget()
        if state["existing_path"] is not None:
            info_var.set(f"Prefix: {state['existing_code']} (used previously, kept consistent)\n"
                          f"Location: {state['existing_path']}")
            move_btn.pack(side=tk.LEFT)
        else:
            info_var.set(f"A new prefix will be created automatically at:\n{state['new_base_dir']} (e.g. GAMEXXX)")
            browse_btn.pack(side=tk.LEFT, padx=(0, 5))
            default_btn.pack(side=tk.LEFT)

    def do_move():
        def on_moved(new_path):
            state["existing_path"] = new_path
            if parent_script_name:
                cfg_all = load_game_runner_config()
                if parent_script_name in cfg_all and cfg_all[parent_script_name].get("runner") == runner_key:
                    cfg_all[parent_script_name]["prefix_path"] = str(new_path)
                    save_game_runner_config(cfg_all)
            update_registry_prefix_path(runner_key, state["existing_code"], new_path)
            refresh()
        move_prefix_folder_dialog(state["existing_path"], state["existing_code"], runner_key, on_moved)

    def do_browse():
        initial = str(state["new_base_dir"]) if state["new_base_dir"].is_dir() else str(Path.home())
        chosen_dir = browse_folder_with_create_option(
            title=f"Choose Default Location for New {runner_label_text} Prefixes", initialdir=initial)
        if chosen_dir:
            state["new_base_dir"] = chosen_dir
            set_prefix_base_dir(runner_key, state["new_base_dir"])
            refresh()

    def do_default():
        state["new_base_dir"] = prefixes_root / runner_key
        reset_prefix_base_dir(runner_key)
        refresh()

    move_btn.config(command=do_move)
    browse_btn.config(command=do_browse)
    default_btn.config(command=do_default)

    refresh()
    return panel, state


def ask_runner_choice(parent_script_name=None, purpose="play"):
    """Dialog pilihan runner (semua binary wine yang terdaftar) + prefix
    per-game + launch options + comment. Return dict pilihan, atau None."""
    runners = load_runners()
    runner_names = sorted(runners.keys())
    if not runner_names:
        messagebox.showerror("Error", "No runners configured.\nAdd one via Settings > Manage Runners...")
        return None

    existing_cfg = load_game_runner_config().get(parent_script_name) if parent_script_name else None

    dialog = tk.Toplevel(root)
    dialog.title("Select Runner - Setup" if purpose == "setup" else "Select Runner - Play")
    dialog.configure(bg=COLORS["primary"])
    dialog.resizable(False, False)
    dialog.transient(root)
    dialog.grab_set()

    result = {"value": None}
    frame = ttk.Frame(dialog, padding=15)
    frame.pack(fill=tk.BOTH, expand=True)

    ttk.Label(frame, text="Select Runner:", font=FONTS["normal"]).pack(anchor="w", pady=(0, 10))

    default_runner = existing_cfg.get("runner") if (existing_cfg and existing_cfg.get("runner") in runner_names) else runner_names[0]
    runner_var = tk.StringVar(value=default_runner)

    runner_row = ttk.Frame(frame)
    runner_row.pack(anchor="w", pady=(0, 2))
    for i, name in enumerate(runner_names):
        ttk.Radiobutton(runner_row, text=name, variable=runner_var, value=name,
                         style="Runner.TRadiobutton", width=14).grid(row=i // 3, column=i % 3, padx=3, pady=3)

    prefix_container = ttk.Frame(frame)
    prefix_container.pack(anchor="w", fill=tk.X, pady=(0, 0))
    panel_state = {"panel": None, "state": None, "use_var": None}

    def rebuild_prefix_ui(*_):
        for w in prefix_container.winfo_children():
            w.destroy()
        runner_name = runner_var.get()
        use_var = tk.BooleanVar(value=bool(existing_cfg and existing_cfg.get("runner") == runner_name and existing_cfg.get("prefix_path")))
        checkbox = ttk.Checkbutton(prefix_container,
                                    text="Use an isolated prefix for this game (avoids buildup in home folder)",
                                    variable=use_var, style="Custom.TCheckbutton")
        checkbox.pack(anchor="w", pady=(10, 4))
        panel, state = build_prefix_panel(prefix_container, runner_name, runner_name, existing_cfg, parent_script_name)

        def toggle(*_):
            if use_var.get():
                panel.pack(anchor="w", pady=(2, 8), fill=tk.X)
            else:
                panel.pack_forget()

        use_var.trace_add("write", toggle)
        toggle()
        panel_state.update(panel=panel, state=state, use_var=use_var)

    runner_var.trace_add("write", rebuild_prefix_ui)
    rebuild_prefix_ui()

    ttk.Separator(frame, orient="horizontal").pack(fill=tk.X, pady=(5, 10))

    ttk.Label(frame, text="Launch Options / Environment Variable (optional):", font=FONTS["small"]).pack(anchor="w", pady=(0, 2))
    launch_options_entry = ttk.Entry(frame, width=48, font=FONTS["small"])
    launch_options_entry.pack(anchor="w", fill=tk.X)
    if existing_cfg and existing_cfg.get("launch_options"):
        launch_options_entry.insert(0, existing_cfg["launch_options"])
    ttk.Label(frame, text="Example: WINEDEBUG=-all %command% -windowed", font=FONTS["small"]).pack(anchor="w", pady=(2, 10))

    ttk.Label(frame, text="Comment (optional):", font=FONTS["small"]).pack(anchor="w", pady=(0, 2))
    comment_entry = ttk.Entry(frame, width=48, font=FONTS["small"])
    comment_entry.pack(anchor="w", fill=tk.X, pady=(0, 10))
    if existing_cfg and existing_cfg.get("comment"):
        comment_entry.insert(0, existing_cfg["comment"])

    btn_frame = ttk.Frame(frame)
    btn_frame.pack(fill=tk.X, pady=(5, 0))

    def on_ok():
        runner_name = runner_var.get()
        result_value = {
            "runner": runner_name,
            "wine_bin": runners[runner_name],
            "launch_options": launch_options_entry.get().strip(),
            "comment": comment_entry.get().strip()
        }
        if panel_state["use_var"].get():
            state = panel_state["state"]
            if state["existing_path"] is not None:
                prefix_code, prefix_path = state["existing_code"], state["existing_path"]
            else:
                prefix_code = generate_next_prefix_code(runner_name)
                prefix_path = state["new_base_dir"] / prefix_code
            prefix_path.mkdir(parents=True, exist_ok=True)
            record_prefix_usage(runner_name, prefix_code, prefix_path)
            result_value["prefix_code"] = prefix_code
            result_value["prefix_path"] = str(prefix_path)
        result["value"] = result_value
        dialog.destroy()

    def on_cancel():
        result["value"] = None
        dialog.destroy()

    ttk.Button(btn_frame, text="Cancel", command=on_cancel, style="Custom.TButton", width=12).pack(side=tk.LEFT)
    ttk.Button(btn_frame, text="OK", command=on_ok, style="Custom.TButton", width=12).pack(side=tk.RIGHT)
    ttk.Button(btn_frame, text="Manage Runners...", command=lambda: (dialog.destroy(), manage_runners_dialog()),
               style="Custom.TButton").pack(side=tk.RIGHT, padx=(0, 8))

    dialog.update_idletasks()
    w, h = dialog.winfo_width(), dialog.winfo_height()
    x = root.winfo_x() + (root.winfo_width() // 2) - (w // 2)
    y = root.winfo_y() + (root.winfo_height() // 2) - (h // 2)
    dialog.geometry(f"+{x}+{y}")

    dialog.wait_window()
    return result["value"]


# =======================================================================
# THEME FUNCTIONS
# =======================================================================
def apply_theme(theme_name):
    global CURRENT_THEME, COLORS
    if theme_name not in THEMES:
        theme_name = "default"
    CURRENT_THEME = theme_name
    COLORS = THEMES[theme_name]
    save_theme_config(theme_name)
    update_style_config()
    update_widget_colors()
    status_label.config(text=f"Changed to {COLORS['name']} theme", fg=COLORS["success"])
    theme_combo.set(COLORS["name"])


def save_theme_config(theme_name):
    with open(theme_config_file, 'w') as f:
        json.dump({'theme': theme_name}, f)


def update_style_config():
    style.configure("TFrame", background=COLORS["primary"])
    style.configure("TPanedwindow", background=COLORS["primary"])
    style.configure("TLabel", background=COLORS["primary"], foreground=COLORS["text"], font=FONTS["normal"])

    style.configure("Custom.TButton", background=COLORS["button_bg"], foreground=COLORS["button_fg"],
                     bordercolor=COLORS["border"], borderwidth=1, focusthickness=1,
                     focuscolor=COLORS["highlight"], font=FONTS["normal"], padding=6)
    style.map("Custom.TButton",
              background=[("active", COLORS["highlight"]), ("!active", COLORS["button_bg"])],
              foreground=[("active", COLORS["button_text"]), ("!active", COLORS["button_fg"])])

    style.layout("Runner.TRadiobutton", style.layout("TButton"))
    style.configure("Runner.TRadiobutton", background=COLORS["button_bg"], foreground=COLORS["button_fg"],
                     bordercolor=COLORS["border"], borderwidth=1, focusthickness=1,
                     focuscolor=COLORS["highlight"], font=FONTS["normal"], anchor="center", padding=6)
    style.map("Runner.TRadiobutton",
              background=[("disabled", COLORS["card_bg"]), ("selected", COLORS["highlight"]),
                          ("active", COLORS["highlight"]), ("!selected", COLORS["button_bg"])],
              foreground=[("disabled", COLORS["text_secondary"]), ("selected", COLORS["button_text"]),
                          ("active", COLORS["button_text"]), ("!selected", COLORS["button_fg"])])

    style.configure("Custom.TCheckbutton", background=COLORS["primary"], foreground=COLORS["text"],
                     font=FONTS["normal"], indicatorbackground=COLORS["text_background"],
                     indicatorforeground=COLORS["button_text"], indicatormargin=(0, 0, 6, 0),
                     focuscolor=COLORS["highlight"])
    style.map("Custom.TCheckbutton",
              background=[("active", COLORS["primary"])],
              foreground=[("disabled", COLORS["text_secondary"]), ("active", COLORS["text"])],
              indicatorbackground=[("disabled", COLORS["card_bg"]), ("selected", COLORS["highlight"]),
                                    ("!selected", COLORS["text_background"])],
              indicatorforeground=[("disabled", COLORS["text_secondary"]), ("selected", COLORS["button_text"])])

    style.configure("TCombobox", fieldbackground=COLORS["text_background"], background=COLORS["card_bg"],
                     foreground=COLORS["text"], selectbackground=COLORS["highlight"],
                     selectforeground=COLORS["text"], bordercolor=COLORS["border"], relief="flat", borderwidth=1)
    style.map("TCombobox",
              fieldbackground=[("readonly", COLORS["text_background"])],
              selectbackground=[("readonly", COLORS["highlight"])],
              selectforeground=[("readonly", COLORS["text_background"])],
              background=[("readonly", COLORS["card_bg"])],
              foreground=[("readonly", COLORS["text"])])

    style.configure("TScrollbar", background=COLORS["secondary"], troughcolor=COLORS["primary"],
                     bordercolor=COLORS["primary"], arrowcolor=COLORS["text"])
    style.map("TScrollbar", background=[("active", COLORS["highlight"])])

    style.configure("TProgressbar", background=COLORS["highlight"], troughcolor=COLORS["card_bg"],
                     bordercolor=COLORS["border"], lightcolor=COLORS["highlight"], darkcolor=COLORS["highlight"])

    style.configure("Treeview", background=COLORS["tree_bg"], foreground=COLORS["tree_fg"],
                     fieldbackground=COLORS["tree_bg"], bordercolor=COLORS["border"], borderwidth=0, rowheight=25)
    style.configure("Treeview.Heading", background=COLORS["secondary"], foreground=COLORS["highlight"],
                     relief="raised", font=FONTS["subtitle"], padding=6, bordercolor=COLORS["border"])
    style.map("Treeview", background=[("selected", COLORS["tree_highlight"])],
              foreground=[("selected", COLORS["tree_highlight_text"])])


def update_widget_colors():
    try:
        root.configure(bg=COLORS["primary"])
        title_label.config(bg=COLORS["primary"], fg=COLORS["text"])
        status_label.config(bg=COLORS["primary"], fg=COLORS["text_secondary"])
        game_title_label.config(bg=COLORS["primary"], fg=COLORS["text"])
        info_label.config(bg=COLORS["primary"], fg=COLORS["text_secondary"])
        icon_label.config(bg=COLORS["card_bg"])
        settings_menu.config(bg=COLORS["card_bg"], fg=COLORS["text"],
                              activebackground=COLORS["highlight"], activeforeground=COLORS["button_text"])
        for btn in all_buttons:
            btn.configure(style="Custom.TButton")
        theme_combo.configure(style="TCombobox")
        sort_combo.configure(style="TCombobox")
        launch_mode_combo.configure(style="TCombobox")
        tree.configure(style="Treeview")
    except Exception:
        pass


# =======================================================================
# FUNGSI UTAMA APLIKASI
# =======================================================================
def update_script_list(sort_order="ascending"):
    for row in tree.get_children():
        tree.delete(row)
    script_files = sorted(scripts_dir.glob("*.sh"), key=lambda x: x.stem.lower())
    if sort_order == "descending":
        script_files.reverse()
    for index, file in enumerate(script_files, start=1):
        tree.insert("", "end", values=(index, file.stem))
    if tree.get_children():
        root.after(100, on_select)
    else:
        game_title_label.config(text="No Game Selected")
        icon_label.config(image='')
        icon_label.image = None
        info_text.set("Select a game to view details")


# =======================================================================
# Streaming log secara real-time (via pty, jalan sama di FreeBSD)
# =======================================================================
ANSI_ESCAPE_RE = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')


def stream_output(script_name_only, proc, master_fd, log_path):
    entry = running_games.get(script_name_only)
    try:
        with open(log_path, "w", encoding="utf-8", errors="replace") as log_f:
            while True:
                try:
                    ready, _, _ = select.select([master_fd], [], [], 0.25)
                except OSError:
                    break
                if master_fd in ready:
                    try:
                        data = os.read(master_fd, 4096)
                    except OSError as e:
                        if e.errno == errno.EIO:
                            break
                        raise
                    if not data:
                        break
                    text = ANSI_ESCAPE_RE.sub('', data.decode("utf-8", errors="replace"))
                    text = text.replace("\r\n", "\n").replace("\r", "\n")
                    log_f.write(text)
                    log_f.flush()
                    if entry:
                        entry["queue"].put(text)
                if proc.poll() is not None and not ready:
                    break
    except Exception as e:
        if entry:
            entry["queue"].put(f"\n[launcher] Error reading process output: {e}\n")
    finally:
        try:
            os.close(master_fd)
        except OSError:
            pass
        proc.wait()
        if entry:
            entry["queue"].put(f"\n[launcher] Process exited (code {proc.returncode}).\n")
            entry["finished"] = True


def poll_log_queues():
    for script_name_only, entry in list(running_games.items()):
        new_lines = []
        try:
            while True:
                new_lines.append(entry["queue"].get_nowait())
        except queue.Empty:
            pass
        if new_lines:
            entry["buffer"].extend(new_lines)
            if len(entry["buffer"]) > MAX_LOG_BUFFER_LINES:
                entry["buffer"] = entry["buffer"][-MAX_LOG_BUFFER_LINES:]
            text_widget = entry.get("text_widget")
            if text_widget and text_widget.winfo_exists():
                was_at_bottom = text_widget.yview()[1] >= 0.999
                text_widget.config(state="normal")
                text_widget.insert(tk.END, "".join(new_lines))
                text_widget.config(state="disabled")
                if was_at_bottom:
                    text_widget.see(tk.END)
            status_label_widget = entry.get("status_label")
            if entry["finished"] and status_label_widget and status_label_widget.winfo_exists():
                status_label_widget.config(text="Finished", fg=COLORS["text_secondary"])
    root.after(150, poll_log_queues)


def open_log_window(script_name_only):
    entry = running_games.get(script_name_only)
    log_path = logs_dir / f"{script_name_only}.log"

    if entry and entry.get("window") is not None and entry["window"].winfo_exists():
        entry["window"].lift()
        entry["window"].focus_force()
        return

    win = tk.Toplevel(root)
    win.title(f"Logs - {script_name_only}")
    win.configure(bg=COLORS["primary"])
    win.geometry("800x500")
    win.minsize(400, 250)

    top_bar = ttk.Frame(win, padding=(10, 8))
    top_bar.pack(fill=tk.X)
    ttk.Label(top_bar, text=script_name_only, font=FONTS["subtitle"]).pack(side=tk.LEFT)

    is_live = bool(entry and not entry.get("finished"))
    state_text = "Running (live)" if is_live else "Not running (last saved log)"
    state_color = COLORS["success"] if is_live else COLORS["text_secondary"]
    run_state_label = tk.Label(top_bar, text=state_text, font=FONTS["small"], fg=state_color)
    run_state_label.pack(side=tk.RIGHT)

    text_frame = ttk.Frame(win)
    text_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))
    text_scroll = ttk.Scrollbar(text_frame, orient=tk.VERTICAL)
    text_scroll.pack(side=tk.RIGHT, fill=tk.Y)
    text_widget = tk.Text(text_frame, wrap=tk.NONE, state="disabled",
                           bg=COLORS["text_background"], fg=COLORS["text"],
                           insertbackground=COLORS["text"], font=("Courier", 9),
                           yscrollcommand=text_scroll.set)
    text_widget.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
    text_scroll.config(command=text_widget.yview)

    def insert_initial(content):
        text_widget.config(state="normal")
        text_widget.insert(tk.END, content)
        text_widget.config(state="disabled")
        text_widget.see(tk.END)

    if entry:
        insert_initial("".join(entry["buffer"]) if entry["buffer"] else "(waiting for output...)\n")
        entry["window"] = win
        entry["text_widget"] = text_widget
        entry["status_label"] = run_state_label
    elif log_path.exists():
        try:
            insert_initial(log_path.read_text(encoding="utf-8", errors="replace"))
        except Exception as e:
            insert_initial(f"[launcher] Could not read log file: {e}\n")
    else:
        insert_initial("(No logs yet - launch this game at least once first)\n")

    def on_close():
        if entry:
            entry["window"] = None
            entry["text_widget"] = None
            entry["status_label"] = None
        win.destroy()

    win.protocol("WM_DELETE_WINDOW", on_close)

    bottom_bar = ttk.Frame(win, padding=(10, 0, 10, 10))
    bottom_bar.pack(fill=tk.X)

    def clear_view():
        text_widget.config(state="normal")
        text_widget.delete("1.0", tk.END)
        text_widget.config(state="disabled")

    ttk.Button(bottom_bar, text="Clear View", command=clear_view).pack(side=tk.LEFT)
    ttk.Button(bottom_bar, text="Open Log File",
               command=lambda: open_path_in_file_manager(str(log_path))
               if log_path.exists() else messagebox.showinfo("Info", "No log file yet")
               ).pack(side=tk.LEFT, padx=(8, 0))


def view_logs():
    selected = tree.focus()
    if not selected:
        messagebox.showinfo("Info", "Please select a game first")
        return
    open_log_window(tree.item(selected, "values")[1])


def run_script():
    selected = tree.focus()
    if not selected:
        messagebox.showinfo("Info", "Please select a game first")
        return

    script_name_only = tree.item(selected, "values")[1]
    script_name = script_name_only + ".sh"
    script_path = scripts_dir / script_name
    launch_mode = launch_mode_combo.get()

    if not script_path.exists():
        status_label.config(text=f"Error: Script file not found: {script_name}", fg=COLORS["danger"])
        return

    choice = ask_runner_choice(parent_script_name=script_name_only, purpose="play")
    if choice is None:
        status_label.config(text="Launch cancelled.", fg=COLORS["text_secondary"])
        return

    exe_path = extract_exe_path_from_script(script_path)
    folder_path = extract_folder_path_from_script(script_path)
    if exe_path and folder_path:
        try:
            with open(script_path, 'w') as f:
                f.write(build_script_content(folder_path, exe_path, choice))
        except Exception as e:
            status_label.config(text=f"Error updating script for runner: {str(e)}", fg=COLORS["danger"])
            return
    else:
        status_label.config(text="Error: Could not read exe/folder path from script.", fg=COLORS["danger"])
        return

    runner_cfg = load_game_runner_config()
    runner_cfg[script_name_only] = choice
    save_game_runner_config(runner_cfg)

    if not os.access(script_path, os.X_OK):
        try:
            script_path.chmod(0o755)
        except Exception:
            status_label.config(text=f"Error: Cannot set executable permission for {script_name}.", fg=COLORS["danger"])
            return

    scale_value = scale_entry.get().strip() or "1"
    commands = {
        "Normal": ["sh", str(script_path)],
        "GalliumHUD": ["sh", "-c",
                        f'GALLIUM_HUD="GPU-load+cpu+fps" GALLIUM_HUD_SCALE={scale_value} "{script_path}"'],
    }
    command = commands.get(launch_mode, commands["Normal"])
    log_path = logs_dir / f"{script_name_only}.log"

    try:
        master_fd, slave_fd = pty.openpty()
        proc = subprocess.Popen(command, stdout=slave_fd, stderr=slave_fd, stdin=slave_fd,
                                 close_fds=True, start_new_session=True, env=get_clean_subprocess_env())
        os.close(slave_fd)

        running_games[script_name_only] = {
            "proc": proc, "log_path": log_path, "queue": queue.Queue(), "buffer": [],
            "window": None, "text_widget": None, "status_label": None, "finished": False,
        }
        threading.Thread(target=stream_output, args=(script_name_only, proc, master_fd, log_path), daemon=True).start()

        runner_label = f"{choice['runner']} ({choice['prefix_code']})" if choice.get("prefix_code") else choice["runner"]
        status_label.config(text=f"Launching {script_name_only} via {runner_label} in {launch_mode} mode...", fg=COLORS["success"])
    except FileNotFoundError:
        messagebox.showerror("Error", "Launcher command not found. Do you have 'sh' available?")
        status_label.config(text="Error: Launcher command not found.", fg=COLORS["danger"])
    except Exception as e:
        status_label.config(text=f"Error launching script: {str(e)}", fg=COLORS["danger"])


def add_script():
    exe_path = filedialog.askopenfilename(title="Select Windows Executable (.exe)",
                                           filetypes=[("Executable Files", "*.exe"), ("All Files", "*.*")])
    if not exe_path:
        return
    exe_path_obj = Path(exe_path)
    exe_name = exe_path_obj.stem
    new_name = simpledialog.askstring("Rename Script", "Enter script name (for display):", initialvalue=exe_name)
    if not new_name:
        return

    safe_new_name = "".join(c for c in new_name if c.isalnum() or c in (' ', '_', '-')).strip()
    if not safe_new_name:
        messagebox.showerror("Error", "Invalid script name.")
        return

    script_path = scripts_dir / f"{safe_new_name}.sh"
    folder_path = exe_path_obj.parent
    exe_resolved = exe_path_obj.resolve()
    folder_resolved = folder_path.resolve()
    default_wine_bin = get_default_wine_bin() or "wine"

    script_content = (
        "#!/bin/sh\n"
        f'cd "{folder_resolved}"\n'
        f'"{default_wine_bin}" "{exe_resolved}"\n'
    )
    try:
        with open(script_path, "w") as f:
            f.write(script_content)
        script_path.chmod(0o755)

        owning = find_owning_prefix(exe_resolved)
        status_extra = ""
        if owning:
            cfg_entry = {
                "runner": owning["runner"],
                "wine_bin": load_runners().get(owning["runner"], default_wine_bin),
                "prefix_code": owning["prefix_code"],
                "prefix_path": owning["prefix_path"],
                "launch_options": "", "comment": ""
            }
            with open(script_path, "w") as f:
                f.write(build_script_content(str(folder_resolved), str(exe_resolved), cfg_entry))
            script_path.chmod(0o755)

            runner_cfg = load_game_runner_config()
            runner_cfg[safe_new_name] = cfg_entry
            save_game_runner_config(runner_cfg)
            status_extra = f" (linked to existing prefix {owning['prefix_code']})"

        update_script_list()
        status_label.config(text=f"Added: {safe_new_name}{status_extra}", fg=COLORS["success"])
    except Exception as e:
        status_label.config(text=f"Error creating script: {str(e)}", fg=COLORS["danger"])


def remove_script():
    selected = tree.focus()
    if not selected:
        messagebox.showinfo("Info", "Please select a game first")
        return
    script_name = tree.item(selected, "values")[1]
    if not messagebox.askyesno("Confirm", f"Are you sure you want to remove '{script_name}'?"):
        return
    script_path = scripts_dir / f"{script_name}.sh"
    icon_path = icon_dir / f"{script_name}.png"
    try:
        script_path.unlink(missing_ok=True)
        icon_path.unlink(missing_ok=True)
        runner_cfg = load_game_runner_config()
        if script_name in runner_cfg:
            del runner_cfg[script_name]
            save_game_runner_config(runner_cfg)
        update_script_list()
        game_title_label.config(text="No Game Selected")
        icon_label.config(image='')
        icon_label.image = None
        info_text.set("Select a game to view details")
        status_label.config(text=f"Removed: {script_name}", fg=COLORS["warning"])
    except Exception as e:
        status_label.config(text=f"Error removing files: {str(e)}", fg=COLORS["danger"])


def rename_script():
    selected = tree.focus()
    if not selected:
        messagebox.showinfo("Info", "Please select a game first")
        return
    old_name = tree.item(selected, "values")[1]
    new_name_input = simpledialog.askstring("Rename Script", "Enter new script name:", initialvalue=old_name)
    if not new_name_input or new_name_input == old_name:
        return
    new_name = "".join(c for c in new_name_input if c.isalnum() or c in (' ', '_', '-')).strip()
    if not new_name:
        messagebox.showerror("Error", "Invalid new script name.")
        return

    old_path, new_path = scripts_dir / f"{old_name}.sh", scripts_dir / f"{new_name}.sh"
    old_icon, new_icon = icon_dir / f"{old_name}.png", icon_dir / f"{new_name}.png"
    try:
        if new_path.exists():
            messagebox.showerror("Error", f"Script '{new_name}' already exists.")
            return
        old_path.rename(new_path)
        if old_icon.exists():
            old_icon.rename(new_icon)
        runner_cfg = load_game_runner_config()
        if old_name in runner_cfg:
            runner_cfg[new_name] = runner_cfg.pop(old_name)
            save_game_runner_config(runner_cfg)
        update_script_list()
        for item in tree.get_children():
            if tree.item(item, "values")[1] == new_name:
                tree.focus(item)
                tree.selection_set(item)
                on_select()
                break
        status_label.config(text=f"Renamed to: {new_name}", fg=COLORS["success"])
    except Exception as e:
        status_label.config(text=f"Error renaming script: {str(e)}", fg=COLORS["danger"])


def change_icon():
    selected = tree.focus()
    if not selected:
        messagebox.showinfo("Info", "Please select a game first")
        return
    script_name = tree.item(selected, "values")[1]
    icon_path = filedialog.askopenfilename(title="Select Icon",
                                            filetypes=[("Image Files", "*.png *.jpg *.jpeg *.ico *.bmp"), ("All Files", "*.*")])
    if not icon_path:
        return
    try:
        image = Image.open(icon_path)
        if image.mode != 'RGBA':
            image = image.convert('RGBA')
        width, height = image.size
        new_size = min(width, height)
        left, top = (width - new_size) // 2, (height - new_size) // 2
        image = image.crop((left, top, left + new_size, top + new_size))
        image = image.resize((ICON_SIZE, ICON_SIZE), Image.LANCZOS)
        image.save(icon_dir / f"{script_name}.png", "PNG", quality=95)
        load_icon(script_name)
        status_label.config(text=f"Icon updated for {script_name}", fg=COLORS["success"])
    except Exception as e:
        messagebox.showerror("Error", f"Failed to process image: {str(e)}")
        status_label.config(text=f"Error processing image: {str(e)}", fg=COLORS["danger"])


def load_icon(script_name):
    icon_path = icon_dir / f"{script_name}.png"
    if icon_path.exists():
        try:
            image = Image.open(icon_path)
            if image.mode != 'RGBA':
                image = image.convert('RGBA')
            if image.size != (ICON_WIDTH, ICON_HEIGHT):
                image = image.resize((ICON_WIDTH, ICON_HEIGHT), Image.LANCZOS)
            photo = ImageTk.PhotoImage(image)
            icon_label.config(image=photo)
            icon_label.image = photo
        except Exception:
            icon_label.config(image='')
            icon_label.image = None
    else:
        icon_label.config(image='')
        icon_label.image = None


def on_select(event=None):
    def do_select():
        selected = tree.focus()
        if selected:
            script_name = tree.item(selected, "values")[1]
            game_title_label.config(text=script_name)
            load_icon(script_name)
            script_path = scripts_dir / f"{script_name}.sh"
            if script_path.exists():
                try:
                    stat = script_path.stat()
                    mod_time = datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
                    size_kb = stat.st_size / 1024
                    size_mb = size_kb / 1024
                    size_str = f"{size_mb:.2f} MB" if size_mb > 1 else (f"{size_kb:.2f} KB" if size_kb > 1 else f"{stat.st_size} bytes")
                    with open(script_path, 'r') as f:
                        lines = f.readlines()
                        folder_path = ""
                        if len(lines) >= 2:
                            folder_path = lines[1].strip().replace('cd "', '').replace('"', '')
                    info_text.set(f"Script File: {script_name}.sh\nLocation: {folder_path}\n"
                                  f"Last Modified: {mod_time}\nSize: {size_str}")
                except Exception as e:
                    info_text.set(f"File information unavailable: {e}")
            else:
                info_text.set("File information not available (script file missing)")
        else:
            game_title_label.config(text="No Game Selected")
            icon_label.config(image='')
            icon_label.image = None
            info_text.set("Select a game to view details")

    root.after(0, do_select)


# =======================================================================
# FILE MANAGER / FOLDER (dengan fallback untuk FreeBSD desktop minimal)
# =======================================================================
def open_path_in_file_manager(path_str):
    env = get_clean_subprocess_env()
    tried = ["xdg-open"] + ["pcmanfm", "thunar", "nautilus", "dolphin", "caja", "nemo", "xfe"]
    for fm in tried:
        try:
            subprocess.Popen([fm, path_str], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env)
            return True
        except FileNotFoundError:
            continue
    return False


def open_file_manager():
    selected = tree.focus()
    if not selected:
        messagebox.showinfo("Info", "Please select a game first")
        return
    script_name = tree.item(selected, "values")[1]
    script_path = scripts_dir / f"{script_name}.sh"
    if not script_path.exists():
        status_label.config(text=f"Error: Script file not found: {script_name}", fg=COLORS["danger"])
        return
    try:
        with open(script_path, 'r') as f:
            lines = f.readlines()
            folder_path = ""
            if len(lines) >= 2 and lines[1].strip().startswith("cd "):
                folder_path = lines[1].strip().replace('cd "', '').replace('"', '')
        if folder_path and Path(folder_path).is_dir():
            if open_path_in_file_manager(folder_path):
                status_label.config(text=f"Opening folder for {script_name}...", fg=COLORS["text_secondary"])
            else:
                messagebox.showerror("Error", "No file manager found.\nTry: pkg install xdg-utils pcmanfm")
        else:
            messagebox.showerror("Error", f"Folder path not found or invalid in script for {script_name}.")
    except Exception as e:
        status_label.config(text=f"Error opening file manager: {str(e)}", fg=COLORS["danger"])


def open_wine_prefix_folder():
    wine_prefix = os.environ.get("WINEPREFIX", str(Path.home() / ".wine"))
    if Path(wine_prefix).is_dir():
        if open_path_in_file_manager(wine_prefix):
            status_label.config(text="Opening Wine Prefix Folder...", fg=COLORS["text_secondary"])
        else:
            messagebox.showerror("Error", "No file manager found.\nTry: pkg install xdg-utils pcmanfm")
    else:
        messagebox.showerror("Error", f"Wine Prefix folder not found: {wine_prefix}")
        status_label.config(text="Error: Wine Prefix folder not found.", fg=COLORS["danger"])


def open_wlm_folder():
    if open_path_in_file_manager(str(directory)):
        status_label.config(text="Opening WLM folder...", fg=COLORS["text_secondary"])
    else:
        messagebox.showerror("Error", "No file manager found.\nTry: pkg install xdg-utils pcmanfm")


def open_winecfg():
    wine_bin = get_default_wine_bin()
    if not wine_bin:
        messagebox.showerror("Error", "No runner configured. Add one via Settings > Manage Runners...")
        return
    try:
        subprocess.Popen([sibling_tool(wine_bin, "winecfg")], stdout=subprocess.DEVNULL,
                          stderr=subprocess.DEVNULL, env=get_clean_subprocess_env())
        status_label.config(text="Opening Wine Configuration...", fg=COLORS["text_secondary"])
    except FileNotFoundError:
        messagebox.showerror("Error", "The 'winecfg' command was not found.")
        status_label.config(text="Error: winecfg not found.", fg=COLORS["danger"])


def run_exe_setup():
    exe_path = filedialog.askopenfilename(title="Select Setup Executable (.exe)",
                                           filetypes=[("Executable Files", "*.exe"), ("All Files", "*.*")])
    if not exe_path:
        return
    choice = ask_runner_choice(parent_script_name=None, purpose="setup")
    if choice is None:
        status_label.config(text="Setup cancelled.", fg=COLORS["text_secondary"])
        return
    try:
        env_vars, extra_args = parse_launch_options(choice.get("launch_options", ""))
        env = get_clean_subprocess_env()
        for key, val in env_vars:
            env[key] = val
        if choice.get("prefix_path"):
            env["WINEPREFIX"] = choice["prefix_path"]
        command = [choice["wine_bin"], exe_path] + extra_args
        subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env)
        label = f"{choice['runner']} (prefix: {choice['prefix_code']})" if choice.get("prefix_code") else choice["runner"]
        status_label.config(text=f"Running setup for {Path(exe_path).name} via {label}...", fg=COLORS["text_secondary"])
    except FileNotFoundError:
        messagebox.showerror("Error", "Runner command was not found.")
        status_label.config(text="Error: Runner command not found.", fg=COLORS["danger"])
    except Exception as e:
        status_label.config(text=f"Error running setup: {str(e)}", fg=COLORS["danger"])


def run_winetricks():
    wine_bin = get_default_wine_bin()
    if not wine_bin:
        messagebox.showerror("Error", "No runner configured. Add one via Settings > Manage Runners...")
        return
    env = get_clean_subprocess_env()
    env["WINE"] = wine_bin
    try:
        subprocess.Popen(["winetricks"], env=env)
        status_label.config(text="Opening Winetricks...", fg=COLORS["text_secondary"])
    except FileNotFoundError:
        messagebox.showerror("Error", "The 'winetricks' command was not found.\nTry: pkg install winetricks")
        status_label.config(text="Error: winetricks not found.", fg=COLORS["danger"])


def sort_by_selected(event=None):
    sort_value = sort_combo.get()
    if sort_value == "A-Z":
        update_script_list("ascending")
    elif sort_value == "Z-A":
        update_script_list("descending")


def on_theme_selected(event=None):
    selected_display = theme_combo.get()
    theme_name = None
    for key, data in THEMES.items():
        if data["name"] == selected_display:
            theme_name = key
            break
    if theme_name and theme_name != CURRENT_THEME:
        apply_theme(theme_name)


def on_launch_mode_selected(event=None):
    scale_entry.config(state="normal" if launch_mode_combo.get() == "GalliumHUD" else "disabled")


# =======================================================================
# INITIALIZATION
# =======================================================================
config = load_config()
CURRENT_THEME = config.get("theme", "default")
COLORS = THEMES.get(CURRENT_THEME, THEMES["default"])
load_runners()  # seed runners_config.json on first run

# =======================================================================
# MAIN WINDOW SETUP
# =======================================================================
root = tk.Tk()
root.title("Wine Launcher Manager - FreeBSD/BSD Edition")
root.protocol("WM_DELETE_WINDOW", lambda: (save_window_config(), root.destroy()))

style = ttk.Style()
style.theme_use('clam')

window_size = config["window_size"]
window_position = config["window_position"]
if window_position:
    root.geometry(f"{window_size}{window_position}")
else:
    width, height = map(int, window_size.split('x'))
    screen_width, screen_height = root.winfo_screenwidth(), root.winfo_screenheight()
    x = (screen_width // 2) - (width // 2)
    y = (screen_height // 2) - (height // 2)
    root.geometry(f"{width}x{height}+{x}+{y}")

root.resizable(True, True)
root.minsize(1000, 720)

# =======================================================================
# WIDGET CREATION
# =======================================================================
all_buttons = []

header_frame = ttk.Frame(root, padding=(15, 8))
header_frame.pack(fill=tk.X, side=tk.TOP)

title_label = tk.Label(header_frame, text="WINE LAUNCHER MANAGER (BSD)", font=FONTS["title"])
title_label.pack(side=tk.LEFT)

status_label = tk.Label(header_frame, text=f"Using {COLORS['name']} theme", font=FONTS["small"])
status_label.pack(side=tk.RIGHT)

toolbar = ttk.Frame(root, padding=(15, 5, 15, 0))
toolbar.pack(fill=tk.X, side=tk.TOP)

theme_label = ttk.Label(toolbar, text="Theme:", font=FONTS["normal"])
theme_label.pack(side=tk.LEFT, padx=(0, 5))

theme_names = [data["name"] for data in THEMES.values()]
theme_combo = ttk.Combobox(toolbar, values=theme_names, state="readonly", width=20, font=FONTS["normal"])
theme_combo.set(COLORS["name"])
theme_combo.pack(side=tk.LEFT, padx=(0, 15))
theme_combo.bind("<<ComboboxSelected>>", on_theme_selected)

settings_btn = ttk.Button(toolbar, text="SETTINGS", style="Custom.TButton")
all_buttons.append(settings_btn)
settings_btn.pack(side=tk.RIGHT)

settings_menu = tk.Menu(root, tearoff=0)
settings_menu.add_command(label="Wine Configuration (winecfg)", command=open_winecfg)
settings_menu.add_command(label="Open Wine Prefix Folder", command=open_wine_prefix_folder)
settings_menu.add_command(label="Uninstall Program",
                           command=lambda: subprocess.Popen([get_default_wine_bin() or "wine", "uninstaller"],
                                                             env=get_clean_subprocess_env()))
settings_menu.add_command(label="Wine Explorer",
                           command=lambda: subprocess.Popen([get_default_wine_bin() or "wine", "explorer"],
                                                             env=get_clean_subprocess_env()))
settings_menu.add_separator()
settings_menu.add_command(label="Manage Runners...", command=manage_runners_dialog)
settings_menu.add_command(label="Open WLM Folder", command=open_wlm_folder)
settings_menu.add_separator()
settings_menu.add_command(label="Refresh List", command=lambda: update_script_list())

_settings_menu_state = {"closed_at": 0.0}


def _on_settings_menu_closed(event=None):
    import time
    _settings_menu_state["closed_at"] = time.monotonic()


settings_menu.bind("<Unmap>", _on_settings_menu_closed)


def _on_global_click_closes_settings_menu(event):
    if not settings_menu.winfo_ismapped():
        return
    if event.widget is settings_menu:
        return
    settings_menu.unpost()


root.bind_all("<Button-1>", _on_global_click_closes_settings_menu, add="+")


def toggle_settings_menu():
    import time
    if time.monotonic() - _settings_menu_state["closed_at"] < 0.25:
        return
    settings_menu.post(settings_btn.winfo_rootx(), settings_btn.winfo_rooty() + settings_btn.winfo_height() + 5)


settings_btn.config(command=toggle_settings_menu)

# MAIN CONTENT
main_container = ttk.PanedWindow(root, orient=tk.HORIZONTAL)
main_container.pack(fill=tk.BOTH, expand=True, padx=15, pady=(0, 15))

left_panel = ttk.Frame(main_container, padding=(0, 0, 10, 0))
main_container.add(left_panel, weight=3)

controls_frame = ttk.Frame(left_panel)
controls_frame.pack(fill=tk.X, pady=(0, 8))

sort_label = ttk.Label(controls_frame, text="Sort:", font=FONTS["normal"])
sort_label.pack(side=tk.LEFT, padx=(0, 5))
sort_combo = ttk.Combobox(controls_frame, values=["A-Z", "Z-A"], state="readonly", width=8, font=FONTS["normal"])
sort_combo.current(0)
sort_combo.pack(side=tk.LEFT, padx=(0, 15))
sort_combo.bind("<<ComboboxSelected>>", sort_by_selected)

launch_label = ttk.Label(controls_frame, text="Launch Mode:", font=FONTS["normal"])
launch_label.pack(side=tk.LEFT, padx=(0, 5))
launch_mode_combo = ttk.Combobox(controls_frame, values=["Normal", "GalliumHUD"], state="readonly", width=12, font=FONTS["normal"])
launch_mode_combo.current(0)
launch_mode_combo.pack(side=tk.LEFT, padx=(0, 10))
launch_mode_combo.bind("<<ComboboxSelected>>", on_launch_mode_selected)

scale_label = ttk.Label(controls_frame, text="HUD Scale:", font=FONTS["normal"])
scale_label.pack(side=tk.LEFT, padx=(0, 5))
scale_entry = ttk.Entry(controls_frame, width=4, font=FONTS["normal"], state="disabled")
scale_entry.insert(0, "1")
scale_entry.pack(side=tk.LEFT)

tree_frame = ttk.Frame(left_panel)
tree_frame.pack(fill=tk.BOTH, expand=True)
tree_scroll = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL)
tree_scroll.pack(side=tk.RIGHT, fill=tk.Y)

tree = ttk.Treeview(tree_frame, columns=("No", "Game Name"), show="headings",
                     yscrollcommand=tree_scroll.set, selectmode="browse")
tree_scroll.config(command=tree.yview)
tree.heading("No", text="No", anchor="center")
tree.heading("Game Name", text="GAME NAME", anchor="w")
tree.column("#0", width=0, stretch=False)
tree.column("No", width=40, anchor="center", minwidth=40, stretch=False)
tree.column("Game Name", width=300, anchor="w", minwidth=200, stretch=True)
tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)


def on_tree_click(event):
    row_id = tree.identify_row(event.y)
    if not row_id:
        return
    if row_id in tree.selection():
        tree.selection_remove(row_id)
        tree.focus('')
        on_select()
        return "break"


tree.bind("<Button-1>", on_tree_click)
tree.bind("<<TreeviewSelect>>", on_select)

right_panel = ttk.Frame(main_container, padding=15)
main_container.add(right_panel, weight=1)

button_panel = ttk.Frame(right_panel, padding=(0, 10))
button_panel.pack(fill=tk.X, side=tk.BOTTOM)

icon_frame = ttk.Frame(right_panel, width=ICON_WIDTH, height=ICON_HEIGHT)
icon_frame.pack(pady=(0, 10))
icon_frame.pack_propagate(False)
icon_label = tk.Label(icon_frame, relief="flat")
icon_label.pack(expand=True, fill=tk.BOTH)

game_title_label = tk.Label(right_panel, text="No Game Selected", font=FONTS["subtitle"],
                             justify=tk.CENTER, wraplength=ICON_WIDTH)
game_title_label.pack(pady=(0, 8))

info_text = tk.StringVar(value="Select a game to view details")
info_label = tk.Label(right_panel, textvariable=info_text, font=FONTS["small"],
                       justify=tk.LEFT, wraplength=ICON_WIDTH + 50)
info_label.pack(pady=(0, 10))

btn_row1 = ttk.Frame(button_panel)
btn_row1.pack(pady=3)
play_btn = ttk.Button(btn_row1, text="PLAY", command=run_script, style="Custom.TButton", width=12)
all_buttons.append(play_btn)
play_btn.grid(row=0, column=0, padx=3, pady=3)
add_btn = ttk.Button(btn_row1, text="+ ADD", command=add_script, style="Custom.TButton", width=12)
all_buttons.append(add_btn)
add_btn.grid(row=0, column=1, padx=3, pady=3)
remove_btn = ttk.Button(btn_row1, text="REMOVE", command=remove_script, style="Custom.TButton", width=12)
all_buttons.append(remove_btn)
remove_btn.grid(row=0, column=2, padx=3, pady=3)

btn_row2 = ttk.Frame(button_panel)
btn_row2.pack(pady=3)
rename_btn = ttk.Button(btn_row2, text="RENAME", command=rename_script, style="Custom.TButton", width=12)
all_buttons.append(rename_btn)
rename_btn.grid(row=0, column=0, padx=3, pady=3)
icon_btn = ttk.Button(btn_row2, text="ICON", command=change_icon, style="Custom.TButton", width=12)
all_buttons.append(icon_btn)
icon_btn.grid(row=0, column=1, padx=3, pady=3)
filemanager_btn = ttk.Button(btn_row2, text="FOLDER", command=open_file_manager, style="Custom.TButton", width=12)
all_buttons.append(filemanager_btn)
filemanager_btn.grid(row=0, column=2, padx=3, pady=3)

btn_row3 = ttk.Frame(button_panel)
btn_row3.pack(pady=3)
logs_btn = ttk.Button(btn_row3, text="VIEW LOGS", command=view_logs, style="Custom.TButton", width=38)
all_buttons.append(logs_btn)
logs_btn.grid(row=0, column=0, padx=3, pady=3)

btn_row4 = ttk.Frame(button_panel)
btn_row4.pack(pady=3)
setup_btn = ttk.Button(button_panel, text="APPS SETUP", command=run_exe_setup, style="Custom.TButton", width=38)
all_buttons.append(setup_btn)
setup_btn.pack(pady=3)
winetricks_btn = ttk.Button(button_panel, text="WINETRICKS", command=run_winetricks, style="Custom.TButton", width=38)
all_buttons.append(winetricks_btn)
winetricks_btn.pack(pady=3)

# =======================================================================
# FINAL SETUP AND RUN
# =======================================================================
apply_theme(CURRENT_THEME)
update_script_list()
root.after(150, poll_log_queues)
root.mainloop()
