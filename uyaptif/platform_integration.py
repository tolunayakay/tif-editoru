"""İşletim sistemi entegrasyonu: Windows dosya ilişkilendirmesi ve sağ tık menüsü.

Kayıtlar yalnızca geçerli kullanıcıya (HKCU) yazılır; yönetici yetkisi gerekmez.
Windows 10/11 varsayılan uygulamanın programla atanmasına izin vermediğinden,
kayıttan sonra "Varsayılan uygulamalar" ayar sayfası açılır.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from . import APP_ID, APP_NAME

PROG_ID = f"{APP_ID}.tif"
EXTENSIONS = (".tif", ".tiff")
MENU_KEY = APP_ID
MENU_TEXT = "TIFF Görüntüleyici ile Aç"

IS_WINDOWS = sys.platform == "win32"


def launch_command() -> tuple[str, str]:
    """(komut satırı, simge yolu)"""
    if getattr(sys, "frozen", False):
        exe = sys.executable
        return f'"{exe}" "%1"', exe
    pyw = Path(sys.executable).with_name("pythonw.exe")
    interp = str(pyw if pyw.exists() else sys.executable)
    main = Path(__file__).resolve().parent.parent / "main.py"
    return f'"{interp}" "{main}" "%1"', interp


def register_windows() -> None:
    import winreg

    cmd, icon = launch_command()
    root = winreg.HKEY_CURRENT_USER
    base = r"Software\Classes"

    def set_value(path: str, name: str | None, value: str) -> None:
        with winreg.CreateKeyEx(root, f"{base}\\{path}", 0, winreg.KEY_WRITE) as k:
            winreg.SetValueEx(k, name, 0, winreg.REG_SZ, value)

    set_value(PROG_ID, None, "UYAP TIFF Belgesi")
    set_value(PROG_ID, "FriendlyTypeName", "UYAP TIFF Belgesi")
    set_value(f"{PROG_ID}\\DefaultIcon", None, f'"{icon}",0')
    set_value(f"{PROG_ID}\\shell\\open\\command", None, cmd)

    exe_name = Path(icon).name
    set_value(f"Applications\\{exe_name}", "FriendlyAppName", APP_NAME)
    set_value(f"Applications\\{exe_name}\\shell\\open\\command", None, cmd)
    for ext in EXTENSIONS:
        set_value(f"{ext}\\OpenWithProgids", PROG_ID, "")
        set_value(f"Applications\\{exe_name}\\SupportedTypes", ext, "")
        menu = f"SystemFileAssociations\\{ext}\\shell\\{MENU_KEY}"
        set_value(menu, None, MENU_TEXT)
        set_value(menu, "Icon", f'"{icon}",0')
        set_value(f"{menu}\\command", None, cmd)
    _notify_shell()


def unregister_windows() -> None:
    import winreg

    root = winreg.HKEY_CURRENT_USER
    base = r"Software\Classes"
    _, icon = launch_command()
    exe_name = Path(icon).name
    for path in [PROG_ID, f"Applications\\{exe_name}"] + \
                [f"SystemFileAssociations\\{ext}\\shell\\{MENU_KEY}" for ext in EXTENSIONS]:
        _delete_tree(root, f"{base}\\{path}")
    for ext in EXTENSIONS:
        try:
            with winreg.OpenKey(root, f"{base}\\{ext}\\OpenWithProgids", 0, winreg.KEY_SET_VALUE) as k:
                winreg.DeleteValue(k, PROG_ID)
        except OSError:
            pass
    _notify_shell()


def _delete_tree(root, path: str) -> None:
    import winreg

    try:
        with winreg.OpenKey(root, path, 0, winreg.KEY_ALL_ACCESS) as k:
            while True:
                try:
                    child = winreg.EnumKey(k, 0)
                except OSError:
                    break
                _delete_tree(root, f"{path}\\{child}")
        winreg.DeleteKey(root, path)
    except OSError:
        pass


def _notify_shell() -> None:
    try:
        import ctypes
        ctypes.windll.shell32.SHChangeNotify(0x08000000, 0, None, None)  # SHCNE_ASSOCCHANGED
    except Exception:
        pass


def open_default_apps_settings() -> None:
    if IS_WINDOWS:
        os.startfile("ms-settings:defaultapps")
    elif sys.platform == "darwin":
        subprocess.Popen(["open", "-b", "com.apple.systempreferences"])
