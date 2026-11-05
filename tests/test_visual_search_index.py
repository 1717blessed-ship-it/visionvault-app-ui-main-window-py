from __future__ import annotations

from PIL import Image, ImageDraw

from app.ai import visual_search


def _sticker(path, color=(30, 180, 55, 255), angle=0):
    image = Image.new("RGBA", (180, 140), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.polygon([(22, 18), (148, 27), (165, 82), (102, 121), (35, 98)], fill=color)
    draw.ellipse((52, 43, 83, 74), fill=(255, 255, 255, 255))
    draw.rectangle((96, 48, 137, 63), fill=(20, 20, 20, 255))
    if angle:
        image = image.rotate(angle, expand=True, resample=Image.Resampling.BICUBIC)
    image.save(path)


def test_visual_signature_persists_every_fast_search_feature(tmp_path):
    source = tmp_path / "green.png"
    _sticker(source)

    encoded = visual_search.build_visual_signature(str(source), embedding=[1.0, 0.0], text="marca verde")
    signatures, embedding, version, phash, dhash, features = visual_search.signature_and_embedding_from_text(encoded)

    assert version == visual_search.VISUAL_INDEX_VERSION
    assert len(signatures) == 12
    assert embedding == [1.0, 0.0]
    assert phash and dhash
    assert len(features["color_hist"]) == 12
    assert len(features["hu"]) == 7
    assert features["text"] == "marca verde"


def test_color_and_silhouette_index_survive_rotation(tmp_path):
    original = tmp_path / "original.png"
    rotated = tmp_path / "rotated.png"
    red = tmp_path / "red.png"
    _sticker(original)
    _sticker(rotated, angle=37)
    _sticker(red, color=(210, 35, 28, 255))

    original_features = visual_search.visual_index_features(str(original))
    rotated_features = visual_search.visual_index_features(str(rotated))
    red_features = visual_search.visual_index_features(str(red))
    same_color, same_silhouette, same_geometry, _ = visual_search._indexed_feature_similarity(
        original_features, rotated_features
    )
    different_color, _, _, _ = visual_search._indexed_feature_similarity(original_features, red_features)

    assert same_color > 0.85
    assert same_silhouette > 0.72
    assert same_geometry > 0.80
    assert different_color < 0.30


def test_precise_comparison_accepts_arbitrary_rotation(tmp_path):
    original = tmp_path / "original.png"
    rotated = tmp_path / "rotated-37.png"
    _sticker(original)
    _sticker(rotated, angle=37)

    shape, color, structure, _distance = visual_search._precise_similarity(
        str(original), str(rotated)
    )

    assert shape > 0.95
    assert color > 0.95
    assert structure > 0.94


def test_stage_one_uses_persisted_candidate_data(tmp_path, monkeypatch):
    query = tmp_path / "query.png"
    candidate = tmp_path / "candidate.png"
    _sticker(query)
    _sticker(candidate, angle=30)
    candidate_signature = visual_search.build_visual_signature(
        str(candidate), embedding=[1.0, 0.0], text=""
    )
    modified = candidate.stat().st_mtime
    candidates = [{
        "path": str(candidate),
        "name": candidate.name,
        "modified": modified,
        "visual_signature_modified": modified,
        "visual_signature": candidate_signature,
        "tags": "",
    }]

    hash_calls = 0
    real_hash = visual_search._compute_phash_dhash

    def query_hash_only(path):
        nonlocal hash_calls
        hash_calls += 1
        return real_hash(path)

    monkeypatch.setattr(visual_search, "get_resnet_embedding", lambda *_args, **_kwargs: [1.0, 0.0])
    monkeypatch.setattr(visual_search, "_compute_phash_dhash", query_hash_only)
    monkeypatch.setattr(visual_search, "_precise_similarity", lambda *_args, **_kwargs: (0.99, 0.99, 0.99, 0.0))
    details = {}

    matches = visual_search.find_similar(
        str(query), candidates, mode="identico", minimum_score=98,
        time_budget_seconds=2, details_ready=details.update,
    )

    assert matches == [(str(candidate), 99.0)]
    assert hash_calls == 1  # solo la consulta; el candidato salió del índice
    assert details[str(candidate)]["accepted_by"] == "identico"
