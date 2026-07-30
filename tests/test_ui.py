from pathlib import Path

from streamlit.testing.v1 import AppTest

APP_PATH = "src/duckdiff/ui/app.py"


def _find_button(at, label):
    for button in at.button:
        if button.label == label:
            return button
    raise ValueError(f"no button labeled {label!r}")


def _write_csv(tmp_path, name, rows):
    path = tmp_path / name
    path.write_text("\n".join(rows) + "\n")
    return str(path)


def test_app_renders_with_no_exception_and_two_default_sources():
    at = AppTest.from_file(APP_PATH)
    at.run()
    assert not at.exception
    assert len(at.session_state.sources) == 2
    assert at.session_state.sources[0]["name"] == "a"
    assert at.session_state.sources[1]["name"] == "b"


def test_add_source_appends_a_row_with_the_next_letter():
    at = AppTest.from_file(APP_PATH)
    at.run()
    _find_button(at, "+ Add source").click().run()
    assert len(at.session_state.sources) == 3
    assert at.session_state.sources[2]["name"] == "c"


def test_remove_button_disabled_at_minimum_two_sources():
    at = AppTest.from_file(APP_PATH)
    at.run()
    row_id = at.session_state.sources[0]["id"]
    assert at.button(key=f"remove_{row_id}").disabled is True


def test_removing_middle_source_does_not_corrupt_remaining_rows():
    at = AppTest.from_file(APP_PATH)
    at.run()

    sources = at.session_state.sources
    a_id, b_id = sources[0]["id"], sources[1]["id"]
    at.text_input(key=f"path_{a_id}").set_value("A_FILE.csv").run()
    at.text_input(key=f"path_{b_id}").set_value("B_FILE.csv").run()

    _find_button(at, "+ Add source").click().run()
    c_id = at.session_state.sources[2]["id"]
    at.text_input(key=f"path_{c_id}").set_value("C_FILE.csv").run()

    at.button(key=f"remove_{b_id}").click().run()

    remaining = {s["name"]: s["path"] for s in at.session_state.sources}
    assert remaining == {"a": "A_FILE.csv", "c": "C_FILE.csv"}


# ---------------------------------------------------------------------------
# Compare flow end-to-end
# ---------------------------------------------------------------------------


def test_compare_shows_matched_and_mismatched_counts(tmp_path):
    a = _write_csv(tmp_path, "a.csv", ["id,amount", "1,10.0", "2,20.0"])
    b = _write_csv(tmp_path, "b.csv", ["id,amount", "1,10.0", "2,25.0"])

    at = AppTest.from_file(APP_PATH)
    at.run()

    sources = at.session_state.sources
    a_id, b_id = sources[0]["id"], sources[1]["id"]
    at.text_input(key=f"path_{a_id}").set_value(a).run()
    at.text_input(key=f"path_{b_id}").set_value(b).run()
    at.text_input(key="key_columns_input").set_value("id").run()

    _find_button(at, "Compare").click().run()

    assert not at.exception
    assert len(at.error) == 0
    markdown_text = "\n".join(m.value for m in at.markdown)
    assert "**Matched:** 1" in markdown_text
    assert "**Mismatched:** 1" in markdown_text


def test_compare_shows_friendly_error_on_schema_mismatch(tmp_path):
    a = _write_csv(tmp_path, "a.csv", ["id,amount", "1,10.0"])
    b = _write_csv(tmp_path, "b.csv", ["id,total", "1,10.0"])

    at = AppTest.from_file(APP_PATH)
    at.run()

    sources = at.session_state.sources
    a_id, b_id = sources[0]["id"], sources[1]["id"]
    at.text_input(key=f"path_{a_id}").set_value(a).run()
    at.text_input(key=f"path_{b_id}").set_value(b).run()

    _find_button(at, "Compare").click().run()

    assert not at.exception
    assert len(at.error) == 1
    assert at.error[0].value.startswith("Error:")


