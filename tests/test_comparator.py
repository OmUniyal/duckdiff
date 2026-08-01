import csv

import pytest

from duckdiff.comparator import export_mismatches, run_comparison
from duckdiff.config import ComparisonConfig, ToleranceRule
from duckdiff.exceptions import ConfigurationError, SchemaMismatchError


def _write_csv(tmp_path, name, rows):
    path = tmp_path / name
    path.write_text("\n".join(rows) + "\n")
    return str(path)


# ---------------------------------------------------------------------------
# Full-row (no key_columns) mode
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
    assert result.matched_row_count == 1
    assert result.only_in == {"a": 1, "b": 1}


def test_full_row_mismatched_row_count_is_always_zero(tmp_path):
    a = _write_csv(tmp_path, "a.csv", ["id,amount", "1,10.0"])
    b = _write_csv(tmp_path, "b.csv", ["id,amount", "1,99.0"])
    result = run_comparison({"a": a, "b": b}, ComparisonConfig())
    assert result.mismatched_row_count == 0
    assert result.only_in == {"a": 1, "b": 1}


def test_full_row_duplicate_rows_use_bag_semantics(tmp_path):
    a = _write_csv(tmp_path, "a.csv", ["id,amount", "1,10.0", "1,10.0", "1,10.0"])
    b = _write_csv(tmp_path, "b.csv", ["id,amount", "1,10.0", "1,10.0"])
    result = run_comparison({"a": a, "b": b}, ComparisonConfig())
    assert result.matched_row_count == 2
    assert result.only_in == {"a": 1, "b": 0}


def test_full_row_three_way(tmp_path):
    a = _write_csv(tmp_path, "a.csv", ["id,amount", "1,10.0", "2,20.0", "3,30.0"])
    b = _write_csv(tmp_path, "b.csv", ["id,amount", "1,10.0", "2,25.0"])
    c = _write_csv(tmp_path, "c.csv", ["id,amount", "1,10.0", "2,20.0", "4,40.0"])
    result = run_comparison({"a": a, "b": b, "c": c}, ComparisonConfig())
    assert result.matched_row_count == 1
    assert result.only_in == {"a": 2, "b": 1, "c": 2}


# ---------------------------------------------------------------------------
# Keyed mode
# ---------------------------------------------------------------------------


def test_keyed_matched_and_mismatched(tmp_path):
    a = _write_csv(tmp_path, "a.csv", ["id,name,amount", "1,alice,10.0", "2,bob,20.0"])
    b = _write_csv(tmp_path, "b.csv", ["id,name,amount", "1,alice,10.0", "2,bob,25.0"])
    config = ComparisonConfig(key_columns=["id"])
    result = run_comparison({"a": a, "b": b}, config)
    assert result.matched_row_count == 1
    assert result.mismatched_row_count == 1
    assert result.only_in == {"a": 0, "b": 0}


def test_keyed_only_in_tracks_missing_keys(tmp_path):
    a = _write_csv(tmp_path, "a.csv", ["id,amount", "1,10.0", "2,20.0"])
    b = _write_csv(tmp_path, "b.csv", ["id,amount", "1,10.0"])
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
    assert result.matched_row_count == 1
    assert result.mismatched_row_count == 1
    assert result.only_in == {"a": 1, "b": 0, "c": 1}


def test_keyed_null_safe_equality(tmp_path):
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
    b = _write_csv(tmp_path, "b.csv", ["id,amount", "1,1005.0"])
    config = ComparisonConfig(
        key_columns=["id"],
        tolerances=[ToleranceRule(column="amount", relative=0.01)],
    )
    result = run_comparison({"a": a, "b": b}, config)
    assert result.matched_row_count == 1


def test_tolerance_requires_key_columns(tmp_path):
    a = _write_csv(tmp_path, "a.csv", ["id,amount", "1,10.0"])
    b = _write_csv(tmp_path, "b.csv", ["id,amount", "1,10.0"])
    config = ComparisonConfig(tolerances=[ToleranceRule(column="amount", absolute=0.1)])
    with pytest.raises(ConfigurationError, match="key_columns"):
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


def test_column_mapping_reconciles_renamed_columns(tmp_path):
    a = _write_csv(tmp_path, "a.csv", ["id,amount", "1,10.0"])
    b = _write_csv(tmp_path, "b.csv", ["id,total", "1,10.0"])
    config = ComparisonConfig(key_columns=["id"])
    mapping = {"b": {"total": "amount"}}
    result = run_comparison({"a": a, "b": b}, config, column_mapping=mapping)
    assert result.matched_row_count == 1
    assert result.mismatched_row_count == 0


