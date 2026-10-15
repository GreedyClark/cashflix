# CashFlix

Сімейний бюджет для кількох людей в одному господарстві: витрати, доходи й перекази між рахунками в кількох валютах, ліміти на категорії (спільні й особисті), регулярні платежі, цілі накопичень, підказки, де зекономити, та експорт в Excel. Оплати Apple Pay потрапляють автоматично через iOS-шорткат.

> Проєкт у розробці. Поточна фаза — 0 (каркас).

## Стек

- Python 3.14, Django 5.2 LTS
- Django templates + django-cotton, HTMX
- Tabler, Tabler Icons, ApexCharts
- SQLite локально, PostgreSQL на проді
- pytest-django, Playwright

## Запуск локально (Windows / PowerShell)

```powershell
git clone https://github.com/GreedyClark/cashflix.git
cd cashflix
py -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
```

У `.env` замініть `SECRET_KEY` на власний:

```powershell
python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```

Далі:

```powershell
python manage.py migrate
python manage.py runserver
```

Сайт відкриється на http://127.0.0.1:8000.

## Тести

```powershell
pytest
```

## Що реалізовано

- [x] Фаза 0 — каркас: налаштування через `.env`, українська мова з підтримкою перекладу, базовий шаблон, світла й темна тема, адаптивне меню

## Що планується

- [ ] Фаза 1 — моделі: господарства, рахунки, категорії, операції, ліміти, цілі
- [ ] Фаза 2 — реєстрація, вхід через Google, запрошення до господарства
- [ ] Фаза 3 — дашборд і операції
- [ ] Фаза 4 — рахунки, перекази, валюти з курсом НБУ
- [ ] Фаза 5 — ліміти, регулярні платежі, підказки, цілі, експорт в Excel
- [ ] Фаза 6 — API для iOS-шорткату, перенесення старих даних
- [ ] Фаза 7 — деплой
- [ ] Фаза 8 — AI-асистент на ключі Gemini користувача