def test_compare_ignores_sources_with_blank_name_or_path(tmp_path):
    a = _write_csv(tmp_path, "a.csv", ["id,amount", "1,10.0"])
    b = _write_csv(tmp_path, "b.csv", ["id,amount", "1,10.0"])

    at = AppTest.from_file(APP_PATH)
    at.run()

    sources = at.session_state.sources
    a_id, b_id = sources[0]["id"], sources[1]["id"]
    at.text_input(key=f"path_{a_id}").set_value(a).run()
    at.text_input(key=f"path_{b_id}").set_value(b).run()

    _find_button(at, "+ Add source").click().run()
    at.text_input(key="key_columns_input").set_value("id").run()

    _find_button(at, "Compare").click().run()

    assert not at.exception
    assert len(at.error) == 0
    markdown_text = "\n".join(m.value for m in at.markdown)
    assert "**Matched:** 1" in markdown_text


# ---------------------------------------------------------------------------
# Mismatch sample preview
# ---------------------------------------------------------------------------


def test_mismatch_samples_shown_after_compare_with_key_columns(tmp_path):
    a = _write_csv(tmp_path, "a.csv", ["id,amount", "1,10.0", "2,20.0"])
    b = _write_csv(tmp_path, "b.csv", ["id,amount", "1,10.0", "2,99.0"])

    at = AppTest.from_file(APP_PATH)
    at.run()

    sources = at.session_state.sources
    a_id, b_id = sources[0]["id"], sources[1]["id"]
    at.text_input(key=f"path_{a_id}").set_value(a).run()
    at.text_input(key=f"path_{b_id}").set_value(b).run()
    at.text_input(key="key_columns_input").set_value("id").run()

    _find_button(at, "Compare").click().run()

    assert not at.exception
    result = at.session_state.last_result
    assert result is not None
    assert len(result.mismatch_samples) == 1
    assert result.mismatch_samples[0].key == {"id": 2}
    assert "amount" in result.mismatch_samples[0].differences


def test_mismatch_samples_not_shown_when_no_key_columns(tmp_path):
    """Full-row mode has no concept of mismatched rows, so no samples."""
    a = _write_csv(tmp_path, "a.csv", ["id,amount", "1,10.0"])
    b = _write_csv(tmp_path, "b.csv", ["id,amount", "1,99.0"])

    at = AppTest.from_file(APP_PATH)
    at.run()

    sources = at.session_state.sources
    a_id, b_id = sources[0]["id"], sources[1]["id"]
    at.text_input(key=f"path_{a_id}").set_value(a).run()
    at.text_input(key=f"path_{b_id}").set_value(b).run()
    # No key_columns_input set -- full-row mode

    _find_button(at, "Compare").click().run()

    assert not at.exception
    result = at.session_state.last_result
    assert result is not None
    assert result.mismatch_samples == []


def test_result_session_kept_alive_after_compare(tmp_path):
    """The session must survive past compare() so export can reuse it."""
    a = _write_csv(tmp_path, "a.csv", ["id,amount", "1,10.0"])
    b = _write_csv(tmp_path, "b.csv", ["id,amount", "1,99.0"])

    at = AppTest.from_file(APP_PATH)
    at.run()

    sources = at.session_state.sources
    a_id, b_id = sources[0]["id"], sources[1]["id"]
    at.text_input(key=f"path_{a_id}").set_value(a).run()
    at.text_input(key=f"path_{b_id}").set_value(b).run()
    at.text_input(key="key_columns_input").set_value("id").run()

    _find_button(at, "Compare").click().run()

    assert at.session_state.result_session is not None


def test_new_compare_closes_previous_result_session(tmp_path):
    """A fresh Compare should tear down the old result_session cleanly."""
    a = _write_csv(tmp_path, "a.csv", ["id,amount", "1,10.0"])
    b = _write_csv(tmp_path, "b.csv", ["id,amount", "1,99.0"])

    at = AppTest.from_file(APP_PATH)
    at.run()

    sources = at.session_state.sources
    a_id, b_id = sources[0]["id"], sources[1]["id"]
    at.text_input(key=f"path_{a_id}").set_value(a).run()
    at.text_input(key=f"path_{b_id}").set_value(b).run()
    at.text_input(key="key_columns_input").set_value("id").run()

    _find_button(at, "Compare").click().run()
    first_session = at.session_state.result_session

    _find_button(at, "Compare").click().run()
    second_session = at.session_state.result_session

    assert first_session is not second_session