def test_column_mapping_only_renames_mapped_columns(tmp_path):
    a = _write_csv(tmp_path, "a.csv", ["id,amount,note", "1,10.0,hi"])
    b = _write_csv(tmp_path, "b.csv", ["id,total,note", "1,10.0,hi"])
    config = ComparisonConfig(key_columns=["id"])
    mapping = {"b": {"total": "amount"}}
    result = run_comparison({"a": a, "b": b}, config, column_mapping=mapping)
    assert result.matched_row_count == 1


def test_no_mapping_still_requires_exact_schema_match(tmp_path):
    a = _write_csv(tmp_path, "a.csv", ["id,amount", "1,10.0"])
    b = _write_csv(tmp_path, "b.csv", ["id,total", "1,10.0"])
    with pytest.raises(SchemaMismatchError):
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


# ---------------------------------------------------------------------------
# Mismatch samples (bounded, in-result preview)
# ---------------------------------------------------------------------------


def test_mismatch_samples_disabled_by_default(tmp_path):
    a = _write_csv(tmp_path, "a.csv", ["id,amount", "1,10.0"])
    b = _write_csv(tmp_path, "b.csv", ["id,amount", "1,20.0"])
    result = run_comparison({"a": a, "b": b}, ComparisonConfig(key_columns=["id"]))
    assert result.mismatch_samples == []


def test_mismatch_samples_requires_key_columns(tmp_path):
    a = _write_csv(tmp_path, "a.csv", ["id,amount", "1,10.0"])
    b = _write_csv(tmp_path, "b.csv", ["id,amount", "1,10.0"])
    config = ComparisonConfig(include_mismatch_samples=True)
    with pytest.raises(ConfigurationError, match="key_columns"):
        run_comparison({"a": a, "b": b}, config)


def test_mismatch_samples_captures_differing_columns(tmp_path):
    a = _write_csv(tmp_path, "a.csv", ["id,amount,region", "1,10.0,us"])
    b = _write_csv(tmp_path, "b.csv", ["id,amount,region", "1,20.0,eu"])
    config = ComparisonConfig(key_columns=["id"], include_mismatch_samples=True)
    result = run_comparison({"a": a, "b": b}, config)

    assert len(result.mismatch_samples) == 1
    sample = result.mismatch_samples[0]
    assert sample.key == {"id": 1}
    # CSV parsing returns strings for all values
    assert sample.differences == {
        "amount": {"a": "10.0", "b": "20.0"},
        "region": {"a": "us", "b": "eu"},
    }


def test_mismatch_samples_groups_by_key_not_scattered(tmp_path):
    """A single row that differs on two columns should produce ONE sample
    with two entries in `differences`, not two separate samples."""
    a = _write_csv(tmp_path, "a.csv", ["id,amount,region", "1,10.0,us", "2,20.0,us"])
    b = _write_csv(tmp_path, "b.csv", ["id,amount,region", "1,99.0,eu", "2,20.0,us"])
    config = ComparisonConfig(key_columns=["id"], include_mismatch_samples=True)
    result = run_comparison({"a": a, "b": b}, config)

    assert len(result.mismatch_samples) == 1
    assert set(result.mismatch_samples[0].differences) == {"amount", "region"}


def test_mismatch_samples_respects_sample_size_limit(tmp_path):
    a_rows = ["id,amount"] + [f"{i},10.0" for i in range(10)]
    b_rows = ["id,amount"] + [f"{i},99.0" for i in range(10)]
    a = _write_csv(tmp_path, "a.csv", a_rows)
    b = _write_csv(tmp_path, "b.csv", b_rows)
    config = ComparisonConfig(
        key_columns=["id"], include_mismatch_samples=True, mismatch_sample_size=3
    )
    result = run_comparison({"a": a, "b": b}, config)
    assert result.mismatched_row_count == 10
    assert len(result.mismatch_samples) == 3


def test_mismatch_samples_three_way(tmp_path):
    a = _write_csv(tmp_path, "a.csv", ["id,amount", "1,10.0"])
    b = _write_csv(tmp_path, "b.csv", ["id,amount", "1,10.0"])
    c = _write_csv(tmp_path, "c.csv", ["id,amount", "1,99.0"])
    config = ComparisonConfig(key_columns=["id"], include_mismatch_samples=True)
    result = run_comparison({"a": a, "b": b, "c": c}, config)

    assert len(result.mismatch_samples) == 1
    assert result.mismatch_samples[0].differences["amount"] == {
        "a": "10.0",
        "b": "10.0",
        "c": "99.0",
    }


