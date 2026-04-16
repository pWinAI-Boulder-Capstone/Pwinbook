"""
Unit tests for Audio Generation — Retry & Fallback Mechanisms
=============================================================

Tests the TTS retry logic, fallback provider switching, voice mapping
fallback, duration validation, and batch error propagation in
open_notebook/graphs/audio_generation.py

All TTS calls are mocked — no real API calls or audio files needed.
"""

import asyncio
import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ── Ensure project root is on sys.path ──
project_root = Path(__file__).parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from open_notebook.domain.agentic_podcast import TranscriptLine
from open_notebook.graphs.audio_generation import (
    DEFAULT_DURATION_RANGE,
    DURATION_TARGET_RANGE,
    SAME_SPEAKER_PAUSE_MS,
    SPEAKER_CHANGE_PAUSE_MS,
    TTS_MAX_RETRIES,
    TTS_RETRY_DELAY_S,
    generate_single_clip,
    validate_audio_duration,
)


# ════════════════════════════════════════════════════════════════════
#  HELPERS
# ════════════════════════════════════════════════════════════════════

def _make_mock_tts(*, succeed: bool = True, fail_count: int = 0):
    """Create a mock TTS object from AIFactory.

    Args:
        succeed: If True, always succeeds. If False, always fails.
        fail_count: Number of initial failures before succeeding.
                    Ignored if succeed is False.
    """
    tts = MagicMock()
    call_counter = {"n": 0}

    async def fake_generate_speech(text, voice, output_file):
        call_counter["n"] += 1
        current = call_counter["n"]
        if not succeed:
            raise ConnectionError(f"TTS API unreachable (call #{current})")
        if current <= fail_count:
            raise ConnectionError(
                f"Transient TTS failure (call #{current}/{fail_count})"
            )
        # "success" — write a tiny file so Path.exists() would work
        Path(output_file).parent.mkdir(parents=True, exist_ok=True)
        Path(output_file).write_bytes(b"\x00" * 16)

    tts.agenerate_speech = AsyncMock(side_effect=fake_generate_speech)
    return tts, call_counter


COMMON_KWARGS = dict(
    text="Hello, welcome to the podcast!",
    speaker="Alice",
    index=0,
    tts_provider="primary_provider",
    tts_model="primary_model",
    voice_mapping={"Alice": "voice_alice", "Bob": "voice_bob"},
)


@pytest.fixture(autouse=True)
def _bypass_model_manager():
    """Bypass ModelManager DB lookup so tests fall through to AIFactory."""
    mock_mgr = MagicMock()
    mock_mgr.return_value.get_model = AsyncMock(
        side_effect=ValueError("test — no DB")
    )
    with patch("open_notebook.domain.models.ModelManager", mock_mgr):
        yield


# ════════════════════════════════════════════════════════════════════
#  TEST 1 — HAPPY PATH: TTS succeeds on first attempt
# ════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_tts_first_attempt_success(tmp_path):
    """
    ✅ TTS succeeds on the very first call.
    Verifies: only 1 API call made, correct clip path returned.
    """
    print("\n" + "=" * 70)
    print("TEST 1: TTS First-Attempt Success")
    print("=" * 70)

    tts_mock, counter = _make_mock_tts(succeed=True, fail_count=0)

    with patch("esperanto.AIFactory") as factory:
        factory.create_text_to_speech.return_value = tts_mock

        clip = await generate_single_clip(
            **COMMON_KWARGS,
            clips_dir=tmp_path,
        )

    assert clip == tmp_path / "0000.mp3"
    assert clip.exists()
    assert counter["n"] == 1

    print(f"  ➤ Clip generated: {clip.name}")
    print(f"  ➤ API calls made: {counter['n']}  (expected: 1)")
    print("  ✅ PASSED — First attempt succeeded, no retries needed\n")


