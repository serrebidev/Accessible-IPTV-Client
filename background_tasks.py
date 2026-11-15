"""One daemon worker with a single replaceable pending task, no growing queue."""
import threading


class LatestTask:
    def __init__(self, dispatch):
        self.dispatch = dispatch
        self.condition = threading.Condition()
        self.version = 0
        self.pending = None
        self.closed = False
        self.thread = None

    def submit(self, work, completed):
        with self.condition:
            if self.closed:
                return
            self.version += 1
            self.pending = (self.version, work, completed)
            if self.thread is None:
                self.thread = threading.Thread(target=self._run, daemon=True, name='LibraryWorker')
                try:
                    self.thread.start()
                except RuntimeError:
                    self.thread = None
                    self.pending = None
                    raise
            self.condition.notify()

    def close(self):
        with self.condition:
            self.closed = True
            self.version += 1
            self.pending = None
            self.condition.notify_all()

    def _run(self):
        while True:
            with self.condition:
                self.condition.wait_for(lambda: self.closed or self.pending is not None)
                if self.closed:
                    return
                version, work, completed = self.pending
                self.pending = None
            def canceled():
                return self.closed or version != self.version
            result, error = None, None
            try:
                result = work(canceled)
            except Exception as exc:
                error = exc
            if not canceled():
                def deliver(result=result, error=error, completed=completed, version=version):
                    if not self.closed and version == self.version:
                        completed(result, error)
                self.dispatch(deliver)
