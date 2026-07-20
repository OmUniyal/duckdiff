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
    """Regression test for the exact bug the UUID-keyed rows were built to
    avoid: index-based widget keys would show stale/swapped values on the
    rows after a removed one, since Streamlit's per-key state doesn't
    shift when the underlying list does."""
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

    assert not at.exception  # the app itself shouldn't crash
    assert len(at.error) == 1
    assert at.error[0].value.startswith("Error:")


def test_compare_ignores_sources_with_blank_name_or_path(tmp_path):
    """A third, never-filled-in row (e.g. from a stray '+ Add source'
    click) shouldn't be passed to ComparisonSession at all."""
    a = _write_csv(tmp_path, "a.csv", ["id,amount", "1,10.0"])
    b = _write_csv(tmp_path, "b.csv", ["id,amount", "1,10.0"])

    at = AppTest.from_file(APP_PATH)
    at.run()

    sources = at.session_state.sources
    a_id, b_id = sources[0]["id"], sources[1]["id"]
    at.text_input(key=f"path_{a_id}").set_value(a).run()
    at.text_input(key=f"path_{b_id}").set_value(b).run()

    _find_button(at, "+ Add source").click().run()  # leave the 3rd row blank
    at.text_input(key="key_columns_input").set_value("id").run()

    _find_button(at, "Compare").click().run()

    assert not at.exception
    assert len(at.error) == 0
    markdown_text = "\n".join(m.value for m in at.markdown)
    assert "**Matched:** 1" in markdown_text