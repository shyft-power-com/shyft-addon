from constants import LOG_DETAIL_MAX_CHARS, shorten_log_detail


def test_short_message_unchanged():
    assert shorten_log_detail("kurz") == "kurz"


def test_long_message_is_cut_and_length_stays_visible():
    text = "x" * (LOG_DETAIL_MAX_CHARS + 250)
    out = shorten_log_detail(text)
    assert out.startswith("x" * LOG_DETAIL_MAX_CHARS)
    assert out.endswith("[... 250 Zeichen gekuerzt]")
    assert len(out) < len(text)
