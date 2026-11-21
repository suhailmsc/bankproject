from django.shortcuts import redirect, render
from django.views import View


class HomeView(View):
    def get(self, request):
        if request.user.is_authenticated:
            if getattr(request.user, "kind", None) == "staff":
                return redirect("admin:index")
            return redirect("banking:dashboard")
        return render(request, "home.html")


def permission_denied(request, exception=None):
    return render(request, "403.html", status=403)


def not_found(request, exception=None):
    return render(request, "404.html", status=404)


def server_error(request):
    return render(request, "500.html", status=500)
