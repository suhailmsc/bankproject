from django.core import signing

SALT = "accounts.email-verify"
MAX_AGE = 3 * 24 * 3600


def make_verification_token(user):
    return signing.dumps({"uid": user.pk, "email": user.email}, salt=SALT)


def read_verification_token(token):
    """Returns payload dict or None."""
    try:
        return signing.loads(token, salt=SALT, max_age=MAX_AGE)
    except signing.BadSignature:
        return None
