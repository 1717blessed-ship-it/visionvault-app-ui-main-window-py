from pathlib import Path

import pytest

from scripts.validate_sticker_visuals import checker, prepare_bank, synthetic, run


def test_visual_bank_has_36_unique_cases_and_real_provenance(tmp_path):
    cases = prepare_bank(tmp_path)
    assert len(cases) == len({c['id'] for c in cases}) == 36
    assert len({c['category'] for c in cases}) == 18
    real = [c for c in cases if c['provenance']=='real_user_reference']
    assert {c['id'] for c in real} == {'04-A', '04-B', '05-B'}
    assert all(Path(c['source']).is_file() for c in cases)
    assert all(c['real_reference_required'] for c in cases if c not in real)


def test_synthetic_fixtures_are_deterministic_and_keep_intentional_holes():
    first, mask = synthetic('arte_transparente', True)
    second, other = synthetic('arte_transparente', True)
    assert first.tobytes() == second.tobytes()
    assert mask.tobytes() == other.tobytes()
    assert mask.getpixel((220,160)) == 0
    assert mask.getpixel((140,160)) == 255


def test_generated_checker_is_not_an_embedded_input_or_alpha_mask():
    board = checker((32,32), 8)
    assert board.getpixel((0,0)) != board.getpixel((8,0))
    assert board.getchannel('A').getextrema() == (255,255)


def test_existing_evidence_folder_cannot_be_overwritten(tmp_path):
    marker = tmp_path/'keep.txt'
    marker.write_text('approved evidence', encoding='utf-8')
    with pytest.raises(FileExistsError):
        run(tmp_path)
    assert marker.read_text(encoding='utf-8') == 'approved evidence'
