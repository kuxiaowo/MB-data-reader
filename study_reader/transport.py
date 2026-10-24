"""GET-only transport, supplied with an already-authenticated in-memory CookieJar."""
import http.cookiejar
import urllib.error
import urllib.request
from .managebac import safe_url, ReaderError


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Fail closed, including same-origin redirects to login or write-like endpoints.
        raise ReaderError('redirect_blocked_session_may_be_expired')


class ReadOnlyTransport:
    def __init__(self, cookie_jar, timeout=20, max_bytes=5 * 1024 * 1024):
        if not isinstance(cookie_jar, http.cookiejar.CookieJar):
            raise TypeError('Supply an authenticated in-memory CookieJar')
        if timeout <= 0 or max_bytes < 1:
            raise ValueError('Limits must be positive')
        self.timeout, self.max_bytes = timeout, max_bytes
        self._opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(cookie_jar), NoRedirect())

    def get(self, url):
        if not safe_url(url):
            raise ReaderError('url_not_allowed')
        request = urllib.request.Request(url, method='GET', headers={
            'Accept': 'text/html', 'User-Agent': 'study-data-reader/0.1',
            'Cache-Control': 'no-cache'})
        try:
            with self._opener.open(request, timeout=self.timeout) as response:
                if response.geturl() != url:
                    raise ReaderError('unexpected_response_url')
                if response.status != 200:
                    raise ReaderError('http_status_' + str(response.status))
                if response.headers.get_content_type() not in {'text/html', 'application/xhtml+xml'}:
                    raise ReaderError('unexpected_content_type')
                raw = response.read(self.max_bytes + 1)
                if len(raw) > self.max_bytes:
                    raise ReaderError('response_too_large')
                try:
                    return raw.decode(response.headers.get_content_charset() or 'utf-8')
                except (UnicodeError, LookupError):
                    raise ReaderError('invalid_response_encoding') from None
        except ReaderError:
            raise
        except urllib.error.HTTPError as exc:
            code = exc.code
            exc.close()
            raise ReaderError('authentication_required' if code in (401, 403) else
                              'http_status_' + str(code)) from None
        except (urllib.error.URLError, TimeoutError, OSError):
            raise ReaderError('network_error') from None
