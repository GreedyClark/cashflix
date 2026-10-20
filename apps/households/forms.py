from django import forms
from django.utils.translation import gettext_lazy as _

from .models import Currency, Household


class HouseholdForm(forms.ModelForm):
    base_currency = forms.ChoiceField(
        label=_("Основна валюта"), choices=Currency.choices, initial=Currency.UAH, widget=forms.RadioSelect
    )

    class Meta:
        model = Household
        fields = ["name", "base_currency"]
        labels = {"name": _("Назва")}
        widgets = {"name": forms.TextInput(attrs={"autocomplete": "off", "placeholder": _("Наприклад, Дім")})}

    def clean_name(self):
        name = self.cleaned_data["name"].strip()
        if not name:
            raise forms.ValidationError(_("Вкажіть назву, наприклад «Дім»."))
        return name