import pytest

from duckdiff.comparator import run_comparison
from duckdiff.config import ComparisonConfig, ToleranceRule
from duckdiff.exceptions import ConfigurationError, SchemaMismatchError


def _write_csv(tmp_path, name, rows):
    """rows: list of lines, first line is the header."""
    path = tmp_path / name
    path.write_text("\n".join(rows) + "\n")
    return str(path)


# ---------------------------------------------------------------------------
# Full-row (no key_columns) mode: a row's entire content is its identity.
# ---------------------------------------------------------------------------


def test_full_row_exact_match(tmp_path):
    a = _write_csv(tmp_path, "a.csv", ["id,name,amount", "1,alice,10.0", "2,bob,20.0"])
    b = _write_csv(tmp_path, "b.csv", ["id,name,amount", "1,alice,10.0", "2,bob,20.0"])
    result = run_comparison({"a": a, "b": b}, ComparisonConfig())
    assert result.matched_row_count == 2
    assert result.mismatched_row_count == 0
    assert result.only_in == {"a": 0, "b": 0}


def test_full_row_disjoint_rows_are_only_in(tmp_path):
    a = _write_csv(tmp_path, "a.csv", ["id,name,amount", "1,alice,10.0", "2,bob,20.0"])
    b = _write_csv(tmp_path, "b.csv", ["id,name,amount", "1,alice,10.0", "3,carol,30.0"])
    result = run_comparison({"a": a, "b": b}, ComparisonConfig())
    assert result.matched_row_count == 1  # only id=1 row is identical in both
    assert result.only_in == {"a": 1, "b": 1}  # id=2 row vs id=3 row


def test_full_row_mismatched_row_count_is_always_zero(tmp_path):
    """In full-row mode there's no concept of 'same identity, different
    content' -- a row that differs at all is simply not part of the
    intersection, and shows up in only_in instead."""
    a = _write_csv(tmp_path, "a.csv", ["id,amount", "1,10.0"])
    b = _write_csv(tmp_path, "b.csv", ["id,amount", "1,99.0"])
    result = run_comparison({"a": a, "b": b}, ComparisonConfig())
    assert result.mismatched_row_count == 0
    assert result.only_in == {"a": 1, "b": 1}


def test_full_row_duplicate_rows_use_bag_semantics(tmp_path):
    """3x of a row in 'a' and 2x of the same row in 'b' should match 2
    (min of the two counts), leaving 1 unmatched copy in 'a'."""
    a = _write_csv(tmp_path, "a.csv", ["id,amount", "1,10.0", "1,10.0", "1,10.0"])
    b = _write_csv(tmp_path, "b.csv", ["id,amount", "1,10.0", "1,10.0"])
    result = run_comparison({"a": a, "b": b}, ComparisonConfig())
    assert result.matched_row_count == 2
    assert result.only_in == {"a": 1, "b": 0}


def test_full_row_three_way(tmp_path):
    a = _write_csv(tmp_path, "a.csv", ["id,amount", "1,10.0", "2,20.0", "3,30.0"])
    b = _write_csv(tmp_path, "b.csv", ["id,amount", "1,10.0", "2,25.0"])  # 3 missing, 2 differs
    # 3 missing from b and c; 4 only in c
    c = _write_csv(tmp_path, "c.csv", ["id,amount", "1,10.0", "2,20.0", "4,40.0"])
    result = run_comparison({"a": a, "b": b, "c": c}, ComparisonConfig())
    # Only id=1's row is identical across all three sources.
    assert result.matched_row_count == 1
    assert result.only_in == {"a": 2, "b": 1, "c": 2}


# ---------------------------------------------------------------------------
# Keyed mode: rows are aligned by key_columns, then diffed column-by-column.
# ---------------------------------------------------------------------------


def test_keyed_matched_and_mismatched(tmp_path):
    a = _write_csv(tmp_path, "a.csv", ["id,name,amount", "1,alice,10.0", "2,bob,20.0"])
    b = _write_csv(tmp_path, "b.csv", ["id,name,amount", "1,alice,10.0", "2,bob,25.0"])
    config = ComparisonConfig(key_columns=["id"])
    result = run_comparison({"a": a, "b": b}, config)
    assert result.matched_row_count == 1  # id=1
    assert result.mismatched_row_count == 1  # id=2, amount differs
    assert result.only_in == {"a": 0, "b": 0}


