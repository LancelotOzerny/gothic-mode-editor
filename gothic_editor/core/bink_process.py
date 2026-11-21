"""Play Bink videos on 64-bit Python using Windows' built-in 32-bit PowerShell.

The helper loads only the user's existing Gothic binkw32.dll in a separate
32-bit process. It streams raw BGR frames through stdout to a bounded queue.
The editor UI never loads a foreign-architecture DLL or calls a blocking read.
"""
from pathlib import Path
from queue import Queue, Empty
import os
import struct
import subprocess
import tempfile
import threading

from .bink_decoder import BinkError, game_decoder_path, dll_compatible

_POWERSHELL = r"""
$ErrorActionPreference='Stop'
try {
Add-Type -TypeDefinition @'
using System;
using System.IO;
using System.Runtime.InteropServices;
using System.Text;
public static class GothicBinkBridge {
    [DllImport("kernel32.dll", CharSet=CharSet.Unicode, SetLastError=true)]
    static extern IntPtr LoadLibraryW(string name);
    [DllImport("kernel32.dll", CharSet=CharSet.Ansi, SetLastError=true)]
    static extern IntPtr GetProcAddress(IntPtr module, string name);
    [DllImport("kernel32.dll")] static extern bool FreeLibrary(IntPtr module);
    [UnmanagedFunctionPointer(CallingConvention.StdCall, CharSet=CharSet.Ansi)]
    delegate IntPtr Open(string path, uint flags);
    [UnmanagedFunctionPointer(CallingConvention.StdCall)]
    delegate void Close(IntPtr handle);
    [UnmanagedFunctionPointer(CallingConvention.StdCall)]
    delegate int DoFrame(IntPtr handle);
    [UnmanagedFunctionPointer(CallingConvention.StdCall)]
    delegate void NextFrame(IntPtr handle);
    [UnmanagedFunctionPointer(CallingConvention.StdCall)]
    delegate int Copy(IntPtr handle, byte[] pixels, int pitch,
        uint height, uint x, uint y, uint flags);
    static T Function<T>(IntPtr module, string name, int argbytes) where T: class {
        IntPtr pointer=GetProcAddress(module, name);
        if(pointer==IntPtr.Zero)pointer=GetProcAddress(module, "_"+name+"@"+argbytes);
        if(pointer==IntPtr.Zero)throw new InvalidOperationException("Bink export not found: "+name);
        return (T)(object)Marshal.GetDelegateForFunctionPointer(pointer,typeof(T));
    }
    public static void Run(string dll, string video) {
        if(IntPtr.Size!=4)throw new InvalidOperationException("Requires 32-bit PowerShell.");
        IntPtr module=LoadLibraryW(dll);
        if(module==IntPtr.Zero)throw new InvalidOperationException("Unable to load Gothic Bink DLL.");
        IntPtr handle=IntPtr.Zero;
        try {
            Open open=Function<Open>(module,"BinkOpen",8);
            Close close=Function<Close>(module,"BinkClose",4);
            DoFrame decode=Function<DoFrame>(module,"BinkDoFrame",4);
            Copy copy=Function<Copy>(module,"BinkCopyToBuffer",28);
            NextFrame next=Function<NextFrame>(module,"BinkNextFrame",4);
            try {
                handle=open(video,0);
                if(handle==IntPtr.Zero)throw new InvalidOperationException("Bink could not open video.");
                uint width=(uint)Marshal.ReadInt32(handle,0);
                uint height=(uint)Marshal.ReadInt32(handle,4);
                uint frames=(uint)Marshal.ReadInt32(handle,8);
                uint fps=(uint)Marshal.ReadInt32(handle,20);
                uint divisor=(uint)Marshal.ReadInt32(handle,24);
                if(width<1||height<1||width>4096||height>4096||
                   (ulong)width*height>8388608UL||frames<1||frames>200000)
                    throw new InvalidOperationException("Invalid Bink frame dimensions.");
                uint interval=(uint)Math.Max(15,Math.Min(1000,
                    Math.Round(1000.0*divisor/Math.Max(1.0,(double)fps))));
                Stream output=Console.OpenStandardOutput();
                BinaryWriter writer=new BinaryWriter(output);
                writer.Write(width);writer.Write(height);
                writer.Write(frames);writer.Write(interval);
                byte[] pixels=new byte[checked((int)(width*height*3))];
                for(uint frame=0;frame<frames;frame++) {
                    decode(handle);
                    copy(handle,pixels,checked((int)(width*3)),height,0,0,1);
                    // Bink's 24-bit surface is BGR; parent converts for Tk.
                    writer.Write(pixels);
                    writer.Flush();
                    if(frame+1<frames)next(handle);
                }
            } finally {
                if(handle!=IntPtr.Zero)close(handle);
            }
        } finally {
            FreeLibrary(module);
        }
    }
}
'@ -ErrorAction Stop
[GothicBinkBridge]::Run($env:GOTHIC_BINK_DLL, $env:GOTHIC_BINK_VIDEO)
} catch {
    [Console]::Error.WriteLine($_.Exception.ToString())
    exit 1
}
"""


