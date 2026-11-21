from django.contrib.auth.backends import ModelBackend


class EmailBackend(ModelBackend):
    """ModelBackend keyed on the (case-insensitive) email address."""

    def authenticate(self, request, username=None, password=None, **kwargs):
        if username is None:
            username = kwargs.get("email")
        if username is None or password is None:
            return None
        return super().authenticate(request, username=username.strip(), password=password)
