"""Only the automatic last partial row loses horizontal justification."""
import pytest
from collections import OrderedDict
from types import SimpleNamespace

from app.planchas.editor import PlanchaEditor, preview_geometry
from app.planchas.model import PlanchaItem, PlanchaProject


def pieces(count):
    return [PlanchaItem(path=f'{i}.png', name=str(i), width_cm=4.8, height_cm=4.8)
            for i in range(count)]


def rows(project):
    grouped = {}
    for item in project.items:
        grouped.setdefault(item.y_cm, []).append(item)
    return [sorted(row, key=lambda item: item.x_cm) for _, row in sorted(grouped.items())]


@pytest.mark.parametrize('count', [1, 2, 3, 5, 6, 7, 9, 10, 11, 19])
@pytest.mark.parametrize('gap', [0.05, 0.13])
def test_last_partial_row_uses_only_normal_gap(count, gap):
    project = PlanchaProject(pieces(count), margin_cm=0.3, gap_cm=gap)
    assert project.optimize() == []
    last = rows(project)[-1]
    assert len(last) < 4
    assert last[0].x_cm == project.margin_cm
    for previous, current in zip(last, last[1:]):
        assert current.x_cm == pytest.approx(previous.x_cm + previous.reserved_width_cm + gap, abs=.001)
    for row in rows(project)[:-1]:
        assert len(row) == 4
        assert row[-1].x_cm + row[-1].reserved_width_cm == pytest.approx(21-project.margin_cm, abs=.001)
    assert all((item.width_cm, item.height_cm) == (4.8, 4.8) for item in project.items)


def test_full_last_row_keeps_justification():
    project = PlanchaProject(pieces(8))
    project.optimize()
    for row in rows(project):
        assert len(row) == 4
        assert row[0].x_cm == project.margin_cm
        assert row[-1].x_cm + row[-1].width_cm == pytest.approx(21-project.margin_cm, abs=.001)


def test_multipage_keeps_full_page_and_compacts_last_page():
    projects = PlanchaProject.calculate_pagination(pieces(26), margin_cm=.3, gap_cm=.1)
    assert [len(p.items) for p in projects] == [20, 6]
    assert len({i.item_id for p in projects for i in p.items}) == 26
    last = rows(projects[-1])[-1]
    assert [i.x_cm for i in last] == pytest.approx([.3, 5.2])
    for project in projects:
        for item in project.items:
            assert item.x_cm >= project.margin_cm
            assert item.x_cm + item.reserved_width_cm <= 21-project.margin_cm+.001
    restored = PlanchaProject.from_dict(projects[-1].to_dict())
    assert [preview_geometry(i) for i in restored.items] == [preview_geometry(i) for i in projects[-1].items]


def test_special_last_row_respects_mixed_widths_and_order():
    items = [PlanchaItem(path=str(i), name=str(i), width_cm=w, height_cm=2, x_cm=x, y_cm=4)
             for i, (w, x) in enumerate([(3, 2), (2, 15)])]
    project = PlanchaProject(items, margin_cm=.3, gap_cm=.1, layout_mode='special')
    project.justify_rows()
    assert [i.x_cm for i in items] == [.3, 3.4]
    assert [i.name for i in sorted(items, key=lambda i: i.x_cm)] == ['0', '1']
    assert [i.y_cm for i in items] == [4, 4]


def test_locked_last_row_is_not_moved():
    item = PlanchaItem(path='locked', name='locked', width_cm=3, height_cm=3, x_cm=8, y_cm=10, locked=True)
    project = PlanchaProject([item])
    project.justify_rows()
    assert (item.x_cm, item.y_cm) == (8, 10)


def test_saved_positions_and_manual_free_preview_are_not_repacked():
    for kind in ('legacy', 'sticker_free'):
        item = PlanchaItem(path='manual.png', name='manual', width_cm=3, height_cm=2, x_cm=8, y_cm=9)
        original = PlanchaProject([item], project_type=kind)
        restored = PlanchaProject.from_dict(original.to_dict())
        editor = SimpleNamespace(project=restored)
        PlanchaEditor._prepare_current_project_for_preview(editor)
        assert restored.to_dict() == original.to_dict()


def test_rendered_export_uses_exact_preview_positions(tmp_path):
    from PIL import Image
    path = tmp_path / 'solid.png'
    Image.new('RGBA', (50, 50), 'red').save(path)
    project = PlanchaProject(pieces(6))
    project.optimize()
    for item in project.items:
        item.path = str(path)
    before = project.to_dict()
    editor = SimpleNamespace(
        project=project, current_project_index=0,
        production_sticker_cache=OrderedDict(), production_sticker_cache_pixels=0,
        prepared_production_sticker=lambda item, target, modified: None,
        _prepare_current_project_for_preview=lambda: None,
    )
    sheet = PlanchaEditor.render_sheet(editor)
    for item in rows(project)[-1]:
        geometry = preview_geometry(item)
        x = round(geometry['design_x_cm'] / 2.54 * 300)
        y = round(geometry['design_y_cm'] / 2.54 * 300)
        center = (x + round(geometry['production_width_cm'] / 2.54 * 150),
                  y + round(geometry['production_height_cm'] / 2.54 * 150))
        assert sheet.getpixel(center)[:3] == (255, 0, 0)
        assert sheet.getpixel((x-1, y+10))[3] == 0
    assert project.to_dict() == before
