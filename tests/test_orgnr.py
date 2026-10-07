from signalpost.phases.p1_company_lookup import validate_orgnr


def test_valid_orgnr():
    # 923 609 016 is a well-known valid orgnr (Equinor)
    assert validate_orgnr("923609016") is True


def test_invalid_checksum():
    assert validate_orgnr("923609017") is False


def test_invalid_format():
    assert validate_orgnr("12345") is False
    assert validate_orgnr("abcdefghi") is False