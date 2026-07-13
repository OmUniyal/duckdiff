from duckdiff.config import ComparisonConfig


def test_config_defaults_are_minimal():
    """Every opt-in feature must default to off — this is a core design guarantee."""
    config = ComparisonConfig()
    assert config.key_columns == []
    assert config.ignore_columns == []
    assert config.tolerances == []
    assert config.case_sensitive is True
    assert config.enable_fuzzy_column_mapping is False
    assert config.sanity_check_mode is False