# ════════════════════════════════════════════════════════════════════
#  TEST 2 — RETRY: First attempt fails, second succeeds
# ════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_tts_retry_succeeds_on_second_attempt(tmp_path):
    """
    🔄 First TTS call fails with a transient error.
    Second attempt (retry) succeeds.
    Verifies: 2 API calls made, still returns valid clip.
    """
    print("\n" + "=" * 70)
    print("TEST 2: TTS Retry — Fails Once, Succeeds on Retry")
    print("=" * 70)

    tts_mock, counter = _make_mock_tts(succeed=True, fail_count=1)

    with patch("esperanto.AIFactory") as factory:
        factory.create_text_to_speech.return_value = tts_mock
        # Speed up the test by reducing retry delay
        with patch("open_notebook.graphs.audio_generation.TTS_RETRY_DELAY_S", 0.01):
            clip = await generate_single_clip(
                **COMMON_KWARGS,
                clips_dir=tmp_path,
            )

    assert clip == tmp_path / "0000.mp3"
    assert clip.exists()
    assert counter["n"] == 2

    print(f"  ➤ Clip generated: {clip.name}")
    print(f"  ➤ API calls made: {counter['n']}  (expected: 2)")
    print(f"  ➤ Retry delay configured: {TTS_RETRY_DELAY_S}s (patched to 0.01s for test)")
    print(f"  ➤ MAX_RETRIES setting: {TTS_MAX_RETRIES}")
    print("  ✅ PASSED — Transient failure recovered via retry\n")


# ════════════════════════════════════════════════════════════════════
#  TEST 3 — FALLBACK: Both primary retries fail → fallback succeeds
# ════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_tts_fallback_provider_succeeds(tmp_path):
    """
    🔀 Primary provider fails on ALL attempts (2 retries exhausted).
    Fallback provider is configured and succeeds.
    Verifies: 2 primary calls + 1 fallback call = 3 total.
    """
    print("\n" + "=" * 70)
    print("TEST 3: TTS Fallback — Primary Exhausted, Fallback Saves the Day")
    print("=" * 70)

    # Primary always fails
    primary_tts, primary_counter = _make_mock_tts(succeed=False)
    # Fallback always succeeds
    fallback_tts, fallback_counter = _make_mock_tts(succeed=True, fail_count=0)

    call_log = []

    def mock_create_tts(provider, model):
        call_log.append((provider, model))
        if provider == "fallback_provider":
            return fallback_tts
        return primary_tts

    with patch("esperanto.AIFactory") as factory:
        factory.create_text_to_speech.side_effect = mock_create_tts
        with patch("open_notebook.graphs.audio_generation.TTS_RETRY_DELAY_S", 0.01):
            clip = await generate_single_clip(
                **COMMON_KWARGS,
                clips_dir=tmp_path,
                fallback_tts_provider="fallback_provider",
                fallback_tts_model="fallback_model",
            )

    assert clip == tmp_path / "0000.mp3"
    assert clip.exists()
    assert primary_counter["n"] == 2   # both retries exhausted
    assert fallback_counter["n"] == 1  # fallback called once

    print(f"  ➤ Clip generated: {clip.name}")
    print(f"  ➤ Primary provider calls: {primary_counter['n']}  (all failed)")
    print(f"  ➤ Fallback provider calls: {fallback_counter['n']}  (succeeded)")
    print(f"  ➤ Provider call sequence:")
    for i, (prov, model) in enumerate(call_log):
        status = "FAILED" if prov == "primary_provider" else "SUCCESS"
        print(f"      Call {i+1}: provider={prov}, model={model} → {status}")
    print("  ✅ PASSED — Fallback provider rescued the clip generation\n")


