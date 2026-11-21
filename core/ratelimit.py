from functools import wraps

from django.core.cache import cache
from django.shortcuts import render

from .audit import client_ip


def ratelimit(name, limit, period):
    """Per-IP fixed-window limiter for POSTs (register, reset, beneficiary lookups...)."""

    def decorator(view):
        @wraps(view)
        def wrapper(request, *args, **kwargs):
            if request.method == "POST":
                key = f"rl:{name}:{client_ip(request)}"
                cache.add(key, 0, period)
                try:
                    count = cache.incr(key)
                except ValueError:
                    cache.set(key, 1, period)
                    count = 1
                if count > limit:
                    return render(request, "429.html", status=429)
            return view(request, *args, **kwargs)

        return wrapper

    return decorator
