from __future__ import annotations
from typing import List, Dict, Any
from pydantic import BaseModel

class Message(BaseModel):
    role: str  # "user" | "assistant" | "system"
    content: str

class Step(BaseModel):
    provider: str
    model: str
    messages: List[Message]

class Turn(BaseModel):
    user_input: str

    def plan(self) -> List[Step]:  # naive planner
        return [
            Step(
                provider="openai",
                model="gpt-3.5-turbo",
                messages=[Message(role="user", content=self.user_input)],
            )
        ]