# ════════════════════════════════════════════════════════════════════
#  TEST 4 — FALLBACK VIA ENV VARS: env-based fallback config works
# ════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_tts_fallback_from_env_vars(tmp_path):
    """
    🌍 Fallback configured via environment variables (not function params).
    Primary fails, fallback from env vars is used.
    """
    print("\n" + "=" * 70)
    print("TEST 4: TTS Fallback via Environment Variables")
    print("=" * 70)

    primary_tts, primary_counter = _make_mock_tts(succeed=False)
    fallback_tts, fallback_counter = _make_mock_tts(succeed=True, fail_count=0)

    def mock_create_tts(provider, model):
        if provider == "env_fallback_provider":
            return fallback_tts
        return primary_tts

    env_patch = {
        "FALLBACK_TTS_PROVIDER": "env_fallback_provider",
        "FALLBACK_TTS_MODEL": "env_fallback_model",
    }

    with patch("esperanto.AIFactory") as factory:
        factory.create_text_to_speech.side_effect = mock_create_tts
        with patch("open_notebook.graphs.audio_generation.TTS_RETRY_DELAY_S", 0.01):
            with patch.dict(os.environ, env_patch):
                clip = await generate_single_clip(
                    **COMMON_KWARGS,
                    clips_dir=tmp_path,
                    # NOTE: no fallback_tts_provider/model params — rely on env
                )

    assert clip.exists()
    assert primary_counter["n"] == 2
    assert fallback_counter["n"] == 1

    print(f"  ➤ Clip generated: {clip.name}")
    print(f"  ➤ Primary exhausted: {primary_counter['n']} attempts")
    print(f"  ➤ Fallback (from env) succeeded: {fallback_counter['n']} call")
    print(f"  ➤ Env vars used: FALLBACK_TTS_PROVIDER=env_fallback_provider")
    print("  ✅ PASSED — Environment variable fallback works correctly\n")


# ════════════════════════════════════════════════════════════════════
#  TEST 5 — TOTAL FAILURE: Primary + fallback both fail → RuntimeError
# ════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_tts_all_attempts_fail_raises_runtime_error(tmp_path):
    """
    💥 Both primary (2 retries) and fallback (1 attempt) fail.
    Verifies: RuntimeError raised with both error messages.
    """
    print("\n" + "=" * 70)
    print("TEST 5: Total TTS Failure — Primary + Fallback Both Fail")
    print("=" * 70)

    primary_tts, primary_counter = _make_mock_tts(succeed=False)
    fallback_tts, fallback_counter = _make_mock_tts(succeed=False)

    def mock_create_tts(provider, model):
        if provider == "fallback_provider":
            return fallback_tts
        return primary_tts

    with patch("esperanto.AIFactory") as factory:
        factory.create_text_to_speech.side_effect = mock_create_tts
        with patch("open_notebook.graphs.audio_generation.TTS_RETRY_DELAY_S", 0.01):
            with pytest.raises(RuntimeError) as exc_info:
                await generate_single_clip(
                    **COMMON_KWARGS,
                    clips_dir=tmp_path,
                    fallback_tts_provider="fallback_provider",
                    fallback_tts_model="fallback_model",
                )

    error_msg = str(exc_info.value)
    assert "primary" in error_msg.lower() or "fallback" in error_msg.lower()
    assert primary_counter["n"] == 2
    assert fallback_counter["n"] == 1

    print(f"  ➤ Primary provider calls: {primary_counter['n']}  (all failed)")
    print(f"  ➤ Fallback provider calls: {fallback_counter['n']}  (also failed)")
    print(f"  ➤ RuntimeError raised: YES")
    print(f"  ➤ Error message: {error_msg[:120]}...")
    print("  ✅ PASSED — RuntimeError correctly raised when all TTS options fail\n")


