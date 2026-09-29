"""Client country names in Russian, for the feed card and Telegram pings."""

# ponytail: the client countries we actually see; anything else stays in English.
COUNTRY_RU = {
    "United States": "США", "USA": "США", "United Kingdom": "Великобритания", "Canada": "Канада",
    "Australia": "Австралия", "New Zealand": "Новая Зеландия", "Ireland": "Ирландия",
    "United Arab Emirates": "ОАЭ", "Saudi Arabia": "Саудовская Аравия", "Qatar": "Катар",
    "Kuwait": "Кувейт", "Israel": "Израиль", "Turkey": "Турция", "Singapore": "Сингапур",
    "India": "Индия", "Pakistan": "Пакистан", "Philippines": "Филиппины", "Indonesia": "Индонезия",
    "Malaysia": "Малайзия", "Japan": "Япония", "Hong Kong": "Гонконг", "China": "Китай",
    "Nigeria": "Нигерия", "Kenya": "Кения", "Egypt": "Египет", "South Africa": "ЮАР",
    "Germany": "Германия", "France": "Франция", "Italy": "Италия", "Spain": "Испания",
    "Portugal": "Португалия", "Netherlands": "Нидерланды", "Belgium": "Бельгия",
    "Switzerland": "Швейцария", "Austria": "Австрия", "Sweden": "Швеция", "Norway": "Норвегия",
    "Denmark": "Дания", "Finland": "Финляндия", "Poland": "Польша", "Ukraine": "Украина",
    "Georgia": "Грузия", "Montenegro": "Черногория", "Serbia": "Сербия", "Cyprus": "Кипр",
    "Greece": "Греция", "Romania": "Румыния", "Bulgaria": "Болгария", "Czech Republic": "Чехия",
    "Hungary": "Венгрия", "Lithuania": "Литва", "Latvia": "Латвия", "Estonia": "Эстония",
    "LBR": "Либерия", "Liberia": "Либерия", "Ghana": "Гана", "Morocco": "Марокко",
    "Thailand": "Таиланд", "Vietnam": "Вьетнам", "South Korea": "Южная Корея", "Taiwan": "Тайвань",
    "Brazil": "Бразилия", "Mexico": "Мексика", "Argentina": "Аргентина",
}


def ru_country(name: str) -> str:
    name = (name or "").strip()
    return COUNTRY_RU.get(name, name)


# ISO 3166 alpha-2 codes, for the flag emoji. Same keys as COUNTRY_RU.
_ISO = {
    "United States": "US", "USA": "US", "United Kingdom": "GB", "Canada": "CA", "Australia": "AU",
    "New Zealand": "NZ", "Ireland": "IE", "United Arab Emirates": "AE", "Saudi Arabia": "SA",
    "Qatar": "QA", "Kuwait": "KW", "Israel": "IL", "Turkey": "TR", "Singapore": "SG", "India": "IN",
    "Pakistan": "PK", "Philippines": "PH", "Indonesia": "ID", "Malaysia": "MY", "Japan": "JP",
    "Hong Kong": "HK", "China": "CN", "Nigeria": "NG", "Kenya": "KE", "Egypt": "EG",
    "South Africa": "ZA", "Germany": "DE", "France": "FR", "Italy": "IT", "Spain": "ES",
    "Portugal": "PT", "Netherlands": "NL", "Belgium": "BE", "Switzerland": "CH", "Austria": "AT",
    "Sweden": "SE", "Norway": "NO", "Denmark": "DK", "Finland": "FI", "Poland": "PL",
    "Ukraine": "UA", "Georgia": "GE", "Montenegro": "ME", "Serbia": "RS", "Cyprus": "CY",
    "Greece": "GR", "Romania": "RO", "Bulgaria": "BG", "Czech Republic": "CZ", "Hungary": "HU",
    "Lithuania": "LT", "Latvia": "LV", "Estonia": "EE", "LBR": "LR", "Liberia": "LR", "Ghana": "GH",
    "Morocco": "MA", "Thailand": "TH", "Vietnam": "VN", "South Korea": "KR", "Taiwan": "TW",
    "Brazil": "BR", "Mexico": "MX", "Argentina": "AR",
}


def flag(name: str) -> str:
    """🇳🇬 for "Nigeria"; the globe when the country isn't in the table."""
    code = _ISO.get((name or "").strip())
    return "".join(chr(0x1F1E6 + ord(c) - 65) for c in code) if code else "🌍"
