"""Comment drafts in the founder's voice for a LinkedIn post he pastes into Telegram (/comment <post text>).
He reads the drafts and pastes the one he likes by hand; nothing is posted from here."""
from . import gemini

USAGE = ("Paste the post after the command, like this:\n/comment <the text of the LinkedIn post>\n\n"
         "I answer with two short comments in your voice. You paste the one you like.")

VOICE = """You write LinkedIn comments for Sanjeev Gulia: a finance leader (IIM, CIMA affiliate, CA finalist) with
eighteen years across manufacturing floors, trading desks and boardrooms on three continents, now building ScoreMyBiz,
a money-health app for small shops, from Lagos.

Rules for every comment:
- Under 60 words. Plain English. Specific to what the post says; quote or paraphrase one point from it.
- Never open with praise like "Great post", "Love this", "Well said", "Spot on". Start with the substance.
- No em-dash, no hashtags, no emojis, no exclamation marks, no made-up numbers or statistics.
- Sound like a peer adding to the conversation, not a fan.

Write exactly two comments:
1. ADD: one that adds a concrete observation from his experience in manufacturing, trading or small business.
2. ASK: one that ends with a genuine question for the author.

Format exactly:
ADD:
<comment>

ASK:
<comment>
"""


def prompt(post_text: str) -> str:
    return f"{VOICE}\nThe post:\n\"\"\"\n{post_text.strip()}\n\"\"\"\n"


def drafts(post_text: str, *, ask=gemini.ask) -> str:
    """Two comment drafts, or the usage line when nothing was pasted. Never raises."""
    if not post_text or len(post_text.strip()) < 20:
        return USAGE
    try:
        out = ask(prompt(post_text), max_tokens=400)
    except Exception as e:                                   # noqa: BLE001  the bot must always answer
        return f"Could not draft right now ({type(e).__name__}: {str(e)[:120]}). Try again in a few minutes."
    return out.strip() or "The model returned nothing. Send the post again."
