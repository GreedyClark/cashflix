from collections import Counter

from django import forms
from django.utils.translation import gettext_lazy as _

from .icon_catalog import CATALOG
from .models import Category

COLORS = range(1, 8)


def free_color(household, kind=Category.Kind.EXPENSE):
    used = Counter(household.categories.filter(kind=kind).values_list("color_slot", flat=True))
    return min(COLORS, key=lambda slot: used[slot])


class CategoryForm(forms.ModelForm):
    color_slot = forms.TypedChoiceField(coerce=int, choices=[(slot, slot) for slot in COLORS], required=False)
    icon = forms.CharField(max_length=40, required=False)

    class Meta:
        model = Category
        fields = ["kind", "name", "color_slot", "icon", "emoji"]
        widgets = {
            "kind": forms.RadioSelect,
            "name": forms.TextInput(attrs={"placeholder": _("Наприклад, Тварини"), "autocomplete": "off"}),
            "emoji": forms.TextInput(attrs={"placeholder": "🎣", "autocomplete": "off", "class": "emoji-input"}),
        }
        error_messages = {"name": {"required": _("Вкажіть назву категорії.")}}

    def __init__(self, *args, household, kind=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.household = household
        self.instance.household = household
        if self.instance.pk or kind:
            self.fields["kind"].disabled = True
            self.fields["kind"].required = False
            self.initial["kind"] = self.instance.kind if self.instance.pk else kind
        current_kind = self.instance.kind if self.instance.pk else (kind or self["kind"].value() or Category.Kind.EXPENSE)
        self.initial.setdefault("color_slot", self.instance.color_slot if self.instance.pk else free_color(household, current_kind))

    def color_options(self):
        selected = str(self["color_slot"].value() or "")
        return [{"slot": slot, "checked": str(slot) == selected} for slot in COLORS]

    def clean_name(self):
        name = " ".join(self.cleaned_data["name"].split())
        kind = self.cleaned_data.get("kind") or self.initial.get("kind") or self.instance.kind
        others = self.household.categories.filter(kind=kind).exclude(pk=self.instance.pk)
        existing = next((c for c in others if c.name.casefold() == name.casefold()), None)
        if existing:
            if existing.is_archived:
                raise forms.ValidationError(_("Категорія «%(name)s» вже є в архіві.") % {"name": existing.name})
            raise forms.ValidationError(_("Категорія «%(name)s» вже є.") % {"name": existing.name})
        return name

    def clean_icon(self):
        icon = self.cleaned_data["icon"]
        if icon in CATALOG or (icon and icon == self.instance.icon):
            return icon
        return ""

    def clean_emoji(self):
        emoji = self.cleaned_data["emoji"].strip()
        if any(char.isalnum() for char in emoji):
            raise forms.ValidationError(_("Тут можна лише емодзі."))
        return emoji

    def save(self, commit=True):
        category = super().save(commit=False)
        if not category.color_slot:
            category.color_slot = free_color(self.household, category.kind)
        if not category.pk:
            category.order = self.household.categories.filter(kind=category.kind).count()
        if commit:
            category.save()
        return category


class MergeForm(forms.Form):
    target = forms.ModelChoiceField(queryset=None, empty_label=None, error_messages={"required": _("Оберіть категорію.")})

    def __init__(self, *args, source, **kwargs):
        super().__init__(*args, **kwargs)
        self.source = source
        self.fields["target"].queryset = source.household.categories.filter(
            kind=source.kind, is_archived=False
        ).exclude(pk=source.pk)
