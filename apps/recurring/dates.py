import calendar
import datetime


def add_months(date, months, day=None):
    day = day or date.day
    month_index = date.month - 1 + months
    year = date.year + month_index // 12
    month = month_index % 12 + 1
    last_day = calendar.monthrange(year, month)[1]
    return datetime.date(year, month, min(day, last_day))