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


MCC_GROUPS = {
    "Продукти": [5300, 5411, 5422, 5441, 5451, 5462, 5499],
    "Кафе": [5811, 5812, 5813, 5814],
    "Транспорт": [4111, 4112, 4121, 4131, 4784, 4789, 5172, 5511, 5532, 5533, 5541, 5542, 7523, 7538, 7542],
    "Комуналка": [4814, 4816, 4900],
    "Підписки": [4899, 5815, 5816, 5817, 5818],
    "Розваги": [5945, 7832, 7841, 7922, 7929, 7991, 7994, 7996, 7999],
    "Одяг": [5611, 5621, 5631, 5641, 5651, 5655, 5661, 5691, 5699, 5948],
    "Здоров'я": [5122, 5912, 8011, 8021, 8031, 8041, 8042, 8043, 8049, 8050, 8062, 8071, 8099],
}
MCC = {code: name for name, codes in MCC_GROUPS.items() for code in codes}


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


def categorize(household, title, kind=Category.Kind.EXPENSE, mcc=None):
    key = merchant_key(title)
    if key:
        rule = MerchantRule.objects.filter(household=household, key=key, category__kind=kind).select_related("category").first()
        if rule and not rule.category.is_archived:
            return Guess(rule.category, False, "memory")
    categories = {c.name: c for c in household.categories.filter(kind=kind, is_archived=False)}
    if kind == Category.Kind.EXPENSE and MCC.get(mcc) in categories:
        return Guess(categories[MCC[mcc]], False, "mcc")
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