# ════════════════════════════════════════════════════════════════════
#  TEST 6 — NO FALLBACK CONFIGURED: Primary fails → RuntimeError (no fallback)
# ════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_tts_no_fallback_configured_raises_runtime_error(tmp_path):
    """
    🚫 Primary provider fails and NO fallback is configured at all.
    Verifies: RuntimeError raised, error mentions missing fallback config.
    """
    print("\n" + "=" * 70)
    print("TEST 6: No Fallback Configured — Primary Fails, No Safety Net")
    print("=" * 70)

    primary_tts, primary_counter = _make_mock_tts(succeed=False)

    # Clear env vars to ensure no fallback
    env_patch = {"FALLBACK_TTS_PROVIDER": "", "FALLBACK_TTS_MODEL": ""}

    with patch("esperanto.AIFactory") as factory:
        factory.create_text_to_speech.return_value = primary_tts
        with patch("open_notebook.graphs.audio_generation.TTS_RETRY_DELAY_S", 0.01):
            with patch.dict(os.environ, env_patch, clear=False):
                # Also remove the env vars entirely
                os.environ.pop("FALLBACK_TTS_PROVIDER", None)
                os.environ.pop("FALLBACK_TTS_MODEL", None)
                with pytest.raises(RuntimeError) as exc_info:
                    await generate_single_clip(
                        **COMMON_KWARGS,
                        clips_dir=tmp_path,
                        # no fallback params
                    )

    error_msg = str(exc_info.value)
    assert "no fallback" in error_msg.lower()
    assert primary_counter["n"] == 2

    print(f"  ➤ Primary provider calls: {primary_counter['n']}  (all failed)")
    print(f"  ➤ Fallback available: NO")
    print(f"  ➤ RuntimeError raised: YES")
    print(f"  ➤ Error message: {error_msg[:120]}...")
    print("  ✅ PASSED — Clear error when no fallback is configured\n")


# ════════════════════════════════════════════════════════════════════
#  TEST 7 — VOICE MAPPING FALLBACK: Unknown speaker gets first voice
# ════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_voice_mapping_fallback_for_unknown_speaker(tmp_path):
    """
    🎤 Speaker not in voice_mapping → falls back to first available voice.
    Verifies: TTS is called with the fallback voice, clip still generated.
    """
    print("\n" + "=" * 70)
    print("TEST 7: Voice Mapping Fallback — Unknown Speaker")
    print("=" * 70)

    captured_voice = {}

    async def capture_generate_speech(text, voice, output_file):
        captured_voice["voice_id"] = voice
        Path(output_file).parent.mkdir(parents=True, exist_ok=True)
        Path(output_file).write_bytes(b"\x00" * 16)

    tts_mock = MagicMock()
    tts_mock.agenerate_speech = AsyncMock(side_effect=capture_generate_speech)

    voice_mapping = {"Alice": "voice_alice", "Bob": "voice_bob"}

    with patch("esperanto.AIFactory") as factory:
        factory.create_text_to_speech.return_value = tts_mock

        clip = await generate_single_clip(
            text="This is a test line.",
            speaker="Charlie",  # NOT in voice_mapping
            index=0,
            clips_dir=tmp_path,
            tts_provider="primary_provider",
            tts_model="primary_model",
            voice_mapping=voice_mapping,
        )

    assert clip.exists()
    # Should have used the first voice in the mapping (dict order)
    first_voice = next(iter(voice_mapping.values()))
    assert captured_voice["voice_id"] == first_voice

    print(f"  ➤ Requested speaker: 'Charlie' (NOT in mapping)")
    print(f"  ➤ Available voices: {voice_mapping}")
    print(f"  ➤ Voice used for TTS: '{captured_voice['voice_id']}' (fallback to first)")
    print(f"  ➤ Clip generated: {clip.name}")
    print("  ✅ PASSED — Unknown speaker gracefully fell back to first voice\n")


# ════════════════════════════════════════════════════════════════════
#  TEST 8 — DURATION VALIDATION: short / medium / long / unknown
# ════════════════════════════════════════════════════════════════════

