"""Optional native Bink 1 decoder using the DLL supplied by the user's Gothic II.

Never ship/copy the game's DLL. Verify PE architecture before loading it to avoid
Windows 32/64-bit loader failures. The preview is video-only (no sound output).
"""
import ctypes
from pathlib import Path
import struct
import sys

class BinkError(ValueError):
    pass


class _BinkHeader(ctypes.Structure):
    _fields_ = [
        ('width',ctypes.c_uint32),('height',ctypes.c_uint32),
        ('frames',ctypes.c_uint32),('frame_num',ctypes.c_uint32),
        ('last_frame_num',ctypes.c_uint32),('rate',ctypes.c_uint32),
        ('rate_div',ctypes.c_uint32),
    ]


def dll_compatible(path, bits=None):
    """Check a real PE DLL's CPU type without loading untrusted or wrong-arch code."""
    if bits is None:bits=struct.calcsize('P')*8
    try:
        with Path(path).open('rb') as stream:
            if stream.read(2)!=b'MZ':return False
            stream.seek(0x3c)
            pointer=struct.unpack('<I',stream.read(4))[0]
            if pointer<64 or pointer>1048576:return False
            stream.seek(pointer)
            if stream.read(4)!=b'PE\\0\\0':return False
            machine=struct.unpack('<H',stream.read(2))[0]
        return machine==(0x14c if bits==32 else 0x8664)
    except (OSError,struct.error):
        return False


def game_decoder_path(game):
    if sys.platform!='win32' or game is None:return None
    root=Path(game)
    for path in (root/'System'/'binkw32.dll',root/'binkw32.dll'):
        if path.is_file():return path
    return None


class BinkDecoder:
    """Frame-at-a-time decoder; the caller owns the Tk event loop."""
    def __init__(self, game, video):
        if sys.platform!='win32':
            raise BinkError('Встроенный BIK-плеер доступен только на Windows.')
        library=game_decoder_path(game)
        if library is None:
            raise BinkError('В установленной Gothic не найдена binkw32.dll.')
        if not dll_compatible(library):
            raise BinkError('Библиотека Gothic имеет другую разрядность. '
                            'Для встроенного просмотра нужен редактор той же разрядности (обычно 32-битный).')
        # Bink 1 SDK exports stdcall symbols; only the user-installed game DLL is used.
        try:
            dll=ctypes.WinDLL(str(library))
            handle_type=ctypes.c_void_p
            dll.BinkOpen.argtypes=[ctypes.c_char_p,ctypes.c_uint32]
            dll.BinkOpen.restype=handle_type
            dll.BinkClose.argtypes=[handle_type]
            dll.BinkClose.restype=None
            dll.BinkDoFrame.argtypes=[handle_type]
            dll.BinkDoFrame.restype=ctypes.c_int
            dll.BinkCopyToBuffer.argtypes=[
                handle_type,ctypes.c_void_p,ctypes.c_int,ctypes.c_uint32,
                ctypes.c_uint32,ctypes.c_uint32,ctypes.c_uint32]
            dll.BinkCopyToBuffer.restype=ctypes.c_int
            dll.BinkNextFrame.argtypes=[handle_type]
            dll.BinkNextFrame.restype=None
            dll.BinkWait.argtypes=[handle_type]
            dll.BinkWait.restype=ctypes.c_int
        except (OSError,AttributeError) as exc:
            raise BinkError('Библиотека Gothic не поддерживает нужные функции Bink.') from exc
        self.dll=dll
        self.handle=None
        self.video=Path(video)
        try:encoded=str(self.video).encode('mbcs')
        except UnicodeError as exc:
            raise BinkError('Путь к видео не поддерживается Bink.') from exc
        handle=dll.BinkOpen(encoded,0)
        if not handle:raise BinkError('Bink не смог открыть видео.')
        self.handle=handle
        header=ctypes.cast(handle,ctypes.POINTER(_BinkHeader)).contents
        self.width,self.height=header.width,header.height
        self.frames=header.frames
        self.rate,self.rate_div=header.rate,header.rate_div
        if (not 1<=self.width<=4096 or not 1<=self.height<=4096
                or self.width*self.height>8_388_608 or
                not 1<=self.frames<=200_000):
            self.close()
            raise BinkError('Некорректные размеры или длительность BIK.')
        self.buffer=ctypes.create_string_buffer(self.width*self.height*3)
        self.number=0

    @property
    def interval_ms(self):
        return max(15,min(1000,round(1000*self.rate_div/max(1,self.rate))))

    def next_frame(self):
        if self.handle is None:return None
        if self.number>=self.frames:return None
        self.dll.BinkDoFrame(self.handle)
        # BINKSURFACE24 is 24-bit BGR on Windows.
        self.dll.BinkCopyToBuffer(
            self.handle,self.buffer,self.width*3,self.height,0,0,1)
        data=bytearray(self.buffer.raw[:self.width*self.height*3])
        data[0::3],data[2::3]=data[2::3],data[0::3]
        self.number+=1
        if self.number<self.frames:self.dll.BinkNextFrame(self.handle)
        return bytes(data)

    def close(self):
        if self.handle is not None:
            self.dll.BinkClose(self.handle)
            self.handle=None

