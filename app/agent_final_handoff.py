"""Draft-only final answer handoff using the agent's working conversation."""
from typing import Any, Callable


def conversation_final_messages(messages: list[dict[str, Any]], compact: Callable[..., None]) -> list[dict[str, Any]]:
    final_messages = [dict(message) for message in messages]
    compact(final_messages)
    final_messages.append({"role": "user", "content": (
        "You have reached the step limit. Using the evidence in the conversation, answer the question now. "
        "Do not call tools. Cite supporting passage IDs in square brackets. "
        "If the evidence does not answer the question, say so."
    )})
    return final_messages
