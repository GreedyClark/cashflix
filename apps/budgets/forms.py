from django import forms
from django.utils.translation import gettext_lazy as _

from apps.money.category_forms import CategoryForm
from apps.money.forms import AmountField, format_amount
from apps.money.models import Category

from .models import Limit

NEW = "new"


class LimitForm(forms.ModelForm):
    category = forms.CharField(required=False)
    amount = AmountField(label=_("Сума на місяць"), min_value=1)
    member = forms.ModelChoiceField(queryset=None, required=False, empty_label=None)

    class Meta:
        model = Limit
        fields = ["amount", "member"]

    def __init__(self, data=None, *args, household, **kwargs):
        super().__init__(data, *args, **kwargs)
        self.household = household
        self.instance.household = household
        self.fields["member"].queryset = household.memberships.active().select_related("user")
        self.categories = household.categories.filter(kind=Category.Kind.EXPENSE, is_archived=False)
        self.category_form = CategoryForm(data, household=household, kind=Category.Kind.EXPENSE)
        if self.instance.pk:
            self.initial["amount"] = format_amount(self.instance.amount)
            self.fields["category"].disabled = True
            self.initial["category"] = self.instance.category_id

    @property
    def is_new_category(self):
        return self["category"].value() == NEW

    def category_options(self):
        selected = str(self["category"].value() or "")
        return [{"object": c, "checked": str(c.pk) == selected} for c in self.categories]

    def owner_options(self):
        selected = str(self["member"].value() or "")
        return [{"object": m, "checked": str(m.pk) == selected} for m in self.fields["member"].queryset]

    def clean(self):
        cleaned = super().clean()
        if self.instance.pk:
            self.category = self.instance.category
        elif cleaned.get("category") == NEW:
            self.category = None
            if not self.category_form.is_valid():
                self.add_error("category", _("Перевірте поля нової категорії."))
        else:
            self.category = self.categories.filter(pk=cleaned.get("category") or None).first()
            if self.category is None:
                self.add_error("category", _("Оберіть категорію."))
        if self.category:
            self.check_duplicate(cleaned.get("member"))
        return cleaned

    def check_duplicate(self, member):
        limits = Limit.objects.filter(category=self.category, member=member).exclude(pk=self.instance.pk)
        if limits.exists():
            self.add_error(None, _("Такий ліміт на цю категорію вже є. Змініть його замість створення нового."))

    def save(self, commit=True):
        if self.category is None:
            self.category = self.category_form.save()
        self.instance.category = self.category
        return super().save(commit)