def test_mismatch_samples_ignore_tolerance_matched_values(tmp_path):
    a = _write_csv(tmp_path, "a.csv", ["id,amount", "1,10.00"])
    b = _write_csv(tmp_path, "b.csv", ["id,amount", "1,10.02"])
    config = ComparisonConfig(
        key_columns=["id"],
        include_mismatch_samples=True,
        tolerances=[ToleranceRule(column="amount", absolute=0.05)],
    )
    result = run_comparison({"a": a, "b": b}, config)
    assert result.mismatched_row_count == 0
    assert result.mismatch_samples == []


# ---------------------------------------------------------------------------
# export_mismatches (full, unbounded, streamed to disk)
# ---------------------------------------------------------------------------


def _read_csv_rows(path):
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def test_export_mismatches_requires_key_columns(tmp_path):
    a = _write_csv(tmp_path, "a.csv", ["id,amount", "1,10.0"])
    b = _write_csv(tmp_path, "b.csv", ["id,amount", "1,10.0"])
    with pytest.raises(ConfigurationError, match="key_columns"):
        export_mismatches({"a": a, "b": b}, ComparisonConfig(), str(tmp_path / "out.csv"))


def test_export_mismatches_writes_melted_mismatches_file(tmp_path):
    a = _write_csv(tmp_path, "a.csv", ["id,amount,region", "1,10.0,us", "2,20.0,us"])
    b = _write_csv(tmp_path, "b.csv", ["id,amount,region", "1,99.0,eu", "2,20.0,us"])
    config = ComparisonConfig(key_columns=["id"])
    out = str(tmp_path / "result.csv")
    export_mismatches({"a": a, "b": b}, config, out)

    rows = _read_csv_rows(tmp_path / "result_mismatches.csv")
    by_column = {r["column"]: r for r in rows}
    assert set(by_column) == {"amount", "region"}
    assert by_column["amount"]["a_value"] == "10.0"
    assert by_column["amount"]["b_value"] == "99.0"
    assert by_column["region"]["a_value"] == "us"
    assert by_column["region"]["b_value"] == "eu"


def test_export_mismatches_writes_only_in_files_with_full_source_columns(tmp_path):
    """Fix #1: an only-in row shows ALL of that source's columns, including
    ones ignored for comparison purposes."""
    a = _write_csv(
        tmp_path,
        "a.csv",
        ["id,amount,notes", "1,10.0,shared-row", "3,30.0,unique-to-a"],
    )
    b = _write_csv(tmp_path, "b.csv", ["id,amount", "1,10.0", "4,40.0"])
    config = ComparisonConfig(key_columns=["id"], ignore_columns=["notes"])
    out = str(tmp_path / "result.csv")
    export_mismatches({"a": a, "b": b}, config, out)

    only_in_a = _read_csv_rows(tmp_path / "result_only_in_a.csv")
    assert len(only_in_a) == 1
    assert only_in_a[0]["id"] == "3"
    assert only_in_a[0]["notes"] == "unique-to-a"

    only_in_b = _read_csv_rows(tmp_path / "result_only_in_b.csv")
    assert len(only_in_b) == 1
    assert only_in_b[0]["id"] == "4"


def test_export_writes_header_only_files_when_nothing_to_report(tmp_path):
    a = _write_csv(tmp_path, "a.csv", ["id,amount", "1,10.0"])
    b = _write_csv(tmp_path, "b.csv", ["id,amount", "1,10.0"])
    config = ComparisonConfig(key_columns=["id"])
    out = str(tmp_path / "result.csv")
    export_mismatches({"a": a, "b": b}, config, out)

    assert _read_csv_rows(tmp_path / "result_mismatches.csv") == []
    assert _read_csv_rows(tmp_path / "result_only_in_a.csv") == []
    assert _read_csv_rows(tmp_path / "result_only_in_b.csv") == []
    with open(tmp_path / "result_mismatches.csv") as f:
        assert f.readline().strip() == "id,column,a_value,b_value"


def test_export_derives_filenames_from_given_path(tmp_path):
    a = _write_csv(tmp_path, "a.csv", ["id,amount", "1,10.0"])
    b = _write_csv(tmp_path, "b.csv", ["id,amount", "1,99.0"])
    config = ComparisonConfig(key_columns=["id"])
    export_mismatches({"a": a, "b": b}, config, str(tmp_path / "my_report.csv"))

    assert (tmp_path / "my_report_mismatches.csv").exists()
    assert (tmp_path / "my_report_only_in_a.csv").exists()
    assert (tmp_path / "my_report_only_in_b.csv").exists()


