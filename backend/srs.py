"""Anki-style SM-2 spaced repetition scheduler (simplified)."""
import datetime


def apply_rating(card: dict, rating: str, today: datetime.date) -> dict:
    """Return updated scheduler fields for a card given a rating."""
    ease = float(card.get("ease") or 2.5)
    interval = int(card.get("interval_days") or 0)
    reps = int(card.get("reps") or 0)
    lapses = int(card.get("lapses") or 0)

    if rating == "again":
        if reps > 0:
            lapses += 1
        ease = max(1.3, ease - 0.2)
        interval = 0  # due again today
    elif rating == "hard":
        interval = max(1, int(round(interval * 1.2)) + 1 if interval else 1)
        ease = max(1.3, ease - 0.05)
    elif rating == "good":
        interval = 1 if reps == 0 else max(1, round(interval * ease))
    elif rating == "easy":
        ease = min(3.0, ease + 0.15)
        interval = 4 if reps == 0 else max(1, round(interval * ease * 1.3))
    else:
        raise ValueError(f"unknown rating {rating!r}")

    reps += 1
    due = today + datetime.timedelta(days=interval)
    return {
        "ease": round(ease, 2),
        "interval_days": int(interval),
        "reps": reps,
        "lapses": lapses,
        "due_date": due.isoformat(),
    }