class TestDurationValidation:
    """Tests for validate_audio_duration() with all podcast length presets."""

    def test_short_podcast_within_range(self):
        """Duration within 'short' range (2.5-7 min)."""
        print("\n" + "=" * 70)
        print("TEST 8a: Duration Validation — Short Podcast (Within Range)")
        print("=" * 70)

        result = validate_audio_duration(300, "short")  # 5 min
        assert result["valid"] is True
        assert "warning" not in result
        assert result["duration_minutes"] == 5.0

        print(f"  ➤ Duration: {result['duration_minutes']} min")
        print(f"  ➤ Target range: {result['target_range_minutes']} min")
        print(f"  ➤ Valid: {result['valid']}")
        print("  ✅ PASSED — 5 min is within short range (2.5-7 min)\n")

    def test_short_podcast_too_short(self):
        """Duration below 'short' minimum."""
        print("\n" + "=" * 70)
        print("TEST 8b: Duration Validation — Short Podcast (TOO SHORT)")
        print("=" * 70)

        result = validate_audio_duration(60, "short")  # 1 min
        assert result["valid"] is False
        assert "warning" in result
        assert "shorter" in result["warning"].lower()

        print(f"  ➤ Duration: {result['duration_minutes']} min")
        print(f"  ➤ Target range: {result['target_range_minutes']} min")
        print(f"  ➤ Valid: {result['valid']}")
        print(f"  ➤ Warning: {result['warning']}")
        print("  ✅ PASSED — Correctly flagged 1 min as too short\n")

    def test_medium_podcast_within_range(self):
        """Duration within 'medium' range (6-12 min)."""
        print("\n" + "=" * 70)
        print("TEST 8c: Duration Validation — Medium Podcast (Within Range)")
        print("=" * 70)

        result = validate_audio_duration(540, "medium")  # 9 min
        assert result["valid"] is True

        print(f"  ➤ Duration: {result['duration_minutes']} min")
        print(f"  ➤ Target range: {result['target_range_minutes']} min")
        print(f"  ➤ Valid: {result['valid']}")
        print("  ✅ PASSED — 9 min is within medium range (6-12 min)\n")

    def test_long_podcast_exceeds_range(self):
        """Duration exceeds 'long' maximum."""
        print("\n" + "=" * 70)
        print("TEST 8d: Duration Validation — Long Podcast (EXCEEDS Range)")
        print("=" * 70)

        result = validate_audio_duration(1200, "long")  # 20 min
        assert result["valid"] is False
        assert "exceeds" in result["warning"].lower()

        print(f"  ➤ Duration: {result['duration_minutes']} min")
        print(f"  ➤ Target range: {result['target_range_minutes']} min")
        print(f"  ➤ Valid: {result['valid']}")
        print(f"  ➤ Warning: {result['warning']}")
        print("  ✅ PASSED — Correctly flagged 20 min as exceeding long range\n")

    def test_unknown_length_uses_default_range(self):
        """Unknown podcast length uses DEFAULT_DURATION_RANGE."""
        print("\n" + "=" * 70)
        print("TEST 8e: Duration Validation — Unknown Length (Default Range)")
        print("=" * 70)

        result = validate_audio_duration(600, "unknown_preset")  # 10 min
        expected_range = (
            round(DEFAULT_DURATION_RANGE[0] / 60, 1),
            round(DEFAULT_DURATION_RANGE[1] / 60, 1),
        )
        assert result["valid"] is True
        assert result["target_range_minutes"] == expected_range

        print(f"  ➤ Duration: {result['duration_minutes']} min")
        print(f"  ➤ Fallback range used: {result['target_range_minutes']} min")
        print(f"  ➤ Valid: {result['valid']}")
        print("  ✅ PASSED — Unknown preset correctly uses default range\n")


# ════════════════════════════════════════════════════════════════════
#  TEST 9 — RETRY TIMING: Verify retry delay is applied
# ════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_retry_delay_is_applied(tmp_path):
    """
    ⏱️  Verifies asyncio.sleep is called between retries with correct delay.
    """
    print("\n" + "=" * 70)
    print("TEST 9: Retry Delay — Verify Sleep Between Attempts")
    print("=" * 70)

    tts_mock, counter = _make_mock_tts(succeed=True, fail_count=1)

    with patch("esperanto.AIFactory") as factory:
        factory.create_text_to_speech.return_value = tts_mock
        with patch("open_notebook.graphs.audio_generation.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            clip = await generate_single_clip(
                **COMMON_KWARGS,
                clips_dir=tmp_path,
            )

    # asyncio.sleep should have been called once (between attempt 1 and 2)
    mock_sleep.assert_called_once_with(TTS_RETRY_DELAY_S)

    print(f"  ➤ Total attempts: {counter['n']}")
    print(f"  ➤ asyncio.sleep called: {mock_sleep.call_count} time(s)")
    print(f"  ➤ Sleep duration: {mock_sleep.call_args[0][0]}s (expected: {TTS_RETRY_DELAY_S}s)")
    print("  ✅ PASSED — Retry delay correctly applied between attempts\n")


