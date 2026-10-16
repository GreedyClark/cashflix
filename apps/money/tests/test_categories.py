from apps.money.models import Category
from apps.money.services import DEFAULT_EXPENSE_CATEGORIES, DEFAULT_INCOME_CATEGORIES


def test_new_household_gets_default_categories(home):
    expense = home.categories.filter(kind=Category.Kind.EXPENSE)
    income = home.categories.filter(kind=Category.Kind.INCOME)

    assert expense.count() == len(DEFAULT_EXPENSE_CATEGORIES)
    assert income.count() == len(DEFAULT_INCOME_CATEGORIES)
    assert expense.first().name == "Продукти"


def test_other_category_uses_grey_color(home):
    other = home.categories.get(kind=Category.Kind.EXPENSE, name="Інше")
    food = home.categories.get(kind=Category.Kind.EXPENSE, name="Продукти")

    assert other.color_var == "--cat-other"
    assert food.color_var == "--cat-1"