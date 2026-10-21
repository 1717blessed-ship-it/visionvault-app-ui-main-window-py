from app.planchas.model import PlanchaItem, PlanchaProject


def test_setting_quantity_creates_and_optimizes_every_copy():
    """Una cantidad ingresada representa copias físicas para el optimizador."""
    project = PlanchaProject([
        PlanchaItem(
            path="/fake/path/sticker.png",
            name="Sticker",
            width_cm=5.7,
            height_cm=5.7,
        )
    ], margin_cm=0.15, gap_cm=0.05)

    project.set_quantity(project.items[0].item_id, 10)
    overflow = project.optimize()

    assert not overflow
    assert len(project.items) == 10
    assert {item.copy_number for item in project.items} == set(range(1, 11))
    assert {item.quantity for item in project.items} == {10}
    assert len({item.item_id for item in project.items}) == 10
