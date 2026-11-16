"""Optional Groq-backed answer drafting for the Ask assistant."""
from app.services.llm.groq import chat_completion, groq_enabled

__all__ = ["chat_completion", "groq_enabled"]
