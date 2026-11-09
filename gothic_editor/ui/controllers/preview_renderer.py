"""One render in flight, one latest request; all Tk work stays on the owning thread."""
from concurrent.futures import ProcessPoolExecutor
from multiprocessing import get_context

from gothic_editor.core.preview_worker import render_frame


class PreviewRenderer:
    def __init__(self, owner, on_frame, on_error):
        self.owner,self.on_frame,self.on_error = owner,on_frame,on_error
        self._executor = None
        self._future = None
        self._running_key = None
        self._worker_revision = None
        self._latest = None
        self._poll_id = None
        self._closed = False

    def request(self, key, mesh, textures, parameters):
        if self._closed:return
        self._latest = (key,mesh,textures,parameters)
        if self._future is None:self._start()

    def discard_requested(self):
        self._latest = None

    def _start(self):
        if self._latest is None or self._closed:return
        key,mesh,textures,parameters = self._latest
        try:
            if self._executor is None:
                self._executor = ProcessPoolExecutor(max_workers=1,mp_context=get_context('spawn'))
            scene = (mesh,textures) if self._worker_revision!=key[0] else None
            self._future = self._executor.submit(render_frame,scene,parameters)
            self._worker_revision = key[0]
            self._running_key = key
            self._poll_id = self.owner.after(16,self._poll)
        except (OSError,RuntimeError) as exc:
            self._future = None
            self.on_error(key,exc)

    def _poll(self):
        self._poll_id = None
        if self._closed:return
        if not self._future.done():
            self._poll_id = self.owner.after(16,self._poll)
            return
        future,key = self._future,self._running_key
        self._future = None
        try:self.on_frame(key,future.result())
        except Exception as exc:self.on_error(key,exc)
        if self._latest is not None and self._latest[0]!=key:self._start()

    def close(self):
        self._closed = True
        self._latest = None
        if self._poll_id is not None:
            self.owner.after_cancel(self._poll_id)
            self._poll_id = None
        if self._executor is not None:
            terminate = getattr(self._executor,'terminate_workers',None)
            if terminate is not None:terminate()
            else:self._executor.shutdown(wait=False,cancel_futures=True)
            self._executor = None
