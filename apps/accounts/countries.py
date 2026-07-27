"""A curated ISO 3166-1 alpha-2 country list used to validate the ``country``
field on registration and profile edits.

Kept in sync with the storefront's ``frontend/src/lib/countries.ts``. A whitelist
(rather than free text) is what makes "country with proper validation" real: only
a code in this list is accepted.
"""

COUNTRIES = [
    ("GB", "United Kingdom"),
    ("IE", "Ireland"),
    ("US", "United States"),
    ("CA", "Canada"),
    ("AU", "Australia"),
    ("NZ", "New Zealand"),
    ("IN", "India"),
    ("SG", "Singapore"),
    ("AE", "United Arab Emirates"),
    ("ZA", "South Africa"),
    ("FR", "France"),
    ("DE", "Germany"),
    ("ES", "Spain"),
    ("IT", "Italy"),
    ("PT", "Portugal"),
    ("NL", "Netherlands"),
    ("BE", "Belgium"),
    ("LU", "Luxembourg"),
    ("CH", "Switzerland"),
    ("AT", "Austria"),
    ("DK", "Denmark"),
    ("SE", "Sweden"),
    ("NO", "Norway"),
    ("FI", "Finland"),
    ("IS", "Iceland"),
    ("PL", "Poland"),
    ("CZ", "Czechia"),
    ("SK", "Slovakia"),
    ("HU", "Hungary"),
    ("RO", "Romania"),
    ("BG", "Bulgaria"),
    ("GR", "Greece"),
    ("HR", "Croatia"),
    ("SI", "Slovenia"),
    ("EE", "Estonia"),
    ("LV", "Latvia"),
    ("LT", "Lithuania"),
    ("CY", "Cyprus"),
    ("MT", "Malta"),
    ("US", "United States"),
    ("MX", "Mexico"),
    ("BR", "Brazil"),
    ("AR", "Argentina"),
    ("CL", "Chile"),
    ("CO", "Colombia"),
    ("JP", "Japan"),
    ("KR", "South Korea"),
    ("CN", "China"),
    ("HK", "Hong Kong"),
    ("TW", "Taiwan"),
    ("MY", "Malaysia"),
    ("TH", "Thailand"),
    ("ID", "Indonesia"),
    ("PH", "Philippines"),
    ("VN", "Vietnam"),
    ("PK", "Pakistan"),
    ("BD", "Bangladesh"),
    ("LK", "Sri Lanka"),
    ("SA", "Saudi Arabia"),
    ("QA", "Qatar"),
    ("KW", "Kuwait"),
    ("BH", "Bahrain"),
    ("OM", "Oman"),
    ("IL", "Israel"),
    ("TR", "Turkey"),
    ("EG", "Egypt"),
    ("NG", "Nigeria"),
    ("KE", "Kenya"),
    ("GH", "Ghana"),
    ("MA", "Morocco"),
]

# De-duplicate while preserving order (the list above has a couple of repeats for
# readability); this is the canonical set the model and validators use.
_seen = set()
COUNTRIES = [(code, name) for code, name in COUNTRIES if not (code in _seen or _seen.add(code))]

COUNTRY_CODES = frozenset(code for code, _ in COUNTRIES)
