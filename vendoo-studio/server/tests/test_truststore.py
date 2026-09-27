import ssl
import urllib.request

import truststore

import vendoo_studio.desktop  # noqa: F401  the launcher is the first thing a packaged app imports


def test_stdlib_https_verifies_against_the_system_trust_store():
    # urllib keeps the HTTPS context of its first opener, so the injection has
    # to be in place by the time any vendoo_studio module can call urlopen.
    handler = next(h for h in urllib.request.build_opener().handlers if isinstance(h, urllib.request.HTTPSHandler))
    assert ssl.SSLContext is truststore.SSLContext
    assert isinstance(handler._context, truststore.SSLContext)
