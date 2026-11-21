from django.conf import settings


def bank(request):
    return {
        "BANK_NAME": settings.BANK_NAME,
        "BANK_BRANCH_CODE": settings.BANK_BRANCH_CODE,
        "DEMO_MODE": settings.DEMO_MODE,
        "SESSION_IDLE_MINUTES": settings.SESSION_IDLE_SECONDS // 60,
    }
