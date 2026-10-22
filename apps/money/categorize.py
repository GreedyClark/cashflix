import re
from dataclasses import dataclass

from .models import Category, MerchantRule

FALLBACK = "Інше"
NOISE = {"ua", "kyiv", "kiev", "київ", "lviv", "львів", "odesa", "одеса", "tov", "тов", "llc", "pp", "фоп", "fop", "shop", "store"}

STARTER = {
    "Продукти": [
        "сільпо", "silpo", "атб", "atb", "новус", "novus", "фора", "fora", "ашан", "auchan", "metro", "метро",
        "варус", "varus", "велмарт", "velmart", "еко маркет", "eko", "наш край", "фуршет", "fozzy", "фоззі",
        "rukavychka", "рукавичка", "lotok", "космос",
    ],
    "Кафе": [
        "кава", "kava", "coffee", "кафе", "cafe", "aroma", "пузата", "mcdonald", "макдональдс", "kfc", "domino",
        "pizza", "піца", "sushi", "суші", "glovo", "bolt food", "starbucks", "croissant", "ресторан", "restaurant",
        "burger", "бургер", "пекарня",
    ],
    "Транспорт": [
        "uklon", "уклон", "bolt", "uber", "wog", "окко", "okko", "socar", "shell", "upg", "бензин", "азс",
        "укрзалізниця", "uz.gov", "metro kyiv", "парковка", "parking", "автобус",
    ],
    "Комуналка": [
        "київстар", "kyivstar", "vodafone", "водафон", "lifecell", "лайфсел", "тепло", "енерго", "energo",
        "водоканал", "газзбут", "газмереж", "naftogaz", "нафтогаз", "інтернет", "volia", "воля", "датагруп", "ланет",
    ],
    "Підписки": [
        "netflix", "spotify", "youtube", "apple.com", "icloud", "google", "megogo", "мегого", "sweet.tv",
        "chatgpt", "openai", "patreon", "adobe", "steam",
    ],
    "Розваги": ["multiplex", "мультиплекс", "планета кіно", "кіно", "cinema", "концерт", "karabas", "квиток", "театр"],
    "Одяг": ["zara", "reserved", "h&m", "intertop", "інтертоп", "answear", "lc waikiki", "sinsay", "cropp", "house", "mango"],
    "Здоров'я": ["аптека", "apteka", "анц", "подорожник", "добробут", "dobrobut", "лікар", "клініка", "medical", "дент"],
}


@dataclass
class Guess:
    category: Category | None
    needs_review: bool
    reason: str


def merchant_key(title):
    words = re.sub(r"[^\w&.]+", " ", (title or "").lower()).split()
    words = [word for word in words if not word.isdigit() and word not in NOISE]
    return " ".join(words[:3])[:80]


def matches(key, keyword):
    if " " in keyword or "." in keyword:
        return keyword in key
    return any(word.startswith(keyword) for word in key.split())


def from_starter(key, categories):
    for name, keywords in STARTER.items():
        if name in categories and any(matches(key, keyword) for keyword in keywords):
            return categories[name]
    return None


def categorize(household, title, kind=Category.Kind.EXPENSE):
    key = merchant_key(title)
    if key:
        rule = MerchantRule.objects.filter(household=household, key=key, category__kind=kind).select_related("category").first()
        if rule and not rule.category.is_archived:
            return Guess(rule.category, False, "memory")
    categories = {c.name: c for c in household.categories.filter(kind=kind, is_archived=False)}
    found = from_starter(key, categories) if kind == Category.Kind.EXPENSE else None
    if found:
        return Guess(found, False, "starter")
    fallback = categories.get(FALLBACK) or next(iter(categories.values()), None)
    return Guess(fallback, True, "fallback")


def remember(transaction):
    if transaction.is_transfer or not transaction.category_id:
        return
    key = merchant_key(transaction.title)
    if not key:
        return
    MerchantRule.objects.update_or_create(
        household_id=transaction.household_id, key=key, defaults={"category_id": transaction.category_id}
    )
