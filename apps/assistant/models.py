from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.households.models import Membership
from apps.integrations.crypto import decrypt, encrypt


class AssistantKey(models.Model):
    membership = models.OneToOneField(
        Membership, on_delete=models.CASCADE, related_name="assistant_key", verbose_name=_("учасник")
    )
    key_encrypted = models.TextField()
    hint = models.CharField(_("кінець ключа"), max_length=12)
    created_at = models.DateTimeField(_("додано"), auto_now_add=True)

    class Meta:
        verbose_name = _("ключ Gemini")
        verbose_name_plural = _("ключі Gemini")

    def __str__(self):
        return f"{self.membership} · …{self.hint}"

    @property
    def key(self):
        return decrypt(self.key_encrypted)

    @key.setter
    def key(self, raw):
        self.key_encrypted = encrypt(raw)
        self.hint = raw[-4:]


class ChatMessage(models.Model):
    class Role(models.TextChoices):
        USER = "user", _("користувач")
        ASSISTANT = "model", _("асистент")

    membership = models.ForeignKey(
        Membership, on_delete=models.CASCADE, related_name="chat_messages", verbose_name=_("учасник")
    )
    role = models.CharField(_("хто"), max_length=10, choices=Role.choices)
    text = models.TextField(_("текст"))
    created_at = models.DateTimeField(_("час"), auto_now_add=True)

    class Meta:
        verbose_name = _("повідомлення")
        verbose_name_plural = _("повідомлення")
        ordering = ["created_at", "pk"]

    def __str__(self):
        return f"{self.get_role_display()}: {self.text[:40]}"
