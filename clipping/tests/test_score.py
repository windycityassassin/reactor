"""Unit tests for the scoring math. No ffmpeg / streamlink needed."""
import math

from clipping.score import _zscore, _resample_to_grid, detect_highlights


# ---- _zscore ---------------------------------------------------------------

def test_zscore_constant_input_is_zero():
    assert _zscore([5.0, 5.0, 5.0]) == [0.0, 0.0, 0.0]


def test_zscore_empty():
    assert _zscore([]) == []


def test_zscore_distribution():
    # symmetric around 5 with std 2 => values should be -1, 0, 1
    z = _zscore([3.0, 5.0, 7.0])
    assert math.isclose(z[0], -math.sqrt(1.5), rel_tol=1e-6)
    assert math.isclose(z[1], 0.0,             abs_tol=1e-9)
    assert math.isclose(z[2],  math.sqrt(1.5), rel_tol=1e-6)


# ---- _resample_to_grid -----------------------------------------------------

def test_resample_picks_nearest():
    pairs = [(0.0, 10.0), (1.0, 20.0), (2.0, 30.0)]
    grid = [0.4, 0.6, 1.4, 2.0]
    out = _resample_to_grid(pairs, grid)
    assert out == [10.0, 20.0, 20.0, 30.0]


def test_resample_empty_curve():
    assert _resample_to_grid([], [0.0, 1.0]) == [0.0, 0.0]


# ---- detect_highlights -----------------------------------------------------

def _flat_loudness(seconds: int, db: float = -30.0) -> list[tuple[float, float]]:
    return [(float(i) + 0.5, db) for i in range(seconds)]


def test_no_highlights_when_signal_is_flat():
    audio = _flat_loudness(120)
    result = detect_highlights(audio, None, bin_seconds=2.0, min_score=1.0)
    assert result == []


def test_single_audio_peak_is_found():
    audio = _flat_loudness(120, db=-30.0)
    # Strong peak at t=60s
    audio[60] = (60.5, 0.0)
    result = detect_highlights(audio, None, bin_seconds=2.0, min_score=1.5,
                               min_gap_seconds=10.0)
    assert len(result) >= 1
    # The peak we inserted should be reflected in the top highlight
    top = max(result, key=lambda h: h.score)
    assert abs(top.timestamp - 60.0) <= 2.0
    assert top.audio_z > 1.5


def test_nms_drops_neighbors():
    audio = _flat_loudness(120, db=-30.0)
    # Two adjacent peaks; NMS should keep only one when min_gap is large
    audio[60] = (60.5, 0.0)
    audio[62] = (62.5, 0.0)
    result = detect_highlights(audio, None, bin_seconds=2.0, min_score=1.5,
                               min_gap_seconds=20.0)
    assert len(result) == 1


def test_chat_signal_adds_to_score():
    # Audio with several bumps so the std isn't artificially tiny;
    # one specific bin also gets a big chat spike, so adding chat should
    # push that bin above the audio-only score for the same bin.
    audio = _flat_loudness(120, db=-30.0)
    for i in (20, 40, 60, 80, 100):
        audio[i] = (float(i) + 0.5, -10.0)
    chat = [(float(i) + 0.5, 1) for i in range(120)]
    chat[60] = (60.5, 50)

    audio_only = detect_highlights(audio, None,
                                   bin_seconds=2.0, min_score=0.0,
                                   min_gap_seconds=0.0)
    with_chat = detect_highlights(audio, chat,
                                  bin_seconds=2.0, min_score=0.0,
                                  min_gap_seconds=0.0,
                                  alpha=0.5, beta=0.5)

    def at(highlights, t):
        return next(h for h in highlights if abs(h.timestamp - t) < 1e-3)

    assert at(with_chat, 60.5).score > at(audio_only, 60.5).score


def test_results_are_chronological():
    audio = _flat_loudness(200, db=-30.0)
    audio[40] = (40.5, -5.0)
    audio[100] = (100.5, -3.0)
    audio[160] = (160.5, -7.0)
    result = detect_highlights(audio, None, bin_seconds=2.0, min_score=1.0,
                               min_gap_seconds=10.0)
    timestamps = [h.timestamp for h in result]
    assert timestamps == sorted(timestamps)
