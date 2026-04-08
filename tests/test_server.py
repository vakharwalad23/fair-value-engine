def test_app_exists():
    from server import app
    assert app is not None
    assert app.title == "F&O Fair Engine"