def test_keyed_only_in_tracks_missing_keys(tmp_path):
    a = _write_csv(tmp_path, "a.csv", ["id,amount", "1,10.0", "2,20.0"])
    b = _write_csv(tmp_path, "b.csv", ["id,amount", "1,10.0"])  # id=2 missing entirely
    config = ComparisonConfig(key_columns=["id"])
    result = run_comparison({"a": a, "b": b}, config)
    assert result.matched_row_count == 1
    assert result.mismatched_row_count == 0
    assert result.only_in == {"a": 1, "b": 0}


def test_keyed_composite_key(tmp_path):
    a = _write_csv(tmp_path, "a.csv", ["region,id,amount", "us,1,10.0", "eu,1,20.0"])
    b = _write_csv(tmp_path, "b.csv", ["region,id,amount", "us,1,10.0", "eu,1,99.0"])
    config = ComparisonConfig(key_columns=["region", "id"])
    result = run_comparison({"a": a, "b": b}, config)
    assert result.matched_row_count == 1
    assert result.mismatched_row_count == 1


def test_keyed_three_way(tmp_path):
    a = _write_csv(tmp_path, "a.csv", ["id,amount", "1,10.0", "2,20.0", "3,30.0"])
    b = _write_csv(tmp_path, "b.csv", ["id,amount", "1,10.0", "2,25.0"])
    c = _write_csv(tmp_path, "c.csv", ["id,amount", "1,10.0", "2,20.0", "4,40.0"])
    config = ComparisonConfig(key_columns=["id"])
    result = run_comparison({"a": a, "b": b, "c": c}, config)
    assert result.matched_row_count == 1  # id=1
    assert result.mismatched_row_count == 1  # id=2, present in all 3, amount disagrees
    assert result.only_in == {"a": 1, "b": 0, "c": 1}  # id=3 (a only), id=4 (c only)


def test_keyed_null_safe_equality(tmp_path):
    """NULL should compare equal to NULL, not propagate to 'mismatched'."""
    a = _write_csv(tmp_path, "a.csv", ["id,note", "1,", "2,hello"])
    b = _write_csv(tmp_path, "b.csv", ["id,note", "1,", "2,hello"])
    config = ComparisonConfig(key_columns=["id"])
    result = run_comparison({"a": a, "b": b}, config)
    assert result.matched_row_count == 2
    assert result.mismatched_row_count == 0


def test_case_insensitive_comparison(tmp_path):
    a = _write_csv(tmp_path, "a.csv", ["id,name", "1,Alice"])
    b = _write_csv(tmp_path, "b.csv", ["id,name", "1,ALICE"])
    config = ComparisonConfig(key_columns=["id"], case_sensitive=False)
    result = run_comparison({"a": a, "b": b}, config)
    assert result.matched_row_count == 1
    assert result.mismatched_row_count == 0

    config_sensitive = ComparisonConfig(key_columns=["id"], case_sensitive=True)
    result_sensitive = run_comparison({"a": a, "b": b}, config_sensitive)
    assert result_sensitive.mismatched_row_count == 1


# ---------------------------------------------------------------------------
# Tolerance rules
# ---------------------------------------------------------------------------


def test_tolerance_absolute_within_bound_matches(tmp_path):
    a = _write_csv(tmp_path, "a.csv", ["id,amount", "1,10.00"])
    b = _write_csv(tmp_path, "b.csv", ["id,amount", "1,10.04"])
    config = ComparisonConfig(
        key_columns=["id"],
        tolerances=[ToleranceRule(column="amount", absolute=0.05)],
    )
    result = run_comparison({"a": a, "b": b}, config)
    assert result.matched_row_count == 1
    assert result.mismatched_row_count == 0


def test_tolerance_absolute_outside_bound_mismatches(tmp_path):
    a = _write_csv(tmp_path, "a.csv", ["id,amount", "1,10.00"])
    b = _write_csv(tmp_path, "b.csv", ["id,amount", "1,10.50"])
    config = ComparisonConfig(
        key_columns=["id"],
        tolerances=[ToleranceRule(column="amount", absolute=0.05)],
    )
    result = run_comparison({"a": a, "b": b}, config)
    assert result.mismatched_row_count == 1


