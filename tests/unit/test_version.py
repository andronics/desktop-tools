import re

import desktop_tools


def test_version_is_pep440() -> None:
    assert re.fullmatch(r"\d+\.\d+\.\d+.*|0\+unknown", desktop_tools.__version__)
