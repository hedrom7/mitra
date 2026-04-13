from pathlib import Path

def test_url_to_local_path_basic(tmp_path):
    from site_downloader.path_utils import url_to_local_path

    mapping = url_to_local_path(tmp_path, "https://example.com/about")
    assert mapping.full_path.suffix == ".html"
    assert mapping.full_path.name == "about.html"
    assert mapping.full_path.parent.name == "example.com"


def test_url_to_local_path_query_hash(tmp_path):
    from site_downloader.path_utils import url_to_local_path

    mapping = url_to_local_path(tmp_path, "https://example.com/data?id=5", content_type="application/json")
    assert mapping.full_path.suffix == ".json"
    assert "__" in mapping.full_path.name
    assert mapping.full_path.parent.name == "example.com"


def test_make_relative(tmp_path):
    from site_downloader.path_utils import make_relative

    base = tmp_path / "example.com" / "index.html"
    asset = tmp_path / "example.com" / "assets" / "script.js"
    asset.parent.mkdir(parents=True)
    base.write_text("test")
    asset.write_text("document")

    relative = make_relative(base, asset)
    assert relative == "assets/script.js"