def test_tolerance_relative_within_bound_matches(tmp_path):
    a = _write_csv(tmp_path, "a.csv", ["id,amount", "1,1000.0"])
    b = _write_csv(tmp_path, "b.csv", ["id,amount", "1,1005.0"])  # 0.5% off
    config = ComparisonConfig(
        key_columns=["id"],
        tolerances=[ToleranceRule(column="amount", relative=0.01)],  # 1% allowed
    )
    result = run_comparison({"a": a, "b": b}, config)
    assert result.matched_row_count == 1


def test_tolerance_requires_key_columns(tmp_path):
    a = _write_csv(tmp_path, "a.csv", ["id,amount", "1,10.0"])
    b = _write_csv(tmp_path, "b.csv", ["id,amount", "1,10.0"])
    config = ComparisonConfig(tolerances=[ToleranceRule(column="amount", absolute=0.1)])
    with pytest.raises(ConfigurationError, match="require key_columns"):
        run_comparison({"a": a, "b": b}, config)


def test_tolerance_on_unknown_column_raises(tmp_path):
    a = _write_csv(tmp_path, "a.csv", ["id,amount", "1,10.0"])
    b = _write_csv(tmp_path, "b.csv", ["id,amount", "1,10.0"])
    config = ComparisonConfig(
        key_columns=["id"],
        tolerances=[ToleranceRule(column="does_not_exist", absolute=0.1)],
    )
    with pytest.raises(ConfigurationError, match="unknown column"):
        run_comparison({"a": a, "b": b}, config)


def test_unknown_key_column_raises(tmp_path):
    a = _write_csv(tmp_path, "a.csv", ["id,amount", "1,10.0"])
    b = _write_csv(tmp_path, "b.csv", ["id,amount", "1,10.0"])
    config = ComparisonConfig(key_columns=["does_not_exist"])
    with pytest.raises(ConfigurationError, match="unknown column"):
        run_comparison({"a": a, "b": b}, config)


# ---------------------------------------------------------------------------
# ignore_columns and schema validation
# ---------------------------------------------------------------------------


def test_ignore_columns_excludes_from_comparison(tmp_path):
    a = _write_csv(tmp_path, "a.csv", ["id,amount,updated_at", "1,10.0,2026-01-01"])
    b = _write_csv(tmp_path, "b.csv", ["id,amount,updated_at", "1,10.0,2026-07-13"])
    config = ComparisonConfig(key_columns=["id"], ignore_columns=["updated_at"])
    result = run_comparison({"a": a, "b": b}, config)
    assert result.matched_row_count == 1
    assert result.mismatched_row_count == 0


def test_schema_mismatch_raises_with_details(tmp_path):
    a = _write_csv(tmp_path, "a.csv", ["id,amount", "1,10.0"])
    b = _write_csv(tmp_path, "b.csv", ["id,total", "1,10.0"])
    with pytest.raises(SchemaMismatchError, match="amount"):
        run_comparison({"a": a, "b": b}, ComparisonConfig())


# ---------------------------------------------------------------------------
# Sanity-check mode
# ---------------------------------------------------------------------------


def test_sanity_check_mode_flags_row_count_disparity(tmp_path):
    a_rows = ["id,amount"] + [f"{i},10.0" for i in range(100)]
    b_rows = ["id,amount"] + [f"{i},10.0" for i in range(50)]
    a = _write_csv(tmp_path, "a.csv", a_rows)
    b = _write_csv(tmp_path, "b.csv", b_rows)
    config = ComparisonConfig(key_columns=["id"], sanity_check_mode=True)
    result = run_comparison({"a": a, "b": b}, config)
    assert any("Row counts vary" in w for w in result.warnings)


def test_sanity_check_mode_off_by_default_produces_no_warnings(tmp_path):
    a_rows = ["id,amount"] + [f"{i},10.0" for i in range(100)]
    b_rows = ["id,amount"] + [f"{i},10.0" for i in range(10)]
    a = _write_csv(tmp_path, "a.csv", a_rows)
    b = _write_csv(tmp_path, "b.csv", b_rows)
    result = run_comparison({"a": a, "b": b}, ComparisonConfig(key_columns=["id"]))
    assert result.warnings == []
