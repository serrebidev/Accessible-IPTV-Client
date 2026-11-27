"""One daemon worker with a single replaceable pending task, no growing queue."""
import threading


def start_operation(owner, name, work, completed, dispatch):
    """One in-flight operation per owner/key; writes are never silently replaced.

    Called on the UI thread. Work receives no wx objects. Confirmed writes finish
    after window closure; only delivery is suppressed. No periodic work is added.
    """
    active = getattr(owner, '_background_operations', None)
    if active is None:
        active = owner._background_operations = set()
    if name in active:
        return False
    active.add(name)

    def deliver(result, error):
        active.discard(name)
        if not getattr(owner, 'closed', False) and bool(owner):
            completed(result, error)

    def run():
        try:
            result, error = work(), None
        except Exception as exc:
            result, error = None, exc
        dispatch(deliver, result, error)
    try:
        threading.Thread(target=run, name='IPTV-' + name, daemon=True).start()
    except RuntimeError as error:
        deliver(None, error)
    return True


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

    def cancel(self):
        with self.condition:
            self.version += 1
            self.pending = None

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
