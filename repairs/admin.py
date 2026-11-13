from django.contrib import admin

from .models import Customer, JobNote, Machine, RepairJob, StageChange


class MachineInline(admin.TabularInline):
    model = Machine
    extra = 0
    fields = ["model", "description", "serial_number"]
    show_change_link = True


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ["full_name", "email", "phone", "postcode", "created_at"]
    search_fields = ["first_name", "last_name", "email", "phone", "postcode"]
    readonly_fields = ["legacy_jetpack_id", "created_at", "updated_at"]
    inlines = [MachineInline]


@admin.register(Machine)
class MachineAdmin(admin.ModelAdmin):
    list_display = ["__str__", "customer", "serial_number"]
    list_filter = ["model"]
    search_fields = ["serial_number", "description", "customer__first_name", "customer__last_name"]
    autocomplete_fields = ["customer"]


class JobNoteInline(admin.StackedInline):
    model = JobNote
    extra = 0


class StageChangeInline(admin.TabularInline):
    model = StageChange
    extra = 0
    readonly_fields = ["from_stage", "to_stage", "changed_by", "changed_at"]
    can_delete = False


@admin.register(RepairJob)
class RepairJobAdmin(admin.ModelAdmin):
    list_display = ["ref", "title", "customer", "machine", "stage", "technician", "received_at"]
    list_filter = ["stage", "technician", "machine__model"]
    search_fields = ["title", "customer__first_name", "customer__last_name", "machine__serial_number"]
    autocomplete_fields = ["customer", "machine"]
    readonly_fields = ["legacy_jetpack_id", "legacy_status", "created_at", "updated_at"]
    inlines = [JobNoteInline, StageChangeInline]
