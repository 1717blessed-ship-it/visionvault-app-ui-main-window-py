import uuid
from pathlib import Path

from app.planchas.model import PlanchaProject
from app.planchas.sticker_mixed import StickerMixedPacker
from app.planchas.sticker_mixed_conversion import convert_sticker_mixed_projects_to_free


def _mixed_pages():
    items = PlanchaProject.from_images([
        {"path": "five.png", "visible_width": 100, "visible_height": 100, "order_id": 1, "order_quantity": 2, "order_size_cm": 5},
        {"path": "wide.png", "visible_width": 200, "visible_height": 100, "order_id": 1, "order_quantity": 3, "order_size_cm": 8},
        {"path": "ten.png", "visible_width": 100, "visible_height": 100, "order_id": 1, "order_quantity": 2, "order_size_cm": 10},
        {"path": "fifteen.png", "visible_width": 100, "visible_height": 100, "order_id": 1, "order_quantity": 1, "order_size_cm": 15},
    ]).items
    return StickerMixedPacker().pack(items).projects


def _snapshot(projects):
    return [[(
        item.item_id, item.group_id, item.copy_number, item.nominal_size_cm,
        item.width_cm, item.height_cm, item.layout_width_cm, item.layout_height_cm,
        item.x_cm, item.y_cm, item.rotation,
    ) for item in project.items] for project in projects]


def test_mixed_to_free_preserves_all_page_geometry_and_identity():
    pages = _mixed_pages()
    before = _snapshot(pages)

    converted = convert_sticker_mixed_projects_to_free(pages)

    assert [id(project) for project in converted] == [id(project) for project in pages]
    assert _snapshot(converted) == before
    assert all(page.project_type == "sticker_free" for page in converted)
    assert all(page.manual_from_mixed for page in converted)


def test_mixed_to_free_allows_only_position_changes_after_conversion():
    pages = convert_sticker_mixed_projects_to_free(_mixed_pages())
    item = pages[0].items[0]
    before = _snapshot(pages)
    item.x_cm += 0.5
    item.y_cm -= 0.25
    after = _snapshot(pages)

    assert after[0][0][8:10] != before[0][0][8:10]
    assert after[0][0][:8] + after[0][0][10:] == before[0][0][:8] + before[0][0][10:]


def test_legacy_project_remains_legacy_when_loaded_without_project_type(tmp_path):
    folder = tmp_path
    folder.mkdir(exist_ok=True)
    path = folder / f"legacy_{uuid.uuid4().hex}.json"
    try:
        path.write_text('{"items": [], "workspace_format": "a4"}', encoding="utf-8")
        project = PlanchaProject.load(path)
        assert project.project_type == "legacy"
        assert not project.manual_from_mixed
    finally:
        path.unlink(missing_ok=True)
