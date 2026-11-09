"""Supported potion use animations and import normalization."""

POTION_SCHEMES = (
    ('Выпить', '"POTION"'),
    ('Выпить быстро', '"POTIONFAST"'),
)
DEFAULT_POTION_SCHEME = POTION_SCHEMES[1][1]


def imported_potion_scheme(value):
    """Unknown imported animations use the first supported option."""
    return next((expression for _, expression in POTION_SCHEMES
                 if expression.casefold() == value.strip().casefold()), POTION_SCHEMES[0][1])
