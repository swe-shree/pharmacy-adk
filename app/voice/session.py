from dataclasses import dataclass
from typing import Any


@dataclass
class VoiceSession:
    session_id: str
    user_id: str
    live_session: Any = None
    active: bool = True