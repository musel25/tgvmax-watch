from tgvmax_watch import config as cfgmod


def test_paid_config_defaults_and_load(tmp_path):
    yaml_text = (
        "origins:\n  paris:\n    - \"PARIS (intramuros)\"\n"
        "max_paid_price: 30\n"
        "paid_lookup_min_weight: 80\n"
        "cities:\n"
        "  - name: Nice\n    region: south\n    stations: [\"NICE VILLE\"]\n    base_weight: 100\n"
        "scheduling:\n"
        "  south:\n    friday_out_windows: [[\"18:00\",\"23:00\"]]\n"
        "    saturday_out_windows: [[\"06:00\",\"12:00\"]]\n"
        "    return_windows: [[\"06:00\",\"11:00\"]]\n"
    )
    p = tmp_path / "c.yaml"
    p.write_text(yaml_text)
    cfg = cfgmod.load(p)
    assert cfg.max_paid_price == 30.0
    assert cfg.paid_lookup_min_weight == 80
