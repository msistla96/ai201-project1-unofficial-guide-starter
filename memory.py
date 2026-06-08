import logging 
from dataclasses import dataclass, field
from config import GROQ_API_KEY, UTILITY_MODEL
from groq import Groq

logger = logging.getLogger(__name__)
_client = Groq(api_key=GROQ_API_KEY)

@dataclass
class Turn:
    query: str
    answer: str


class ConversationMemory:
    """Stores the exchange history for a single conversation session."""

    def __init__(self, max_turns: int = 10):
        self.max_turns = max_turns
        self._turns: list[Turn] = []

    def add(self, query: str, answer: str):
        self._turns.append(Turn(query=query, answer=answer))
        # Trim oldest turns if we exceed the window
        if len(self._turns) > self.max_turns:
            self._turns = self._turns[-self.max_turns:]

    def to_messages(self) -> list[dict]:
        """Convert history to OpenAI-style message dicts for the LLM."""
        messages = []
        for turn in self._turns:
            messages.append({"role": "user", "content": turn.query})
            messages.append({"role": "assistant", "content": turn.answer})
        return messages

    def is_empty(self) -> bool:
        return len(self._turns) == 0

    def clear(self):
        self._turns = []

    def __len__(self):
        return len(self._turns)
    

    def rewrite_query(self, query: str, model= UTILITY_MODEL, llm_client=_client) -> str:
        """Rewrite a follow-up query into a standalone query using conversation history."""
        if self is None or len(self) == 0:
            return query  # no history, nothing to rewrite

        prompt = f"""\
        Given this conversation history:
        {self.to_messages()}

        Excluding sources, summarize rest of conversation not exceeding 100 words.

        Follow-up: {query}"""

        try:
            completion = llm_client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
            )
            rewritten = completion.choices[0].message.content.strip()
            logger.debug("Query rewrite: '%s' → '%s'", query, rewritten)
            return rewritten
        except Exception:
            logger.warning("Query rewrite failed, using original", exc_info=True)
            return query