# ---------------------------------------------------------------------------
# Export flow
# ---------------------------------------------------------------------------


def test_export_default_path_derived_from_source_a(tmp_path):
    a = _write_csv(tmp_path, "a.csv", ["id,amount", "1,10.0"])
    b = _write_csv(tmp_path, "b.csv", ["id,amount", "1,99.0"])

    at = AppTest.from_file(APP_PATH)
    at.run()

    sources = at.session_state.sources
    a_id, b_id = sources[0]["id"], sources[1]["id"]
    at.text_input(key=f"path_{a_id}").set_value(a).run()
    at.text_input(key=f"path_{b_id}").set_value(b).run()
    at.text_input(key="key_columns_input").set_value("id").run()

    _find_button(at, "Compare").click().run()

    export_input = at.text_input(key="export_path_input")
    expected_dir = str(Path(a).parent)
    assert export_input.value.startswith(expected_dir)
    assert export_input.value.endswith(".csv")


def test_export_writes_files_to_disk(tmp_path):
    a = _write_csv(tmp_path, "a.csv", ["id,amount", "1,10.0", "2,20.0"])
    b = _write_csv(tmp_path, "b.csv", ["id,amount", "1,10.0", "2,99.0"])
    out = str(tmp_path / "result.csv")

    at = AppTest.from_file(APP_PATH)
    at.run()

    sources = at.session_state.sources
    a_id, b_id = sources[0]["id"], sources[1]["id"]
    at.text_input(key=f"path_{a_id}").set_value(a).run()
    at.text_input(key=f"path_{b_id}").set_value(b).run()
    at.text_input(key="key_columns_input").set_value("id").run()

    _find_button(at, "Compare").click().run()
    at.text_input(key="export_path_input").set_value(out).run()
    _find_button(at, "Export to files").click().run()

    assert not at.exception
    assert len(at.success) == 1
    assert (tmp_path / "result_mismatches.csv").exists()
    assert (tmp_path / "result_only_in_a.csv").exists()
    assert (tmp_path / "result_only_in_b.csv").exists()


def test_export_not_shown_when_everything_matches(tmp_path):
    """No export section when matched=all, mismatched=0, only_in=0."""
    a = _write_csv(tmp_path, "a.csv", ["id,amount", "1,10.0"])
    b = _write_csv(tmp_path, "b.csv", ["id,amount", "1,10.0"])

    at = AppTest.from_file(APP_PATH)
    at.run()

    sources = at.session_state.sources
    a_id, b_id = sources[0]["id"], sources[1]["id"]
    at.text_input(key=f"path_{a_id}").set_value(a).run()
    at.text_input(key=f"path_{b_id}").set_value(b).run()
    at.text_input(key="key_columns_input").set_value("id").run()

    _find_button(at, "Compare").click().run()

    assert not at.exception
    # Export path input should not appear when there's nothing to export
    export_keys = [ti.key for ti in at.text_input]
    assert "export_path_input" not in export_keys


# ---------------------------------------------------------------------------
# Fuzzy-mapping retry flow
# ---------------------------------------------------------------------------


def _set_two_sources(at, a_path, b_path):
    sources = at.session_state.sources
    a_id, b_id = sources[0]["id"], sources[1]["id"]
    at.text_input(key=f"path_{a_id}").set_value(a_path).run()
    at.text_input(key=f"path_{b_id}").set_value(b_path).run()


