"""Opaque browser sessions with bounded input storage and idle expiration."""
from dataclasses import dataclass, field
import secrets
import threading
import time
import uuid

from . import config
from .engine import AnalysisEngine


class ServerBusy(ValueError):
    pass


@dataclass
class Workspace:
    engine: AnalysisEngine
    public_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    touched: float = 0
    active: int = 0
    input_bytes: int = 0
    reserved_bytes: int = 0


class SessionStore:
    def __init__(self, *, factory=AnalysisEngine, ttl=config.SESSION_TTL,
                 max_sessions=config.MAX_SESSIONS, budget=config.GLOBAL_INPUT_BYTES, clock=time.monotonic):
        self.factory, self.ttl, self.max_sessions, self.budget = factory, ttl, max_sessions, budget
        self.clock = clock
        self.lock = threading.RLock()
        self.workspaces: dict[str, Workspace] = {}

    def acquire(self, token):
        with self.lock:
            now = self.clock()
            for key, workspace in list(self.workspaces.items()):
                if not workspace.active and now - workspace.touched >= self.ttl:
                    del self.workspaces[key]
            workspace = self.workspaces.get(token)
            if workspace is None:
                if len(self.workspaces) >= self.max_sessions:
                    raise ServerBusy("The server is at its session limit. Please try again after an idle session expires.")
                token = secrets.token_urlsafe(32)
                engine = self.factory()
                workspace = Workspace(engine, touched=now, input_bytes=sum(r.size for r in engine.samples.values()))
                self.workspaces[token] = workspace
            workspace.active += 1
            workspace.touched = now
            return token, workspace

    def release(self, workspace):
        with self.lock:
            workspace.active -= 1
            workspace.touched = self.clock()

    def reserve(self, workspace, size):
        with self.lock:
            allocated = sum(w.input_bytes + w.reserved_bytes for w in self.workspaces.values())
            if allocated + size > self.budget:
                raise ValueError("The server's FCS input budget is full. Remove unused samples or try again later.")
            workspace.reserved_bytes += size

    def commit(self, workspace, reservation, added):
        with self.lock:
            workspace.reserved_bytes -= reservation
            workspace.input_bytes += added

    def subtract(self, workspace, size):
        with self.lock:
            workspace.input_bytes -= size
