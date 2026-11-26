"""Windows integration for the otherwise borderless Tk welcome window."""
import os


def show_in_taskbar(window):
    if os.name != 'nt':return
    import ctypes
    from ctypes import wintypes

    user32=ctypes.WinDLL('user32',use_last_error=True)
    user32.GetParent.argtypes=[wintypes.HWND]
    user32.GetParent.restype=wintypes.HWND
    user32.GetWindowLongW.argtypes=[wintypes.HWND,ctypes.c_int]
    user32.GetWindowLongW.restype=ctypes.c_long
    user32.SetWindowLongW.argtypes=[wintypes.HWND,ctypes.c_int,ctypes.c_long]
    user32.SetWindowLongW.restype=ctypes.c_long
    user32.SetWindowPos.argtypes=[wintypes.HWND,wintypes.HWND,ctypes.c_int,ctypes.c_int,
                                 ctypes.c_int,ctypes.c_int,wintypes.UINT]
    user32.SetWindowPos.restype=wintypes.BOOL
    handle=user32.GetParent(window.winfo_id()) or window.winfo_id()
    style=user32.GetWindowLongW(handle,-20)  # GWL_EXSTYLE
    style=(style | 0x00040000) & ~0x00000080  # APPWINDOW instead of TOOLWINDOW
    ctypes.set_last_error(0)
    if not user32.SetWindowLongW(handle,-20,style) and ctypes.get_last_error():
        raise ctypes.WinError(ctypes.get_last_error())
    # Refresh the native frame without moving or resizing the Tk window.
    if not user32.SetWindowPos(handle,None,0,0,0,0,0x0001|0x0002|0x0004|0x0010|0x0020):
        raise ctypes.WinError(ctypes.get_last_error())
    # Re-register the borderless root window in the Windows taskbar.
    window.withdraw()
    window.deiconify()


def move_window(window, x, y):
    """Move across Windows monitors including negative desktop coordinates."""
    if os.name != 'nt':
        window.geometry(f'+{x}+{y}')
        return
    import ctypes
    from ctypes import wintypes
    user32 = ctypes.WinDLL('user32', use_last_error=True)
    user32.GetParent.argtypes = [wintypes.HWND]
    user32.GetParent.restype = wintypes.HWND
    user32.SetWindowPos.argtypes = [wintypes.HWND,wintypes.HWND,ctypes.c_int,ctypes.c_int,
                                  ctypes.c_int,ctypes.c_int,wintypes.UINT]
    user32.SetWindowPos.restype = wintypes.BOOL
    handle = user32.GetParent(window.winfo_id()) or window.winfo_id()
    if not user32.SetWindowPos(handle,None,int(x),int(y),0,0,0x0001|0x0004|0x0010):
        raise ctypes.WinError(ctypes.get_last_error())
