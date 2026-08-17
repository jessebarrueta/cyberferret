"""Pure control helpers.

No hardware, no I/O, no global state. Everything here is a plain function of
its arguments so it can be reasoned about and tested on a laptop.
"""


def clamp(value, low, high):
    return max(low, min(high, value))


def approach(current, target, amount):
    """Move `current` toward `target` by at most `amount`."""

    if current < target:
        return min(current + amount, target)

    if current > target:
        return max(current - amount, target)

    return current


def low_pass(previous, value, alpha):
    """Single-pole filter. `None` inputs mean "no measurement yet"."""

    if value is None:
        return previous

    if previous is None:
        return value

    return previous * (1.0 - alpha) + value * alpha
