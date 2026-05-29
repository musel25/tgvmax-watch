def test_fixture_loads(sncf_search_response):
    assert isinstance(sncf_search_response, dict)
    assert sncf_search_response  # non-empty