def test_schema_mismatch_shows_error_and_suggest_button(tmp_path):
    a = _write_csv(tmp_path, "a.csv", ["customer_id,amount", "1,10.0"])
    b = _write_csv(tmp_path, "b.csv", ["cust_id,amount", "1,10.0"])

    at = AppTest.from_file(APP_PATH)
    at.run()
    _set_two_sources(at, a, b)
    at.text_input(key="key_columns_input").set_value("customer_id").run()

    _find_button(at, "Compare").click().run()

    assert not at.exception
    assert len(at.error) == 1
    assert at.error[0].value.startswith("Error:")
    assert _find_button(at, "Suggest column mapping") is not None


def test_error_message_persists_after_clicking_suggest(tmp_path):
    a = _write_csv(tmp_path, "a.csv", ["customer_id,amount", "1,10.0"])
    b = _write_csv(tmp_path, "b.csv", ["cust_id,amount", "1,10.0"])

    at = AppTest.from_file(APP_PATH)
    at.run()
    _set_two_sources(at, a, b)
    at.text_input(key="key_columns_input").set_value("customer_id").run()
    _find_button(at, "Compare").click().run()

    _find_button(at, "Suggest column mapping").click().run()

    assert not at.exception
    assert len(at.error) == 1
    assert at.error[0].value.startswith("Error:")


def test_suggest_then_apply_and_retry_succeeds(tmp_path):
    a = _write_csv(tmp_path, "a.csv", ["customer_id,amount", "1,10.0", "2,20.0"])
    b = _write_csv(tmp_path, "b.csv", ["cust_id,amount", "1,10.0", "2,25.0"])

    at = AppTest.from_file(APP_PATH)
    at.run()
    _set_two_sources(at, a, b)
    at.text_input(key="key_columns_input").set_value("customer_id").run()
    _find_button(at, "Compare").click().run()
    _find_button(at, "Suggest column mapping").click().run()

    assert at.session_state.suggested_mapping == {"b": {"cust_id": "customer_id"}}

    _find_button(at, "Apply and retry").click().run()

    assert not at.exception
    assert len(at.error) == 0
    markdown_text = "\n".join(m.value for m in at.markdown)
    assert "**Matched:** 1" in markdown_text
    assert "**Mismatched:** 1" in markdown_text
    assert at.session_state.pending_session is None


def test_no_suggestions_available_shows_info_message(tmp_path):
    a = _write_csv(tmp_path, "a.csv", ["id,amount", "1,10.0"])
    b = _write_csv(tmp_path, "b.csv", ["id,region", "1,us"])

    at = AppTest.from_file(APP_PATH)
    at.run()
    _set_two_sources(at, a, b)

    _find_button(at, "Compare").click().run()
    _find_button(at, "Suggest column mapping").click().run()

    assert not at.exception
    assert len(at.info) == 1
    assert "No fuzzy column-mapping suggestions found" in at.info[0].value


def test_new_compare_click_abandons_unfinished_retry_flow(tmp_path):
    a = _write_csv(tmp_path, "a.csv", ["customer_id,amount", "1,10.0"])
    b = _write_csv(tmp_path, "b.csv", ["cust_id,amount", "1,10.0"])
    a2 = _write_csv(tmp_path, "a2.csv", ["id,amount", "1,10.0"])
    b2 = _write_csv(tmp_path, "b2.csv", ["id,amount", "1,10.0"])

    at = AppTest.from_file(APP_PATH)
    at.run()
    _set_two_sources(at, a, b)
    at.text_input(key="key_columns_input").set_value("customer_id").run()
    _find_button(at, "Compare").click().run()
    assert at.session_state.pending_session is not None

    _set_two_sources(at, a2, b2)
    at.text_input(key="key_columns_input").set_value("id").run()
    _find_button(at, "Compare").click().run()

    assert not at.exception
    assert len(at.error) == 0
    markdown_text = "\n".join(m.value for m in at.markdown)
    assert "**Matched:** 1" in markdown_text
    assert at.session_state.pending_session is None


# ---------------------------------------------------------------------------
# Parameter parity -- ignore columns and tolerance rules
# ---------------------------------------------------------------------------


