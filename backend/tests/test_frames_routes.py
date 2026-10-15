"""Regression tests for the frames route table.

``create_frames_bulk`` was mis-decorated as ``GET ""``: a body-bearing GET
that was registered before ``list_frames`` and therefore shadowed every
``GET /frames?scene_id=...`` request (clients saw 422 "frames body required").
It now lives at ``POST /frames/bulk``.
"""
from app.api.v1.endpoints import frames


def _routes():
    table = {}
    for route in frames.router.routes:
        methods = tuple(sorted(m for m in route.methods if m != "HEAD"))
        table.setdefault(route.path, set()).update(methods)
    return table


def test_list_frames_is_get_on_root():
    table = _routes()
    assert "GET" in table[""]


def test_single_create_is_post_on_root():
    table = _routes()
    assert "POST" in table[""]


def test_bulk_create_is_post_on_bulk_path():
    table = _routes()
    assert "POST" in table["/bulk"]
    # nothing should ever be GET-able on /bulk
    assert "GET" not in table.get("/bulk", set())
