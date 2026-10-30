"""Sample authority terms and languages, and a small stand-in for CollectionSpace's date parser (the BMU's lookups)."""
from __future__ import annotations

import calendar
import re
from typing import Any

from .store import Store

PEOPLE = ["Madeleine W. Fang", "Leslie Freund", "Natasha Johnson", "Michael T. Black", "Linda Waterfield",
          "Zachary Williams"]
ORGS = ["Phoebe A. Hearst Museum of Anthropology", "University of California at Berkeley Regents"]
# A few terms of the languages vocabulary (the real one is much longer).
LANGUAGES = {"eng": "English", "spa": "Spanish", "fre": "French", "ger": "German", "chi": "Chinese", "jpn": "Japanese",
             "haw": "Hawaiian", "nav": "Navajo"}
# Short identifiers the BMU's tests and examples have always used; other terms get one made from the name.
SHORT_IDS = {"Leslie Freund": "7475"}


def domain(store: Store) -> str:
    """The museum's CollectionSpace domain, as refNames carry it."""
    return f"{store.museum}.cspace.berkeley.edu"


def short(name: str) -> str:
    return SHORT_IDS.get(name) or re.sub(r"[^A-Za-z0-9]", "", name) + "1400000000000"


def shown(store: Store, name: str) -> str:
    """A term's display name now (a renamed term keeps its short identifier)."""
    return store.term_renames.get(short(name), name)


def ref(store: Store, service: str, vocab: str, name: str) -> str:
    return f"urn:cspace:{domain(store)}:{service}:name({vocab}):item:name({short(name)})'{shown(store, name)}'"


def term_names(service: str) -> list[str]:
    return PEOPLE if service == "personauthorities" else ORGS


def language_name(store: Store, code: str) -> str:
    return store.language_renames.get(code, LANGUAGES[code])


def language_ref(store: Store, code: str) -> str:
    return f"urn:cspace:{domain(store)}:vocabularies:name(languages):item:name({code})'{language_name(store, code)}'"


_MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
           "november", "december"]
Day = tuple[int, int, int]


def parse_date(store: Store, text: str) -> dict[str, Any] | None:
    """A small stand-in for CollectionSpace's date parser (it understands far more): the structured date, or None."""
    t, certainty = text.strip(), ""
    if m := re.match(r"^(?:circa|ca\.?|c\.)\s*(.+)$", t, re.I):
        certainty, t = "approximate", m.group(1)

    def day(y: int, mo: int, d: int) -> Day | None:
        return (y, mo, d) if 1 <= mo <= 12 and 1 <= d <= calendar.monthrange(y, mo)[1] else None

    early: Day | None = None
    late: Day | None = None
    if m := re.match(r"^(\d{4})-(\d{2})-(\d{2})$", t):
        early = late = day(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    elif m := re.match(r"^(\d{4})-(\d{2})$", t):
        y, mo = int(m.group(1)), int(m.group(2))
        if 1 <= mo <= 12:
            early, late = (y, mo, 1), (y, mo, calendar.monthrange(y, mo)[1])
    elif m := re.match(r"^(\d{4})$", t):
        y = int(m.group(1))
        early, late = (y, 1, 1), (y, 12, 31)
    elif m := re.match(r"^(\d{3}0)s$", t):
        y = int(m.group(1))
        early, late = (y, 1, 1), (y + 9, 12, 31)
    elif (m := re.match(r"^(\d{4})\s*(?:-|–|to)\s*(\d{4})$", t, re.I)) and int(m.group(2)) >= int(m.group(1)):
        early, late = (int(m.group(1)), 1, 1), (int(m.group(2)), 12, 31)
    elif (m := re.match(r"^([A-Za-z]+)\s+(\d{1,2}),?\s+(\d{4})$", t)) and m.group(1).lower() in _MONTHS:
        early = late = day(int(m.group(3)), _MONTHS.index(m.group(1).lower()) + 1, int(m.group(2)))
    if not early or not late:
        return None
    era = f"urn:cspace:{domain(store)}:vocabularies:name(dateera):item:name(ce)'CE'"
    group: dict[str, Any] = {
        "dateDisplayDate": text, "dateEarliestSingleYear": early[0], "dateEarliestSingleMonth": early[1],
        "dateEarliestSingleDay": early[2], "dateEarliestSingleEra": era, "dateLatestYear": late[0],
        "dateLatestMonth": late[1], "dateLatestDay": late[2], "dateLatestEra": era,
        "dateEarliestScalarValue": f"{early[0]:04d}-{early[1]:02d}-{early[2]:02d}T00:00:00.000Z",
        "dateLatestScalarValue": f"{late[0]:04d}-{late[1]:02d}-{late[2]:02d}T00:00:00.000Z",
        "scalarValuesComputed": "true"}
    if certainty:
        group["dateEarliestSingleCertainty"] = group["dateLatestCertainty"] = certainty
    return group
