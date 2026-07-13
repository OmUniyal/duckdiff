import pytest


@pytest.fixture
def sample_csv_pair(tmp_path):
    """Two tiny CSV files with a matching schema and one intentional mismatch."""
    left = tmp_path / "left.csv"
    right = tmp_path / "right.csv"
    left.write_text("id,name,amount\n1,alice,10.0\n2,bob,20.0\n")
    right.write_text("id,name,amount\n1,alice,10.0\n2,bob,25.0\n")
    return str(left), str(right)