def powershell_32bit():
    """WoW64 powershell.exe is x86 even when the editor runs as x64."""
    base=Path(os.environ.get('WINDIR', r'C:\Windows'))
    executable=base/'SysWOW64'/'WindowsPowerShell'/'v1.0'/'powershell.exe'
    return executable if executable.is_file() else None


class BinkProcessDecoder:
    """Asynchronously produces frames, retaining at most two decoded frames."""
    def __init__(self, game, video):
        dll=game_decoder_path(game)
        shell=powershell_32bit()
        if dll is None:
            raise BinkError('В Gothic не найдена binkw32.dll.')
        if not dll_compatible(dll,32):
            raise BinkError('Для BIK нужна 32-битная binkw32.dll.')
        if shell is None:
            raise BinkError('Не найден встроенный 32-битный PowerShell Windows.')
        self.width=self.height=self.frames=0
        self.interval=40
        self.number=0
        self.error=None
        self.finished=False
        self.queue=Queue(maxsize=2)
        self._closing=threading.Event()
        self._temp=tempfile.TemporaryDirectory(prefix='gothic-bink-')
        script=Path(self._temp.name)/'decode.ps1'
        script.write_text(_POWERSHELL,encoding='utf-8-sig')
        env=os.environ.copy()
        env['GOTHIC_BINK_DLL']=str(dll)
        env['GOTHIC_BINK_VIDEO']=str(Path(video).resolve())
        self.process=subprocess.Popen(
            [str(shell),'-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass',
             '-File',str(script)],
            stdout=subprocess.PIPE,stderr=subprocess.PIPE,
            env=env,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        self._reader=threading.Thread(target=self._read,daemon=True)
        self._reader.start()

    @staticmethod
    def _exact(stream,length):
        parts=[]
        while length>0:
            chunk=stream.read(length)
            if not chunk:raise EOFError('Поток декодера BIK завершился.')
            parts.append(chunk)
            length-=len(chunk)
        return b''.join(parts)

    def _read(self):
        try:
            header=self._exact(self.process.stdout,16)
            self.width,self.height,self.frames,self.interval=struct.unpack('<4I',header)
            if (not 1<=self.width<=4096 or not 1<=self.height<=4096 or
                    self.width*self.height>8388608 or
                    not 1<=self.frames<=200000 or not 15<=self.interval<=1000):
                raise BinkError('Неверный заголовок потока BIK.')
            size=self.width*self.height*3
            for i in range(self.frames):
                if self._closing.is_set():break
                pixels=bytearray(self._exact(self.process.stdout,size))
                pixels[0::3],pixels[2::3]=pixels[2::3],pixels[0::3]
                while not self._closing.is_set():
                    try:
                        self.queue.put(bytes(pixels),timeout=.1)
                        break
                    except Exception:
                        continue
        except (OSError,EOFError,ValueError) as exc:
            if not self._closing.is_set():
                self.error=str(exc)
        finally:
            self.finished=True

    @property
    def interval_ms(self):
        return self.interval

    def next_frame(self):
        if self.error:raise BinkError(self.error)
        try:
            frame=self.queue.get_nowait()
        except Empty:
            return None if self.finished else False
        self.number+=1
        return frame

    def close(self):
        self._closing.set()
        if self.process.poll() is None:
            self.process.kill()
        try:self.process.communicate(timeout=2)
        except (OSError,subprocess.TimeoutExpired):pass
        self._reader.join(timeout=.5)
        self._temp.cleanup()
