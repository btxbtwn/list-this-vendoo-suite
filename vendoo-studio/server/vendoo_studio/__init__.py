import truststore

# The packaged app's Python has no CA bundle of its own, so stdlib HTTPS (the
# box-scout crawl, for one) failed certificate checks. Verify against the
# system trust store (the macOS Keychain) instead. This has to run before the
# first urlopen: urllib builds its shared opener, HTTPS context included, on
# that first call and keeps it, and the desktop launcher's health check makes
# that call before the server is imported.
truststore.inject_into_ssl()
