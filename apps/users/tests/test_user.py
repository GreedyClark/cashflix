import pytest
from django.contrib.auth import get_user_model

User = get_user_model()


@pytest.mark.django_db
def test_create_user_with_email():
    user = User.objects.create_user(email="Yura@Example.com", password="pass12345")

    assert user.email == "yura@example.com"
    assert user.check_password("pass12345")
    assert not user.is_staff


@pytest.mark.django_db
def test_create_user_without_email_fails():
    with pytest.raises(ValueError):
        User.objects.create_user(email="", password="pass12345")


@pytest.mark.django_db
def test_create_superuser():
    admin = User.objects.create_superuser(email="admin@example.com", password="pass12345")

    assert admin.is_staff
    assert admin.is_superuser


@pytest.mark.django_db
def test_name_falls_back_to_email():
    user = User.objects.create_user(email="olichka@example.com", password="pass12345")
    assert user.name == "olichka"
    assert user.initial == "O"

    user.display_name = "Олічка"
    assert user.name == "Олічка"
    assert user.initial == "О"


@pytest.mark.django_db
def test_login_with_email(client):
    User.objects.create_user(email="yura@example.com", password="pass12345")

    assert client.login(email="yura@example.com", password="pass12345")