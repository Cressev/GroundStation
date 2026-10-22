"""Latest-only stereo worker; GUI and network never wait for SGBM."""

import threading


class StereoWorker:
    """Own a single in-flight calculation and one pending input/output slot."""

    def __init__(self):
        """Start an idle daemon without opening cameras or network connections."""
        self.condition = threading.Condition()
        self.model = None
        self.enabled = True
        self.generation = 0
        self.pending = self.output = None
        self.closed = False
        self.thread = threading.Thread(target=self._run, daemon=True, name='local-stereo')
        self.thread.start()

    def set_model(self, model):
        """Invalidate old frames when a connection supplies its calibration."""
        with self.condition:
            self.model = model
            self.generation += 1
            self.pending = self.output = None

    def invalidate(self, enabled=None):
        """Cancel queued and in-flight results without blocking the GUI."""
        with self.condition:
            self.generation += 1
            self.pending = self.output = None
            if enabled is not None:
                self.enabled = enabled

    def submit(self, metadata, jpeg):
        """Replace an obsolete pending pair instead of building latency."""
        with self.condition:
            if not self.closed and self.model is not None:
                self.pending = (self.generation, self.model, self.enabled, metadata, jpeg)
                self.condition.notify()

    def take_latest(self):
        """Consume a completed snapshot at the GUI's own refresh cadence."""
        with self.condition:
            result, self.output = self.output, None
            return result

    def _run(self):
        """Compute outside the lock and discard obsolete generation results."""
        while True:
            with self.condition:
                self.condition.wait_for(lambda: self.closed or self.pending is not None)
                if self.closed:
                    return
                generation, model, enabled, metadata, jpeg = self.pending
                self.pending = None
            try:
                result = model.process_jpeg(jpeg, metadata, enabled)
            except Exception as exc:
                result = {'error': str(exc)}
            with self.condition:
                if not self.closed and generation == self.generation:
                    self.output = result

    def close(self):
        """Discard all results and request shutdown without a GUI-thread join."""
        with self.condition:
            self.closed = True
            self.pending = self.output = self.model = None
            self.condition.notify_all()
