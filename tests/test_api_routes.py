def test_contracts_router():
    from src.api.routes.contracts import router
    assert router.prefix == "/api"

def test_scrip_router():
    from src.api.routes.scrip import router
    assert router.prefix == "/api/scrip"

def test_search_router():
    from src.api.routes.search import router
    assert router.prefix == "/api"

def test_tiers_router():
    from src.api.routes.tiers import router
    assert router.prefix == "/api"

def test_health_router():
    from src.api.routes.health import router
    assert router.prefix == "/api"
