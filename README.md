# WLM - Wine Launch Manager BSD Version
Wine Launch Manager, is a python3 based application for managing vanilla wine applications on BSD (FreeBSD).
## Screenshot
![Screenshot WLM](./1.png)
---

## How to Use WLM?

### **Before Using, Ensure:**

1. You have installed Wine Vanilla or ProtonGE & winetricks correctly according to your BSD (Tested in FreeBSD & GhostBSD).
2. You have installed the following Python packages:
   - `python3-tkinter`
   *(Use the commands below or adjust according to your distribution.)*

---

### **Install the required components or packages (Debian-Based, adjust for other distros):**

```bash
$ sudo pkg update
$ sudo pkg install py3x-tkinter
```
## Note: py3x is version python, chek using command
```bash
$ python3 --version
```
---

## Steps to Run WLM:

1. Download the latest version of WLM.
2. Open a terminal in the directory where the file has been downloaded (e.g., `~/Downloads`).
3. Make it excutable using command:
   ```bash
   $ chmod +x wlm_bsd.py
   ```
4. Excute using terminal or you can create shortcut link to desktop.

---

## WLM Menu
![Screenshot WLM](./2.png)
---

## Features:

- Manage Vanilla Wine applications via a user-friendly GUI.
- Integrate Winetricks for additional Wine configurations.
- Uninstall applications installed within Wine.
- Display FPS using GalliumHUD.
- Create and manage shortcut lists in the Launcher.
---
![Screenshot WLM](./1.png)
## How to Play?
1. **Runner**: Select Runner Option (Wine or Proton).
2. **Counter FPS**: For Counter FPS using GalliumHUD.
3. **Remove Button**: Deletes an application from the shortcut list, Mode for Enable Gallium Hud & Scale for ajust size HUD.
4. **Add Exe**: Adds an application to the shortcut list menu (.exe file).
5. **Setup**: Open Setup your windows apps (.*exe).
6. **Remove**: Remove Shortcut (not Uninstall).
7. **Launch**: Launch or Run Apps.
8. **Add Exe**: Runs the application that has been added to the shortcut list.
9. **Winetricks**: Open Winetricks to manage Wine or Proton.
10. **Exit**: Exit WLM.

## How to Uninstall WLM?

### **Safer Method (File Manager):**

Simply delete the `wlm` directory using your file manager

---

