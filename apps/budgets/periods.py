import datetime
from dataclasses import dataclass

from django.utils import dateformat, formats
from django.utils.translation import gettext as _

from apps.recurring.dates import add_months

EARLY_INCOME_DAYS = 3


@dataclass(frozen=True)
class Period:
    start: datetime.date
    end: datetime.date
    start_day: int = 1

    @classmethod
    def starting(cls, start, start_day=1):
        return cls(start, add_months(start, 1) - datetime.timedelta(days=1), start_day)

    @classmethod
    def containing(cls, day, start_day=1):
        if day.day >= start_day:
            start = day.replace(day=start_day)
        else:
            start = add_months(day.replace(day=1), -1).replace(day=start_day)
        return cls.starting(start, start_day)

    @classmethod
    def from_key(cls, key, start_day, today):
        try:
            month = datetime.datetime.strptime(key or "", "%Y-%m").date()
        except ValueError:
            return cls.containing(today, start_day)
        return cls.starting(month.replace(day=start_day), start_day)

    @property
    def key(self):
        return self.start.strftime("%Y-%m")

    @property
    def is_calendar(self):
        return self.start_day == 1

    @property
    def days(self):
        return (self.end - self.start).days + 1

    def shift(self, months):
        return Period.starting(add_months(self.start, months), self.start_day)

    def previous(self):
        return self.shift(-1)

    def next(self):
        return self.shift(1)

    def contains(self, day):
        return self.start <= day <= self.end

    def day_number(self, day):
        day = min(max(day, self.start), self.end)
        return (day - self.start).days + 1

    def dates(self):
        return [self.start + datetime.timedelta(days=offset) for offset in range(self.days)]

    def income_range(self):
        if self.is_calendar:
            return self.start, self.end
        shift = datetime.timedelta(days=EARLY_INCOME_DAYS)
        return self.start - shift, self.end - shift

    @property
    def label(self):
        if self.is_calendar:
            return dateformat.format(self.start, "F Y").capitalize()
        start_format = "j E Y" if self.start.year != self.end.year else "j E"
        return f"{formats.date_format(self.start, start_format)} – {formats.date_format(self.end, 'j E')}"

    @property
    def name(self):
        if self.is_calendar:
            return dateformat.format(self.start, "F").lower()
        return self.short_label

    @property
    def since(self):
        if self.is_calendar:
            return _("за %(name)s") % {"name": self.name}
        return _("з %(date)s") % {"date": formats.date_format(self.start, "j E")}

    @property
    def short_label(self):
        if self.is_calendar:
            return dateformat.format(self.start, "E")
        return _("%(start)s – %(end)s") % {
            "start": formats.date_format(self.start, "j.m"),
            "end": formats.date_format(self.end, "j.m"),
        }

    @property
    def chart_label(self):
        if self.is_calendar:
            return dateformat.format(self.start, "M")
        return formats.date_format(self.start, "j.m")
