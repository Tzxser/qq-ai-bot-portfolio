import time


class SessionPolicy:
    """Bounded group conversation policy; long-term memory stays opt-in."""

    def __init__(self, recent_turns=3, history_chars=6400, idle_ttl=1800, absolute_ttl=7200):
        self.recent_turns = recent_turns
        self.history_chars = history_chars
        self.idle_ttl = idle_ttl
        self.absolute_ttl = absolute_ttl
        self.started = {}
        self.touched = {}
        self.cleared = set()

    def active(self, key, now=None):
        now = time.time() if now is None else now
        if key in self.cleared:
            self.cleared.discard(key)
            self.started[key] = now
            self.touched[key] = now
            return False
        started = self.started.get(key)
        touched = self.touched.get(key)
        if started is None:
            self.started[key] = now
            self.touched[key] = now
            return True
        if now - touched > self.idle_ttl or now - started > self.absolute_ttl:
            self.clear(key)
            self.started[key] = now
            self.touched[key] = now
            return False
        self.touched[key] = now
        return True

    def trim(self, history):
        result = list(history[-(self.recent_turns * 2):])
        while result and sum(len(item.get("content", "")) for item in result) > self.history_chars:
            result = result[2:]
        return result

    def clear(self, key):
        self.started.pop(key, None)
        self.touched.pop(key, None)
        self.cleared.add(key)
