"""First-run setup, health check and the staff Tools page (import + backups)."""
from django import forms
from django.contrib import messages
from django.contrib.auth import get_user_model, login
from django.contrib.auth.decorators import login_not_required
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.views import LoginView
from django.core.exceptions import PermissionDenied
from django.db import connection
from django.http import FileResponse, HttpResponse
from django.shortcuts import redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST

from .backup import backup_dir, make_backup
from .importer import hand_imported_jobs, run_import
from .models import RepairJob


def _no_users_yet():
    return not get_user_model().objects.exists()


@login_not_required
@never_cache
def healthz(request):
    with connection.cursor() as cur:
        cur.execute("SELECT 1")
    return HttpResponse("ok", content_type="text/plain")


class CRMLoginView(LoginView):
    """Normal login, except it sends you to first-run setup while there are no accounts."""

    def dispatch(self, request, *args, **kwargs):
        if _no_users_yet():
            return redirect("setup")
        return super().dispatch(request, *args, **kwargs)


class FirstAdminForm(UserCreationForm):
    first_name = forms.CharField(max_length=150, help_text="Shown on the board, e.g. Chris")

    class Meta(UserCreationForm.Meta):
        model = get_user_model()
        fields = ("username", "first_name")


@login_not_required
@never_cache
def setup(request):
    """Create the first (admin) account in the browser. Disappears once any account exists."""
    if not _no_users_yet():
        return redirect("login")
    form = FirstAdminForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save(commit=False)
        user.is_staff = user.is_superuser = True
        user.save()
        login(request, user, backend="django.contrib.auth.backends.ModelBackend")
        return redirect("repairs:tools")
    return render(request, "repairs/setup.html", {"form": form})


class ImportForm(forms.Form):
    dump = forms.FileField(label="WordPress database dump (.sql)",
                           help_text="phpMyAdmin export of the WordPress database")
    commit = forms.BooleanField(required=False, label="Import for real",
                                help_text="Leave unticked for a dry run that shows what would be imported")
    include_leads = forms.BooleanField(required=False, label="Also import contacts with no repair jobs",
                                       help_text="Mostly contact-form leads and spam")
    holder = forms.ModelChoiceField(
        queryset=get_user_model().objects.filter(is_active=True), required=False, label="Imported jobs are with",
        empty_label="— nobody —",
        help_text="If they all came through one person (e.g. Phil), choose them so they can see these jobs.")


class HandImportedForm(forms.Form):
    user = forms.ModelChoiceField(queryset=get_user_model().objects.filter(is_active=True), label="Give them to")


def _staff_only(request):
    if not request.user.is_staff:
        raise PermissionDenied


def tools(request):
    _staff_only(request)
    form = ImportForm()
    hand_form = HandImportedForm()
    result = None
    if request.method == "POST" and request.POST.get("action") == "hand_imported":
        hand_form = HandImportedForm(request.POST)
        if hand_form.is_valid():
            user = hand_form.cleaned_data["user"]
            n = hand_imported_jobs(user, by=request.user)
            messages.success(request, f"{n} imported job{'s' if n != 1 else ''} now with {user.get_short_name() or user}.")
            return redirect("repairs:tools")
    elif request.method == "POST":
        form = ImportForm(request.POST, request.FILES)
        if form.is_valid():
            text = form.cleaned_data["dump"].read().decode("utf-8", errors="replace")
            result = run_import(text, commit=form.cleaned_data["commit"],
                                include_leads=form.cleaned_data["include_leads"],
                                holder=form.cleaned_data["holder"], by=request.user)
            if result.committed:
                form = ImportForm()
    backups = sorted(backup_dir().glob("crm-*.sqlite3"), reverse=True)[:5] if backup_dir().exists() else []
    unassigned = RepairJob.objects.filter(legacy_jetpack_id__isnull=False, holder__isnull=True).count()
    return render(request, "repairs/tools.html", {
        "form": form, "hand_form": hand_form, "unassigned_imported": unassigned, "result": result, "backups": backups,
    })


@require_POST
def download_backup(request):
    _staff_only(request)
    path = make_backup()
    return FileResponse(open(path, "rb"), as_attachment=True, filename=path.name,
                        content_type="application/vnd.sqlite3")
