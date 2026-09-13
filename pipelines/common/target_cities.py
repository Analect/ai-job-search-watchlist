"""Single source of truth for which cities this watchlist targets.

Add a new city here to extend collection scope everywhere it applies -
the shared gazetteer (location_normalize.py) and any adapter capable of
a server-side location pre-filter (Workday's `locations` facet,
Eightfold's `location=` query param) all read from this list, so a new
entry takes effect across every consumer without hunting through each
one individually. "London or Dublin" is always OR semantics - each
city is an independent match target, never a combined location.
"""

TARGET_CITIES: dict[str, tuple[str, str]] = {
    # lowercase city name -> (region, country)
    "london": ("England", "United Kingdom"),
    "dublin": ("Leinster", "Ireland"),
}

# lowercase alias segment -> canonical key in TARGET_CITIES
CITY_ALIASES: dict[str, str] = {
    "greater london": "london",
    # Fidelity International: "Cannon Street Office" — no comma, city name absent;
    # the building name "Cannon Street" is a well-known City of London address.
    "cannon street": "london",
}
