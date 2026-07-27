import pytest

from modules.voice_commands import _strip_wake_prefix, _match_color, _match_brightness, _best_string_match


@pytest.mark.parametrize("input_text, expected_output", [
    ("Hey, Sentinel, set lights to red", "set lights to red"),
    ("Sentinel set lights to red", "set lights to red"),
    ("set lights to red", "set lights to red"),
    ("Hey, Sentinel. Set lights to red.", "Set lights to red."),
    ("Hey Sentinel! Stop.", "Stop."),
])
def test_strip_wake_prefix(input_text, expected_output):
    assert _strip_wake_prefix(input_text) == expected_output


@pytest.mark.parametrize("phrase, expected_color", [
    ("set lights to red", "red"),
    ("set the lights to purple", "purple"),
    ("set lights to mauve", None),
])
def test_match_color(phrase, expected_color):
    assert _match_color(None, phrase) == expected_color


@pytest.mark.parametrize("phrase, expected_pct", [
    ("set lights to 50 percent", 50),
    ("set brightness to 75", 75),
    ("set lights to red", None),
])
def test_match_brightness(phrase, expected_pct):
    assert _match_brightness(None, phrase) == expected_pct


@pytest.mark.parametrize("query, candidates, expected", [
    ("AC DC", ["AC/DC", "Beatles"], "AC/DC"),
    ("beatles", ["Beatles", "AC/DC"], "Beatles"),
    ("xyz123nonsense", ["Beatles", "AC/DC"], None),
    ("test", [], None),
    ("", ["Beatles", "AC/DC"], None),
])
def test_best_string_match(query, candidates, expected):
    result = _best_string_match(query, candidates)
    if expected is None:
        assert result is None
    else:
        assert result[0] == expected
