def is_htmx(request) -> bool:
    """
    True when HTMX asked for a fragment. A history-restore request (back button
    after the cache expired) wants the full page, so it doesn't count.
    """
    return (
        request.headers.get('HX-Request') == 'true'
        and request.headers.get('HX-History-Restore-Request') != 'true'
    )
