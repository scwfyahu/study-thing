"""Export flashcards to CSV and Anki .apkg."""
import csv
import hashlib
import io
import re
import tempfile
from pathlib import Path


def cards_to_csv(cards: list[tuple[str, str]]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["question", "answer"])
    w.writerows(cards)
    return buf.getvalue()


def cards_to_apkg(cards: list[tuple[str, str]], deck_name: str, tags: list[str] | None = None) -> Path:
    import genanki

    model = genanki.Model(
        1749284721,
        "StudyThing QA",
        fields=[{"name": "Question"}, {"name": "Answer"}],
        templates=[
            {
                "name": "Card 1",
                "qfmt": "{{Question}}",
                "afmt": "{{FrontSide}}<hr id=answer>{{Answer}}",
            }
        ],
    )
    deck_id = int(hashlib.sha1(deck_name.encode("utf-8")).hexdigest()[:12], 16) % (1 << 62)
    deck = genanki.Deck(deck_id, deck_name)
    # genanki forbids spaces in tags
    safe_tags = [re.sub(r"\s+", "_", t).strip("_") for t in (tags or []) if str(t).strip()]
    for q, a in cards:
        deck.add_note(genanki.Note(model=model, fields=[q, a], tags=safe_tags))
    out = Path(tempfile.mkdtemp(prefix="studything_")) / "deck.apkg"
    genanki.Package(deck).write_to_file(str(out))
    return out