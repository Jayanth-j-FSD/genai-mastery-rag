"""Tokens to money, with prices you state (Week 10).

The free tier bills nothing, so "what does this cost?" has no answer until you pick a price. A provider
charges separately for the text you send (input tokens) and the text the model writes (output tokens), per million
tokens, and output costs more. An agent run is mostly input, because every step re-sends the conversation so far, so
the input price decides most of the bill.

There is no price table in this project on purpose. A table would go stale and would be a guess that looks like a
fact. Prices come from the settings (PRICE_INPUT_PER_MILLION, PRICE_OUTPUT_PER_MILLION) or from arguments, and any
saved result records the ones it used, labelled as an assumption. With no price stated a cost is `None`, never 0:
unknown is not free.
"""
from app.config import settings

ASSUMPTION = "an assumption you state, not a bill: the free tier charges nothing"


def current_prices():
    """The (input, output) dollars per million tokens from the settings. (0.0, 0.0) means unpriced."""
    return settings.price_input_per_million, settings.price_output_per_million


def is_priced(input_per_m=None, output_per_m=None):
    """True when at least one price is stated (an argument wins over the setting)."""
    input_per_m, output_per_m = _resolve(input_per_m, output_per_m)
    return input_per_m > 0 or output_per_m > 0


def cost_of(prompt_tokens, completion_tokens, input_per_m=None, output_per_m=None):
    """Dollars for this many tokens at the stated prices, or None when no price is stated."""
    if prompt_tokens < 0 or completion_tokens < 0:
        raise ValueError(f"token counts cannot be negative, got {prompt_tokens} and {completion_tokens}")
    input_per_m, output_per_m = _resolve(input_per_m, output_per_m)
    if input_per_m <= 0 and output_per_m <= 0:
        return None
    return (prompt_tokens * input_per_m + completion_tokens * output_per_m) / 1_000_000


def describe_prices(input_per_m=None, output_per_m=None):
    """One line saying which prices a cost used, so a number never travels without them."""
    input_per_m, output_per_m = _resolve(input_per_m, output_per_m)
    if input_per_m <= 0 and output_per_m <= 0:
        return ("no price stated, so cost is not reported (pass --price-in, --price-out and --price-source "
                "to scripts/race_team.py --show)")                      # the PRICE_* settings are not read by the race report
    return (f"${input_per_m:g} per million input tokens and ${output_per_m:g} per million output tokens "
            f"({ASSUMPTION})")


def _resolve(input_per_m, output_per_m):
    """Fill a missing price from the settings and refuse a negative one."""
    default_in, default_out = current_prices()
    input_per_m = default_in if input_per_m is None else input_per_m
    output_per_m = default_out if output_per_m is None else output_per_m
    if not (0 <= input_per_m < float("inf") and 0 <= output_per_m < float("inf")):
        raise ValueError(f"a price must be 0 or more (dollars per million tokens), got {input_per_m} and {output_per_m}")
    return float(input_per_m), float(output_per_m)
