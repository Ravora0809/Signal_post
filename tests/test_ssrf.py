from signalpost.utils.ssrf import is_url_safe


def test_blocks_localhost():
    assert is_url_safe("http://localhost/x")[0] is False
    assert is_url_safe("http://127.0.0.1/x")[0] is False


def test_blocks_private_ips():
    assert is_url_safe("http://10.0.0.1/x")[0] is False
    assert is_url_safe("http://192.168.1.1/x")[0] is False


def test_blocks_bad_scheme():
    assert is_url_safe("file:///etc/passwd")[0] is False


def test_allows_public():
    ok, _ = is_url_safe("https://data.brreg.no/enhetsregisteret/api/enheter/923609016")
    assert ok is True