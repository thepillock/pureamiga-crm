from django.urls import path

from . import system_views, views

app_name = "repairs"

urlpatterns = [
    path("", views.board, name="board"),
    path("jobs/", views.job_list, name="job_list"),
    path("jobs/<int:pk>/", views.job_detail, name="job_detail"),
    path("jobs/<int:pk>/edit/", views.job_edit, name="job_edit"),
    path("jobs/<int:pk>/move/", views.job_move, name="job_move"),
    path("jobs/<int:pk>/assign-ref/", views.job_assign_ref, name="job_assign_ref"),
    path("jobs/<int:pk>/hand/", views.job_hand, name="job_hand"),
    path("jobs/<int:pk>/costs/add/", views.cost_add, name="cost_add"),
    path("costs/<int:pk>/edit/", views.cost_edit, name="cost_edit"),
    path("costs/<int:pk>/delete/", views.cost_delete, name="cost_delete"),
    path("notes/<int:pk>/edit/", views.note_edit, name="note_edit"),
    path("notes/<int:pk>/delete/", views.note_delete, name="note_delete"),
    path("notes/<int:pk>/split/", views.note_split, name="note_split"),
    path("customers/", views.customer_list, name="customer_list"),
    path("customers/new/", views.customer_edit, name="customer_new"),
    path("customers/<int:pk>/", views.customer_detail, name="customer_detail"),
    path("customers/<int:pk>/edit/", views.customer_edit, name="customer_edit"),
    path("customers/<int:customer_pk>/book-in/", views.job_book_in, name="job_book_in"),
    path("machines/<int:pk>/", views.machine_detail, name="machine_detail"),
    path("machines/<int:pk>/edit/", views.machine_edit, name="machine_edit"),
    path("tools/", system_views.tools, name="tools"),
    path("tools/backup/", system_views.download_backup, name="download_backup"),
]
