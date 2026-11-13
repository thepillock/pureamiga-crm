from django.conf import settings


def site(request):
    return {
        "app_version": settings.APP_VERSION,
        "crm_environment": settings.CRM_ENVIRONMENT,
    }
