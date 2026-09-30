from nemotron import AUTO, lang_id, strip_tags


def test_lang_id_plain_and_regional_codes():
    assert lang_id("en") == 0
    assert lang_id("de") == 9
    assert lang_id("de-DE") == 9
    assert lang_id("EN-gb") == 0


def test_lang_id_unknown_or_missing_is_auto_detect():
    assert lang_id(None) == AUTO
    assert lang_id("") == AUTO
    assert lang_id("xx") == AUTO


def test_strip_tags_removes_language_tag_and_its_space():
    assert strip_tags("I placed. <en-US> My work") == "I placed. My work"
    assert strip_tags(" <de-DE>Hallo") == "Hallo"


def test_strip_tags_leaves_other_angle_brackets():
    assert strip_tags("use <b> here") == "use <b> here"
