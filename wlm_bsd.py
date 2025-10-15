#!/usr/bin/env python3
import os
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

SHORTCUT_DIR = os.path.expanduser("~/.local/share/wlm_shortcuts")
os.makedirs(SHORTCUT_DIR, exist_ok=True)


class WineLauncherManager:
    def __init__(self, root):
        self.root = root
        self.root.title("Wine Launcher Manager")
        self.root.geometry("520x470")
        self.root.configure(bg="#d9d9d9")

        tk.Label(
            root,
            text="Wine Launcher Manager",
            font=("Arial", 14, "bold"),
            bg="#d9d9d9"
        ).pack(pady=10)

        self.app_list = tk.Listbox(root, width=70, height=10, exportselection=False)
        self.app_list.pack(pady=5)
        self.load_shortcuts()
        self.app_list.bind("<<ListboxSelect>>", self.on_select)

        frame_radio = tk.Frame(root, bg="#d9d9d9")
        frame_radio.pack(pady=5)
        tk.Label(frame_radio, text="Runner:", bg="#d9d9d9").pack(side=tk.LEFT, padx=5)
        self.engine_choice = tk.StringVar(value="wine")
        tk.Radiobutton(frame_radio, text="Wine", variable=self.engine_choice, value="wine", bg="#d9d9d9").pack(side=tk.LEFT)
        tk.Radiobutton(frame_radio, text="Proton", variable=self.engine_choice, value="proton", bg="#d9d9d9").pack(side=tk.LEFT)

        frame_hud_border = ttk.LabelFrame(root, text="Counter FPS (Gallium HUD)")
        frame_hud_border.pack(fill="x", padx=10, pady=5)

        frame_hud = tk.Frame(frame_hud_border)
        frame_hud.pack(pady=5)

        tk.Label(frame_hud, text="Mode:").pack(side=tk.LEFT, padx=5)
        self.hud_mode = tk.StringVar(value="none")
        self.hud_dropdown = ttk.OptionMenu(frame_hud, self.hud_mode, "none", "none", "CPU, GPU, FPS")
        self.hud_dropdown.pack(side=tk.LEFT)

        tk.Label(frame_hud, text="Scale:").pack(side=tk.LEFT, padx=10)
        self.scale_entry = tk.Entry(frame_hud, width=5)
        self.scale_entry.insert(0, "1")
        self.scale_entry.pack(side=tk.LEFT)

        frame_btn_top = tk.Frame(root, bg="#d9d9d9")
        frame_btn_top.pack(pady=5)
        tk.Button(frame_btn_top, text="Add EXE", command=self.add_app, width=12).pack(side=tk.LEFT, padx=5)
        tk.Button(frame_btn_top, text="Setup", command=self.setup_app, width=12).pack(side=tk.LEFT, padx=5)
        tk.Button(frame_btn_top, text="Remove", command=self.remove_app, width=12).pack(side=tk.LEFT, padx=5)
        tk.Button(frame_btn_top, text="Launch", command=self.launch_app, width=12).pack(side=tk.LEFT, padx=5)
        
        frame_btn_bottom = tk.Frame(root, bg="#d9d9d9")
        frame_btn_bottom.pack(pady=5)
        tk.Button(frame_btn_bottom, text="Winetricks", command=self.run_winetricks, width=12).pack(side=tk.LEFT, padx=5)
        tk.Button(frame_btn_bottom, text="Exit", command=root.quit, width=12).pack(side=tk.LEFT, padx=5)

    def on_select(self, event):
        selection = self.app_list.curselection()
        if not selection:
            return
        self.current_selection = selection[0]

    def load_shortcuts(self):
        selected = self.app_list.curselection()
        index = selected[0] if selected else None
        self.app_list.delete(0, tk.END)
        for file in sorted(os.listdir(SHORTCUT_DIR)):
            if file.endswith(".sh"):
                self.app_list.insert(tk.END, file[:-3])
        if index is not None and index < self.app_list.size():
            self.app_list.selection_set(index)

    def add_app(self):
        exe_path = filedialog.askopenfilename(
            title="Select EXE file", filetypes=[("Windows Executable", "*.exe")]
        )
        if not exe_path:
            return
        exe_dir = os.path.dirname(exe_path)
        exe_file = os.path.basename(exe_path)
        name = os.path.splitext(exe_file)[0]
        runner = self.engine_choice.get()
        self.create_shortcut(name, exe_dir, exe_file, runner)
        self.load_shortcuts()
        messagebox.showinfo("Success", f"Game '{name}' added successfully!")

    def setup_app(self):
        exe_path = filedialog.askopenfilename(
            title="Select EXE file to run", filetypes=[("Windows Executable", "*.exe")]
        )
        if not exe_path:
            return
        exe_dir = os.path.dirname(exe_path)
        exe_file = os.path.basename(exe_path)
        runner = self.engine_choice.get()
        wine_cmd = (
            "/usr/local/wine-proton/bin/wine"
            if runner == "proton"
            else "/usr/local/bin/wine"
        )
        os.system(f'cd "{exe_dir}" && {wine_cmd} "{exe_file}" &')

    def create_shortcut(self, name, exe_dir, exe_file, runner):
        wine_cmd = (
            "/usr/local/wine-proton/bin/wine"
            if runner == "proton"
            else "/usr/local/bin/wine"
        )
        script_content = f"""#!/bin/sh
cd "{exe_dir}"
{wine_cmd} "{exe_file}"
"""
        shortcut_path = os.path.join(SHORTCUT_DIR, f"{name}.sh")
        with open(shortcut_path, "w") as f:
            f.write(script_content)
        os.chmod(shortcut_path, 0o755)

    def remove_app(self):
        selection = self.app_list.curselection()
        if not selection:
            messagebox.showwarning("Warning", "Select a game to remove.")
            return
        name = self.app_list.get(selection[0])
        path = os.path.join(SHORTCUT_DIR, f"{name}.sh")
        if os.path.exists(path):
            os.remove(path)
            self.load_shortcuts()

    def launch_app(self):
        selection = self.app_list.curselection()
        if not selection:
            messagebox.showwarning("Warning", "Select a game to launch.")
            return
        name = self.app_list.get(selection[0])
        shortcut_path = os.path.join(SHORTCUT_DIR, f"{name}.sh")
        if not os.path.exists(shortcut_path):
            messagebox.showerror("Error", "Shortcut file not found.")
            return

        hud_mode = self.hud_mode.get()
        scale_value = self.scale_entry.get().strip() or "1"
        with open(shortcut_path, "r") as f:
            content = f.read()

        lines = content.splitlines()
        new_lines = []
        for line in lines:
            if "/usr/local/bin/wine" in line or "/usr/local/wine-proton/bin/wine" in line:
                if hud_mode == "CPU, GPU, FPS":
                    line = f'GALLIUM_HUD="GPU-load+cpu+fps" GALLIUM_HUD_SCALE={scale_value} {line}'
            new_lines.append(line)

        with open(shortcut_path, "w") as f:
            f.write("\n".join(new_lines))

        os.system(f'sh "{shortcut_path}" &')

    def run_winetricks(self):
        runner = self.engine_choice.get()
        wine_path = (
            "/usr/local/wine-proton/bin/wine"
            if runner == "proton"
            else "/usr/local/bin/wine"
        )
        os.system(f'env WINE="{wine_path}" winetricks &')


if __name__ == "__main__":
    root = tk.Tk()
    app = WineLauncherManager(root)
    root.mainloop()
