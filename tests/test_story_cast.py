import pytest
from engine.story import cast_prompt


def test_cast_names_are_filled_in_and_unknown_names_fail_loudly():
    cast = {"suresh": "a middle-aged Indian man in glasses and a checked shirt"}
    assert cast_prompt("{suresh} opens the drawer; {suresh} sighs.", cast) == "a middle-aged Indian man in glasses and a checked shirt opens the drawer; a middle-aged Indian man in glasses and a checked shirt sighs."
    assert cast_prompt("a lane of shops at night", cast) == "a lane of shops at night"
    with pytest.raises(KeyError):
        cast_prompt("{meena} at the counter", cast)