def test_export_three_way_creates_one_only_in_file_per_source(tmp_path):
    a = _write_csv(tmp_path, "a.csv", ["id,amount", "1,10.0", "2,20.0"])
    b = _write_csv(tmp_path, "b.csv", ["id,amount", "1,10.0", "3,30.0"])
    c = _write_csv(tmp_path, "c.csv", ["id,amount", "1,10.0", "4,40.0"])
    config = ComparisonConfig(key_columns=["id"])
    out = str(tmp_path / "result.csv")
    export_mismatches({"a": a, "b": b, "c": c}, config, out)

    assert len(_read_csv_rows(tmp_path / "result_only_in_a.csv")) == 1
    assert len(_read_csv_rows(tmp_path / "result_only_in_b.csv")) == 1
    assert len(_read_csv_rows(tmp_path / "result_only_in_c.csv")) == 1


# ---------------------------------------------------------------------------
# Auto-intersect columns
# ---------------------------------------------------------------------------


def test_auto_intersect_off_by_default_still_raises_on_mismatch(tmp_path):
    a = _write_csv(tmp_path, "a.csv", ["id,amount", "1,10.0"])
    b = _write_csv(tmp_path, "b.csv", ["id,total", "1,10.0"])
    with pytest.raises(SchemaMismatchError):
        run_comparison({"a": a, "b": b}, ComparisonConfig())


def test_auto_intersect_compares_shared_columns_only(tmp_path):
    """a has 'notes', b doesn't -- with auto_intersect, comparison proceeds
    on the shared columns (id, amount) and 'notes' is dropped with a warning."""
    a = _write_csv(tmp_path, "a.csv", ["id,amount,notes", "1,10.0,x", "2,20.0,y"])
    b = _write_csv(tmp_path, "b.csv", ["id,amount", "1,10.0", "2,25.0"])
    config = ComparisonConfig(key_columns=["id"], auto_intersect_columns=True)
    result = run_comparison({"a": a, "b": b}, config)

    assert result.matched_row_count == 1
    assert result.mismatched_row_count == 1
    assert any("notes" in w for w in result.warnings)


def test_auto_intersect_warning_names_the_source_and_dropped_columns(tmp_path):
    a = _write_csv(tmp_path, "a.csv", ["id,amount,region", "1,10.0,us"])
    b = _write_csv(tmp_path, "b.csv", ["id,amount", "1,10.0"])
    config = ComparisonConfig(key_columns=["id"], auto_intersect_columns=True)
    result = run_comparison({"a": a, "b": b}, config)

    assert len(result.warnings) == 1
    assert "region" in result.warnings[0]
    assert "a" in result.warnings[0]


def test_auto_intersect_no_warning_when_schemas_already_match(tmp_path):
    a = _write_csv(tmp_path, "a.csv", ["id,amount", "1,10.0"])
    b = _write_csv(tmp_path, "b.csv", ["id,amount", "1,10.0"])
    config = ComparisonConfig(key_columns=["id"], auto_intersect_columns=True)
    result = run_comparison({"a": a, "b": b}, config)
    assert result.warnings == []


def test_auto_intersect_raises_when_no_shared_columns(tmp_path):
    a = _write_csv(tmp_path, "a.csv", ["id,amount", "1,10.0"])
    b = _write_csv(tmp_path, "b.csv", ["id,region", "1,us"])
    config = ComparisonConfig(key_columns=["id"], auto_intersect_columns=True)
    with pytest.raises(ConfigurationError, match="No columns are shared"):
        run_comparison({"a": a, "b": b}, config)


def test_auto_intersect_three_way(tmp_path):
    """Only 'amount' is shared across all three -- 'notes' (only in a)
    and 'region' (only in b) both get dropped."""
    a = _write_csv(tmp_path, "a.csv", ["id,amount,notes", "1,10.0,x"])
    b = _write_csv(tmp_path, "b.csv", ["id,amount,region", "1,10.0,us"])
    c = _write_csv(tmp_path, "c.csv", ["id,amount", "1,10.0"])
    config = ComparisonConfig(key_columns=["id"], auto_intersect_columns=True)
    result = run_comparison({"a": a, "b": b, "c": c}, config)

    assert result.matched_row_count == 1
    assert len(result.warnings) == 2