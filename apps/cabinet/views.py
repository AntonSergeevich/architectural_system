"""Кабинет: общая точка входа."""

from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect


@login_required
def home(request):
    if request.user.is_owner:
        return redirect("cabinet:leads")
    return redirect("cabinet:my_project")
