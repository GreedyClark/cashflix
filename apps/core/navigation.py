from django.utils.translation import gettext_lazy as _

# url_name = None means the section is not built yet
MAIN_MENU = [
    {"label": _("Огляд"), "short": _("Огляд"), "icon": "home", "url_name": "core:home"},
    {"label": _("Операції"), "short": _("Операції"), "icon": "arrows-exchange", "url_name": "money:transactions"},
    {"label": _("Бюджет і ліміти"), "short": _("Бюджет"), "icon": "report-money", "url_name": "budgets:budget"},
    {"label": _("Рахунки"), "short": _("Рахунки"), "icon": "wallet", "url_name": "money:accounts"},
    {"label": _("Категорії"), "short": _("Категорії"), "icon": "category", "url_name": "money:categories"},
    {"label": _("Регулярні платежі"), "short": _("Платежі"), "icon": "repeat", "url_name": "recurring:payments"},
    {"label": _("Цілі"), "short": _("Цілі"), "icon": "target", "url_name": "goals:goals"},
]