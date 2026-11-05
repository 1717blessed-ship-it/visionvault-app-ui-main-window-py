import tkinter as tk


from app.ai.tag_review import normalize_tag, review_suggestions, tag_group
from app.database.database import ImageDatabase
from app.ui.gallery import Gallery


def test_normalize_tag_ignores_case_accents_and_extra_spaces():
    assert normalize_tag("  Dragón   Ball ") == "dragon ball"


def test_review_reuses_existing_equivalent_and_removes_repeated_proposals():
    rows = review_suggestions(
        ["dragon ball", "Dragón Ball", "Rojo"],
        ["Dragón Ball", "Goku"],
    )

    assert [row["tag"] for row in rows] == ["Dragón Ball", "Rojo"]
    assert rows[0]["existing"] is True
    assert rows[1]["group"] == "Color"


def test_tag_group_keeps_general_terms_together():
    assert tag_group("Selección Argentina") == "Tema y busqueda"


def test_rename_tag_merges_associations_when_destination_exists(tmp_path):
    database = ImageDatabase(tmp_path / "library.db")
    database.connection.execute(
        "INSERT INTO images(path, name, extension, size, modified) VALUES (?, ?, ?, ?, ?)",
        ("one.png", "one.png", ".png", 0, 1),
    )
    database.connection.execute(
        "INSERT INTO images(path, name, extension, size, modified) VALUES (?, ?, ?, ?, ?)",
        ("two.png", "two.png", ".png", 0, 1),
    )
    database.connection.commit()
    database.add_tag("one.png", "Anime")
    database.add_tag("two.png", "Animé")

    assert database.rename_tag("Animé", "Anime") == "Anime"
    assert database.tag_counts() == [("Anime", 2)]
    assert database.remove_tag_from_images(["one.png"], "Anime") == 1
    assert database.tag_counts() == [("Anime", 1)]


def test_ai_review_images_returns_only_untagged_current_analysis(tmp_path):
    database = ImageDatabase(tmp_path / "review.db")
    database.connection.execute(
        "INSERT INTO images(path, name, extension, size, modified) VALUES (?, ?, ?, ?, ?)",
        ("review.png", "review.png", ".png", 0, 7),
    )
    database.connection.commit()
    database.save_ai_result("review.png", "Gemini", "model:structured-v3", 7, {"suggestions": ["Anime"]})

    items = database.ai_review_images("Gemini", "model:structured-v3")

    assert len(items) == 1
    assert items[0]["path"] == "review.png"
    assert items[0]["ai_result"]["suggestions"] == ["Anime"]


def test_rename_category_merges_category_assignments(tmp_path):
    database = ImageDatabase(tmp_path / "categories.db")
    database.connection.execute(
        "INSERT INTO images(path, name, extension, size, modified, category) VALUES (?, ?, ?, ?, ?, ?)",
        ("one.png", "one.png", ".png", 0, 1, "Anime"),
    )
    database.connection.execute(
        "INSERT INTO images(path, name, extension, size, modified, category) VALUES (?, ?, ?, ?, ?, ?)",
        ("two.png", "two.png", ".png", 0, 1, "Animacion"),
    )
    database.connection.commit()

    assert database.rename_category("Animacion", "Anime") == 1
    assert database.category_counts() == [("Anime", 2)]


def test_visual_search_images_reuses_cache_for_same_database(tmp_path):
    database = ImageDatabase(tmp_path / "visual-cache.db")
    database.connection.execute(
        "INSERT INTO images(path, name, extension, size, modified) VALUES (?, ?, ?, ?, ?)",
        ("demo.png", "demo.png", ".png", 10, 1),
    )
    database.connection.commit()

    first = database.visual_search_images()
    second = database.visual_search_images()

    assert first == second
    assert database._visual_search_cache is not None
    assert database._visual_search_cache[1] == first


def test_random_search_reuses_cache_for_same_database(tmp_path):
    database = ImageDatabase(tmp_path / "random-cache.db")
    database.connection.execute(
        "INSERT INTO images(path, name, extension, size, modified) VALUES (?, ?, ?, ?, ?)",
        ("demo.png", "demo.png", ".png", 10, 1),
    )
    database.connection.commit()

    first = database.search(random_order=True, limit=10)
    second = database.search(random_order=True, limit=10)

    assert len(first) == len(second) == 1
    assert database._search_cache
    assert second == first


def test_library_search_reuses_cache_for_same_query_and_filters(tmp_path):
    database = ImageDatabase(tmp_path / "query-cache.db")
    database.connection.execute(
        "INSERT INTO images(path, name, extension, size, modified) VALUES (?, ?, ?, ?, ?)",
        ("demo.png", "demo.png", ".png", 10, 1),
    )
    database.connection.commit()

    first = database.search("demo", limit=10)
    second = database.search("demo", limit=10)

    assert first == second
    assert database._search_cache


def test_images_by_paths_reuses_cache_for_same_paths(tmp_path):
    database = ImageDatabase(tmp_path / "paths-cache.db")
    database.connection.execute(
        "INSERT INTO images(path, name, extension, size, modified) VALUES (?, ?, ?, ?, ?)",
        ("demo.png", "demo.png", ".png", 10, 1),
    )
    database.connection.commit()

    first = database.images_by_paths(["demo.png"])
    second = database.images_by_paths(["demo.png"])

    assert first == second
    assert database._images_by_paths_cache


def test_gallery_skips_re_render_for_same_image_set():
    root = tk.Tk()
    root.withdraw()
    try:
        gallery = Gallery(
            root,
            on_preview=lambda *_args, **_kwargs: None,
            on_add_tag=lambda *_args, **_kwargs: None,
            on_remove_tag=lambda *_args, **_kwargs: None,
            on_capacity_change=lambda: None,
            on_toggle_selection=lambda *_args, **_kwargs: None,
            is_selected=lambda *_args, **_kwargs: False,
        )
        photos = [{"path": "a.png", "modified": 1.0, "tags": "", "caption": ""}]

        gallery.show_images(photos)
        before = gallery.render_generation
        gallery.show_images(photos)

        assert gallery.render_generation == before
    finally:
        root.destroy()


def test_count_reuses_cache_for_same_query_and_filters(tmp_path):
    database = ImageDatabase(tmp_path / "count-cache.db")
    database.connection.execute(
        "INSERT INTO images(path, name, extension, size, modified, caption) VALUES (?, ?, ?, ?, ?, ?)",
        ("demo.png", "demo.png", ".png", 10, 1, "demo"),
    )
    database.connection.commit()

    first = database.count("demo")
    second = database.count("demo")

    assert first == second == 1
    assert database._count_cache
