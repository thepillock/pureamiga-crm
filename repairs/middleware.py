from django.conf import settings


class SecureCookiesOnHttps:
    """Mark the session and CSRF cookies Secure whenever the request came in over HTTPS.

    Saves configuring it per deployment: through NPM+ with SSL the cookies are Secure,
    and plain-HTTP access on the LAN (http://unraid:3300) still works.
    """

    def __init__(self, get_response):
        self.get_response = get_response
        self.names = (settings.SESSION_COOKIE_NAME, settings.CSRF_COOKIE_NAME)

    def __call__(self, request):
        response = self.get_response(request)
        if request.is_secure():
            for name in self.names:
                if name in response.cookies:
                    response.cookies[name]["secure"] = True
        return response
