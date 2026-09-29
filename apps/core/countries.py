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