def test_ignore_columns_excludes_from_comparison(tmp_path):
    a = _write_csv(tmp_path, "a.csv", ["id,amount,note", "1,10.0,x"])
    b = _write_csv(tmp_path, "b.csv", ["id,amount,note", "1,10.0,y"])

    at = AppTest.from_file(APP_PATH)
    at.run()

    sources = at.session_state.sources
    a_id, b_id = sources[0]["id"], sources[1]["id"]
    at.text_input(key=f"path_{a_id}").set_value(a).run()
    at.text_input(key=f"path_{b_id}").set_value(b).run()
    at.text_input(key="key_columns_input").set_value("id").run()
    at.text_input(key="ignore_columns_input").set_value("note").run()

    _find_button(at, "Compare").click().run()

    assert not at.exception
    assert len(at.error) == 0
    markdown_text = "\n".join(m.value for m in at.markdown)
    assert "**Matched:** 1" in markdown_text
    assert "**Mismatched:** 0" in markdown_text


def test_tolerance_abs_wired_into_config(tmp_path):
    """amount differs by 0.03 -- without tolerance it mismatches,
    with absolute tolerance of 0.05 it should match."""
    a = _write_csv(tmp_path, "a.csv", ["id,amount", "1,10.00"])
    b = _write_csv(tmp_path, "b.csv", ["id,amount", "1,10.03"])

    at = AppTest.from_file(APP_PATH)
    at.run()

    sources = at.session_state.sources
    a_id, b_id = sources[0]["id"], sources[1]["id"]
    at.text_input(key=f"path_{a_id}").set_value(a).run()
    at.text_input(key=f"path_{b_id}").set_value(b).run()
    at.text_input(key="key_columns_input").set_value("id").run()
    at.text_input(key="tolerance_abs_input").set_value("amount=0.05").run()

    _find_button(at, "Compare").click().run()

    assert not at.exception
    assert len(at.error) == 0
    markdown_text = "\n".join(m.value for m in at.markdown)
    assert "**Matched:** 1" in markdown_text
    assert "**Mismatched:** 0" in markdown_text


def test_tolerance_rel_wired_into_config(tmp_path):
    """1005 vs 1000 is 0.5% -- within 1% relative tolerance."""
    a = _write_csv(tmp_path, "a.csv", ["id,amount", "1,1000.0"])
    b = _write_csv(tmp_path, "b.csv", ["id,amount", "1,1005.0"])

    at = AppTest.from_file(APP_PATH)
    at.run()

    sources = at.session_state.sources
    a_id, b_id = sources[0]["id"], sources[1]["id"]
    at.text_input(key=f"path_{a_id}").set_value(a).run()
    at.text_input(key=f"path_{b_id}").set_value(b).run()
    at.text_input(key="key_columns_input").set_value("id").run()
    at.text_input(key="tolerance_rel_input").set_value("amount=0.01").run()

    _find_button(at, "Compare").click().run()

    assert not at.exception
    assert len(at.error) == 0
    markdown_text = "\n".join(m.value for m in at.markdown)
    assert "**Matched:** 1" in markdown_text


def test_malformed_tolerance_input_silently_skipped(tmp_path):
    """A half-typed tolerance like 'amount=' shouldn't crash the app --
    _parse_kv_floats skips entries it can't parse."""
    a = _write_csv(tmp_path, "a.csv", ["id,amount", "1,10.0"])
    b = _write_csv(tmp_path, "b.csv", ["id,amount", "1,10.0"])

    at = AppTest.from_file(APP_PATH)
    at.run()

    sources = at.session_state.sources
    a_id, b_id = sources[0]["id"], sources[1]["id"]
    at.text_input(key=f"path_{a_id}").set_value(a).run()
    at.text_input(key=f"path_{b_id}").set_value(b).run()
    at.text_input(key="key_columns_input").set_value("id").run()
    at.text_input(key="tolerance_abs_input").set_value("amount=").run()

    _find_button(at, "Compare").click().run()

    assert not at.exception
    assert len(at.error) == 0