from .models import Category

DEFAULT_EXPENSE_CATEGORIES = [
    ("Продукти", "shopping-cart", 1),
    ("Кафе", "coffee", 2),
    ("Транспорт", "car", 3),
    ("Комуналка", "home-bolt", 4),
    ("Підписки", "repeat", 5),
    ("Розваги", "device-gamepad-2", 6),
    ("Одяг", "shirt", 7),
    ("Здоров'я", "heart", 1),
    ("Інше", "dots", Category.OTHER_COLOR),
]

DEFAULT_INCOME_CATEGORIES = [
    ("Зарплата", "cash", 3),
    ("Подарунки", "gift", 5),
    ("Інвестиційний дохід", "chart-line", 7),
    ("Інше", "dots", Category.OTHER_COLOR),
]


def create_default_categories(household):
    rows = []
    for kind, items in (
        (Category.Kind.EXPENSE, DEFAULT_EXPENSE_CATEGORIES),
        (Category.Kind.INCOME, DEFAULT_INCOME_CATEGORIES),
    ):
        for order, (name, icon, color) in enumerate(items):
            rows.append(
                Category(household=household, kind=kind, name=name, icon=icon, color_slot=color, order=order)
            )
    return Category.objects.bulk_create(rows)