from app.rules.normalize import despace


def test_default_keeps_digits_and_folds_accents():
    assert despace("750 mL") == "750ml"
    assert despace("Séléné") == "selene"  # accents folded to ASCII


def test_drop_digits():
    assert despace("war2ning", keep_digits=False) == "warning"


def test_no_strip_accents_drops_accented_char():
    # legacy [^a-z0-9] behavior: an accented char is removed, not folded
    assert despace("café", strip_accents=False) == "caf"


def test_drop_digits_no_accents_matches_legacy_alpha_only():
    assert despace("A1 b-2 C", keep_digits=False, strip_accents=False) == "abc"


def test_none_is_empty():
    assert despace(None) == ""
