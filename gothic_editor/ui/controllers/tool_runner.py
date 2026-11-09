import queue
from concurrent.futures import ThreadPoolExecutor
from gothic_editor.core.localization import tr

class ToolRunner:
    def __init__(self, scheduler, append, on_complete):
        self.scheduler = scheduler
        self.append = append
        self.on_complete = on_complete
        self.running = False
        self.messages = queue.Queue()
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='project-tools')
        self.on_progress = lambda _:None

    def start(self, title, operation, log_path=None):
        if self.running:
            return
        self.running = True
        self.log_path = log_path
        self.append('\n' + title)
        self.future = self.executor.submit(operation, self.messages.put)
        self.scheduler.after(50, self.poll)

    def poll(self):
        while True:
            try:
                message=self.messages.get_nowait()
                self.append(message)
                self.on_progress(message)
            except queue.Empty:
                break
        if not self.future.done():
            self.scheduler.after(50, self.poll)
            return
        success, result, error = False, None, None
        try:
            result = self.future.result()
            success = True
        except Exception as exc:
            error = str(exc)
        if self.log_path is not None and self.log_path.is_file():
            try:
                with self.log_path.open('rb') as stream:
                    stream.seek(max(0, self.log_path.stat().st_size - 128 * 1024))
                    self.append(stream.read().decode('utf-8', errors='replace'))
            except OSError as exc:
                self.append(str(exc))
        if success:
            if getattr(result,'archive',None) is not None:
                self.append(tr('item_assets.archive_result',path=str(result.archive)))
            operation=getattr(result,'operation','compile' if self.log_path is not None else 'sync')
            key={'compile':'tools.compile_success','sync':'tools.sync_success','launch':'pipeline.launch_success'}[operation]
            if getattr(result,'manual',False):self.append(tr('pipeline.manual_launch',name=result.output.name))
            self.append(tr(key,path=str(result.output),count=result.files,warnings=result.warnings))
            if result.backup is not None:
                self.append(tr('tools.backup',path=str(result.backup)))
        else:
            self.append(error)
        self.running = False
        self.on_complete(success, result)

    def close(self):
        self.executor.shutdown(wait=False, cancel_futures=True)
