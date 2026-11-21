import re

from django.core.exceptions import ValidationError


class ComplexityValidator:
    """Require upper, lower, digit and symbol characters."""

    def validate(self, password, user=None):
        checks = [
            (r"[a-z]", "a lowercase letter"),
            (r"[A-Z]", "an uppercase letter"),
            (r"\d", "a number"),
            (r"[^\w\s]|_", "a symbol such as ! or #"),
        ]
        missing = [label for pattern, label in checks if not re.search(pattern, password)]
        if missing:
            raise ValidationError(
                "Your password must also include " + ", ".join(missing) + ".", code="password_too_simple"
            )

    def get_help_text(self):
        return "Use upper and lower case letters, a number and a symbol."
