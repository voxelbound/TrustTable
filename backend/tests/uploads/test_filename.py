"""Tests for `uploads.filename.sanitize_filename` (`WP-029`, AC-01)."""

from __future__ import annotations

from trusttable_backend.uploads.filename import FALLBACK_FILENAME, sanitize_filename


def test_ordinary_filename_preserved() -> None:
    assert sanitize_filename("sales_march.csv") == "sales_march.csv"


def test_filename_with_spaces_preserved() -> None:
    assert sanitize_filename("Q1 Sales Report.csv") == "Q1 Sales Report.csv"


def test_posix_path_traversal_stripped() -> None:
    assert sanitize_filename("../../etc/passwd.csv") == "passwd.csv"


def test_posix_absolute_path_stripped() -> None:
    assert sanitize_filename("/etc/passwd.csv") == "passwd.csv"


def test_windows_path_traversal_stripped() -> None:
    assert sanitize_filename("..\\..\\Windows\\evil.csv") == "evil.csv"


def test_windows_drive_letter_path_stripped() -> None:
    assert sanitize_filename("C:\\Users\\name\\data.csv") == "data.csv"


def test_windows_unc_path_stripped() -> None:
    assert sanitize_filename("\\\\server\\share\\data.csv") == "data.csv"


def test_control_characters_removed() -> None:
    assert sanitize_filename("da\x00ta\x1f.csv") == "data.csv"


def test_del_character_removed() -> None:
    assert sanitize_filename("data\x7f.csv") == "data.csv"


def test_none_input_falls_back() -> None:
    assert sanitize_filename(None) == FALLBACK_FILENAME


def test_empty_input_falls_back() -> None:
    assert sanitize_filename("") == FALLBACK_FILENAME


def test_whitespace_only_input_falls_back() -> None:
    assert sanitize_filename("   ") == FALLBACK_FILENAME


def test_path_only_input_falls_back() -> None:
    assert sanitize_filename("../../") == FALLBACK_FILENAME


def test_dots_and_spaces_only_input_falls_back() -> None:
    assert sanitize_filename(" . . . ") == FALLBACK_FILENAME


def test_trailing_dot_and_space_trimmed() -> None:
    assert sanitize_filename("data.csv. ") == "data.csv"


def test_leading_and_trailing_whitespace_trimmed() -> None:
    assert sanitize_filename("  data.csv  ") == "data.csv"


def test_over_length_input_is_bounded() -> None:
    name = ("a" * 300) + ".csv"
    result = sanitize_filename(name)
    assert len(result) <= 255
    assert result.startswith("a")


def test_all_dots_input_falls_back_regardless_of_length() -> None:
    # A component made entirely of "." characters strips away to nothing
    # (dots are trimmed at both ends), landing on the fallback name.
    name = "." * 300
    assert sanitize_filename(name) == FALLBACK_FILENAME
