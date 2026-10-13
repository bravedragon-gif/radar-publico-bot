from app.core import format_pncp

def test_empty_sample_disclaimer():
    assert 'amostra' in format_pncp([])
