import re

# Legal suffixes to strip, order matters (longer first to avoid partial matches)
_LEGAL_SUFFIXES = re.compile(
    r',?\s+(?:Inc\.?|LLC|Ltd\.?|GmbH|Pty(?:\s+Ltd)?|B\.?V\.?|S\.?A\.?|AB)\.?$',
    re.IGNORECASE,
)

def normalize_company(name: str) -> str:
    """Lowercase, collapse whitespace, strip legal suffixes. Idempotent."""
    name = ' '.join(name.strip().split())
    name = _LEGAL_SUFFIXES.sub('', name)
    return name.lower().strip()


# Countries we can detect from common patterns in job location strings
_COUNTRY_HINTS = {
    'usa': 'US', 'united states': 'US', 'u.s.': 'US', 'u.s.a.': 'US', 'us only': 'US',
    'uk': 'GB', 'united kingdom': 'GB', 'u.k.': 'GB',
    'canada': 'CA', 'germany': 'DE', 'france': 'FR', 'australia': 'AU',
    'netherlands': 'NL', 'spain': 'ES', 'brazil': 'BR', 'india': 'IN',
    'poland': 'PL', 'portugal': 'PT', 'sweden': 'SE', 'switzerland': 'CH',
    'austria': 'AT', 'italy': 'IT', 'romania': 'RO', 'ukraine': 'UA',
    'argentina': 'AR', 'mexico': 'MX', 'colombia': 'CO', 'nigeria': 'NG',
    'kenya': 'KE', 'south africa': 'ZA', 'new zealand': 'NZ', 'singapore': 'SG',
    'japan': 'JP', 'israel': 'IL', 'turkey': 'TR',
}

_REMOTE_PATTERN = re.compile(
    r'\bremote\b|\banywhere\b|\bworldwide\b|\bglobal\b|\bwork from home\b|\bwfh\b',
    re.IGNORECASE,
)

# "City, Country" — two comma-separated tokens
_CITY_COUNTRY_PATTERN = re.compile(r'^([^,]+),\s*(.+)$')


def normalize_location(text: str) -> dict:
    """
    Parse a free-text location string.

    Returns:
        {
            'is_remote': bool,
            'country': str | None,   # ISO 3166-1 alpha-2
            'city': str | None,
            'raw': str               # original text, always preserved
        }
    """
    raw = text.strip()
    cleaned = ' '.join(raw.split())
    lower = cleaned.lower()

    is_remote = bool(_REMOTE_PATTERN.search(lower))

    country = None
    city = None

    # Try longest match first so "united states" beats "us"
    for hint in sorted(_COUNTRY_HINTS, key=len, reverse=True):
        if hint in lower:
            country = _COUNTRY_HINTS[hint]
            break

    # Try "City, Country" pattern if no city found yet
    m = _CITY_COUNTRY_PATTERN.match(cleaned)
    if m:
        candidate_city = m.group(1).strip()
        candidate_country_text = m.group(2).strip().lower()
        # Only treat left side as city if it doesn't look like a remote keyword
        if not _REMOTE_PATTERN.search(candidate_city):
            city = candidate_city
        if country is None:
            country = _COUNTRY_HINTS.get(candidate_country_text)

    return {'is_remote': is_remote, 'country': country, 'city': city, 'raw': raw}


_SKILL_NORMALISE = re.compile(r'[^a-z0-9]+')


def normalize_skill(raw: str) -> str:
    """Lowercase, strip non-alphanumeric, collapse to single key. Idempotent."""
    return _SKILL_NORMALISE.sub('', raw.lower().strip())


_TITLE_NORMALISE = re.compile(r'[^a-z0-9 ]+')


def normalize_title(title: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace. Idempotent."""
    return ' '.join(_TITLE_NORMALISE.sub(' ', title.lower()).split())
