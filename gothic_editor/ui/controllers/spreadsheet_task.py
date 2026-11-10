"""Background spreadsheet job with a single latest progress message and Tk polling."""
from concurrent.futures import ThreadPoolExecutor
from queue import Queue,Empty,Full


class SpreadsheetTask:
    def __init__(self,owner,on_progress,on_complete):
        self.owner,self.on_progress,self.on_complete=owner,on_progress,on_complete
        self.executor=ThreadPoolExecutor(max_workers=1,thread_name_prefix='xlsx')
        self.messages=Queue(maxsize=1)
        self.running=False
        self.poll_id=None

    def progress(self,*message):
        try:self.messages.put_nowait(message)
        except Full:
            try:self.messages.get_nowait()
            except Empty:pass
            try:self.messages.put_nowait(message)
            except Full:pass

    def start(self,operation):
        if self.running:return
        self.running=True
        self.future=self.executor.submit(operation,self.progress)
        self.poll_id=self.owner.after(40,self.poll)

    def poll(self):
        self.poll_id=None
        try:self.on_progress(*self.messages.get_nowait())
        except Empty:pass
        if not self.future.done():
            self.poll_id=self.owner.after(40,self.poll)
            return
        self.running=False
        try:result,error=self.future.result(),None
        except Exception as exc:result,error=None,str(exc)
        self.on_complete(result,error)

    def close(self):
        if self.poll_id is not None:self.owner.after_cancel(self.poll_id)
        self.executor.shutdown(wait=False,cancel_futures=True)
