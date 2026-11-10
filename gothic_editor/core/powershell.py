"""An owned, persistent PowerShell session. Reader threads never access Tk."""
import base64
import os
from pathlib import Path
from queue import Queue
import shutil
import subprocess
from threading import Thread
import uuid


class PowerShellSession:
    def __init__(self,cwd):
        self.cwd=Path(cwd)
        self.events=Queue(maxsize=4096)
        self.process=None
        self.running=False
        self.marker='__GE_'+uuid.uuid4().hex+'__'
        self.closed=False
        self._stop_thread=None

    def _start(self):
        executable=shutil.which('pwsh') or shutil.which('powershell')
        if not executable:raise OSError('PowerShell не найден в PATH')
        self.process=subprocess.Popen([executable,'-NoLogo','-NoProfile','-NonInteractive','-Command','-'],
            cwd=self.cwd,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,
            text=True,encoding='utf-8',errors='replace',bufsize=1,
            creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        initialization=("[Console]::InputEncoding = New-Object System.Text.UTF8Encoding($false); "
            "[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false); "
            "$OutputEncoding = [Console]::OutputEncoding; $ProgressPreference = 'SilentlyContinue'; "
            "if ($PSVersionTable.PSVersion.Major -ge 7) { $PSStyle.OutputRendering = 'PlainText' }\n")
        self.process.stdin.write(initialization)
        self.process.stdin.flush()
        Thread(target=self._read,daemon=True,name='powershell-output').start()

    def execute(self,command):
        if self.running:raise ValueError('Дождитесь завершения команды или остановите её')
        if self.closed:raise ValueError('Сессия закрыта')
        if self.process is None:self._start()
        encoded=base64.b64encode(command.encode('utf-16-le')).decode('ascii')
        # Dot sourcing preserves variables and Set-Location between commands.
        script=("try { . ([ScriptBlock]::Create([Text.Encoding]::Unicode.GetString("
            "[Convert]::FromBase64String('"+encoded+"')))) | Out-Default } "
            "catch { $_ | Out-String | Write-Output } finally { "
            "[Console]::Out.WriteLine('"+self.marker+"' + [Convert]::ToBase64String("
            "[Text.Encoding]::UTF8.GetBytes((Get-Location).Path))); [Console]::Out.Flush() }\n")
        self.running=True
        try:
            self.process.stdin.write(script)
            self.process.stdin.flush()
        except (OSError,ValueError):
            self.running=False
            raise

    def _emit(self,event):
        # Bounded output applies backpressure while allowing shutdown to unblock.
        from queue import Full
        while not self.closed:
            try:self.events.put(event,timeout=.1);return
            except Full:continue

    def _read(self):
        try:
            for line in self.process.stdout:
                text=line.rstrip('\r\n')
                if self.marker in text:
                    before,encoded=text.split(self.marker,1)
                    if before:self._emit(('output',before))
                    try:cwd=base64.b64decode(encoded).decode('utf-8')
                    except (ValueError,UnicodeError):cwd=str(self.cwd)
                    self._emit(('done',cwd))
                else:self._emit(('output',text))
        finally:
            self._emit(('exit',self.process.wait()))

    def close(self):
        if self.closed:return self._stop_thread
        self.closed=True
        self.running=False
        process=self.process
        if process is None:return
        def terminate():
            if process.poll() is None:
                if os.name=='nt':
                    subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'],
                        stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
                        creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
                else:process.terminate()
                try:process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
            for stream in (process.stdin,process.stdout):
                try:stream.close()
                except (OSError,ValueError):pass
        worker=Thread(target=terminate,name='powershell-stop')
        self._stop_thread=worker
        worker.start()
        return worker