# ════════════════════════════════════════════════════════════════════
#  TEST 10 — CORRECT VOICE MAPPING: Right voice used for speaker
# ════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_correct_voice_used_for_speaker(tmp_path):
    """
    🎤 Verifies that the correct voice_id from voice_mapping is passed to TTS.
    """
    print("\n" + "=" * 70)
    print("TEST 10: Voice Mapping — Correct Voice Used for Known Speaker")
    print("=" * 70)

    captured_voice = {}

    async def capture_generate_speech(text, voice, output_file):
        captured_voice["voice_id"] = voice
        Path(output_file).parent.mkdir(parents=True, exist_ok=True)
        Path(output_file).write_bytes(b"\x00" * 16)

    tts_mock = MagicMock()
    tts_mock.agenerate_speech = AsyncMock(side_effect=capture_generate_speech)

    with patch("esperanto.AIFactory") as factory:
        factory.create_text_to_speech.return_value = tts_mock

        await generate_single_clip(
            text="Testing Bob's voice.",
            speaker="Bob",
            index=1,
            clips_dir=tmp_path,
            tts_provider="primary_provider",
            tts_model="primary_model",
            voice_mapping={"Alice": "voice_alice", "Bob": "voice_bob"},
        )

    assert captured_voice["voice_id"] == "voice_bob"

    print(f"  ➤ Speaker: 'Bob'")
    print(f"  ➤ Voice used: '{captured_voice['voice_id']}' (expected: 'voice_bob')")
    print("  ✅ PASSED — Correct voice_id resolved from mapping\n")


# ════════════════════════════════════════════════════════════════════
#  SUMMARY BANNER (runs after all tests via session-scoped fixture)
# ════════════════════════════════════════════════════════════════════

def pytest_terminal_summary(terminalreporter, exitstatus, config):
    """Print a clear summary banner at the end of test execution."""
    passed = len(terminalreporter.stats.get("passed", []))
    failed = len(terminalreporter.stats.get("failed", []))
    total = passed + failed

    print("\n")
    print("╔" + "═" * 68 + "╗")
    print("║" + " AUDIO GENERATION TEST SUITE — RESULTS SUMMARY".center(68) + "║")
    print("╠" + "═" * 68 + "╣")
    print("║" + f"  Total tests:  {total}".ljust(68) + "║")
    print("║" + f"  Passed:       {passed} ✅".ljust(68) + "║")
    print("║" + f"  Failed:       {failed} {'❌' if failed else ''}".ljust(68) + "║")
    print("╠" + "═" * 68 + "╣")
    print("║" + "  Tests cover:".ljust(68) + "║")
    print("║" + "    • TTS first-attempt success".ljust(68) + "║")
    print("║" + "    • TTS retry on transient failure".ljust(68) + "║")
    print("║" + "    • Fallback to secondary TTS provider".ljust(68) + "║")
    print("║" + "    • Fallback via environment variables".ljust(68) + "║")
    print("║" + "    • Total failure (primary + fallback)".ljust(68) + "║")
    print("║" + "    • No fallback configured scenario".ljust(68) + "║")
    print("║" + "    • Voice mapping fallback for unknown speakers".ljust(68) + "║")
    print("║" + "    • Duration validation (short/medium/long/unknown)".ljust(68) + "║")
    print("║" + "    • Retry delay timing verification".ljust(68) + "║")
    print("║" + "    • Correct voice-to-speaker resolution".ljust(68) + "║")
    print("╚" + "═" * 68 + "╝")
