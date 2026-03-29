"""
agent/critic.py — pydantic-ai agents for generating player critiques.

Uses Claude (claude-haiku-4-5-20251001) via pydantic-ai.

Agents:
- critic_agent: Takes a DailyStats object and returns a CritiqueOutput.
  System prompt: toxic R6 coach who roasts stats in German, brutal but funny.
- lazy_day_agent: Returns a LazyDayOutput when all players have delta=0.
  System prompt: generates a varied German insult for zero-activity days.

Models:
- DailyStats: Input model with all per-player daily delta data.
- CritiqueOutput: Structured roast (headline, critique text, verdict, rating).
- LazyDayOutput: The @everyone insult message for lazy days.
"""

from pydantic import BaseModel
from pydantic_ai import Agent
from pydantic_ai.models.anthropic import AnthropicModel
from pydantic_ai.providers.anthropic import AnthropicProvider
from config import settings


# ---------------------------------------------------------------------------
# Input / output Pydantic models
# ---------------------------------------------------------------------------

class DailyStats(BaseModel):
    """All data needed by the critic agent to roast a player."""
    username: str
    platform: str
    rank: str
    rank_delta: int          # Change in rank points vs. today's baseline snapshot
    kills: int               # Kills accumulated today
    deaths: int              # Deaths accumulated today
    kd_today: float          # Kill/death ratio for today's session
    wins: int                # Wins today
    losses: int              # Losses today
    most_played_operator: str
    operator_rounds: int     # Rounds played with the most-played operator today


class CritiqueOutput(BaseModel):
    """Structured critique returned by the critic agent."""
    headline: str   # Bold embed title, e.g. "Absolute Katastrophe"
    critique: str   # 2–4 sentences of roasting in German
    verdict: str    # One short verdict phrase, e.g. "Absolute Bodenplatte"
    rating: int     # 1–10 performance rating (1 = worst)


class LazyDayOutput(BaseModel):
    """Returned by lazy_day_agent when nobody played today."""
    message: str    # Full @everyone message in German, varied daily


class QuoteOutput(BaseModel):
    """Returned by quote_agent — a single R6-themed quote."""
    quote: str      # The quote itself
    operator: str   # The operator the quote is attributed to


# ---------------------------------------------------------------------------
# Agent definitions
# ---------------------------------------------------------------------------

# Toxic R6 coach agent — roasts a player's daily stats
critic_agent: Agent[None, CritiqueOutput] = Agent(
    model=AnthropicModel("claude-haiku-4-5-20251001", provider=AnthropicProvider(api_key=settings.anthropic_api_key)),
    output_type=CritiqueOutput,
    system_prompt=(
        "Du bist ein toxischer Rainbow Six Siege Coach. "
        "Deine Aufgabe ist es, die Tagesstatistiken eines Spielers brutal, "
        "aber auf humorvolle Weise auf Deutsch zu kommentieren. "
        "Sei sarkastisch, direkt und gnadenlos ehrlich. "
        "Benutze Siege-Slang und Gaming-Begriffe. "
        "Dein Kommentar soll aus 2-4 Sätzen bestehen. "
        "Der 'headline' soll ein kurzer, reißerischer Titel sein (max. 8 Wörter). "
        "Der 'verdict' soll eine kurze, vernichtende Schlussbeurteilung sein (max. 5 Wörter). "
        "Das 'rating' ist eine Zahl von 1 (komplette Katastrophe) bis 10 (unerwartet gut). "
        "Sei kreativ, abwechslungsreich und verwende verschiedene Beleidigungen."
    ),
)

# Quote agent — generates a random R6-operator-style quote
quote_agent: Agent[None, QuoteOutput] = Agent(
    model=AnthropicModel("claude-haiku-4-5-20251001", provider=AnthropicProvider(api_key=settings.anthropic_api_key)),
    output_type=QuoteOutput,
    system_prompt=(
        "Du bist ein Rainbow Six Siege Operator. "
        "Generiere ein einziges, authentisches Zitat im Stil eines R6-Operators. "
        "Das Zitat soll taktisch, dramatisch oder motivierend klingen — auf Englisch, "
        "wie die echten Operator-Zitate im Spiel. "
        "Wähle zufällig einen echten R6-Operator (z.B. Sledge, Ash, Thermite, Jäger, Caveira, "
        "Vigil, Echo, Hibana, Maestro, Bandit, etc.) und schreibe das Zitat in dessen Charakter. "
        "Das Zitat soll 1-2 Sätze lang sein. Sei kreativ und variiere den Stil."
    ),
)

# Lazy-day agent — generates a varied @everyone taunt when nobody played
lazy_day_agent: Agent[None, LazyDayOutput] = Agent(
    model=AnthropicModel("claude-haiku-4-5-20251001", provider=AnthropicProvider(api_key=settings.anthropic_api_key)),
    output_type=LazyDayOutput,
    system_prompt=(
        "Du bist ein zynischer Discord-Bot für eine Rainbow Six Siege Gruppe. "
        "Heute hat KEINER der registrierten Spieler Siege gespielt. "
        "Generiere eine wütende, beleidigende @everyone-Nachricht auf Deutsch. "
        "Variiere täglich: manchmal enttäuscht, manchmal wütend, manchmal sarkastisch. "
        "Erwähne, dass sie alle faule Kartoffeln sind, die lieber Fortnite spielen "
        "oder auf der Couch sitzen. Sei kreativ, lustig und lass es brennen. "
        "Die Nachricht soll 2-4 Sätze lang sein und @everyone am Anfang enthalten. "
        "Erfinde gerne neue Schimpfwörter oder Kombinationen."
    ),
)
