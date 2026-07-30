"""Dependency-free helpers for levelling and assembling generated speech."""

from array import array
from io import BytesIO
import math
import sys
import wave


def normalise_pcm16(
    pcm_data,
    target_dbfs: float = -18.0,
    max_gain_db: float = 12.0,
    peak_ceiling: float = 0.95,
) -> bytes:
    """Level signed 16-bit mono PCM while protecting against clipping."""
    raw_pcm = bytes(pcm_data or b"")
    if len(raw_pcm) < 2:
        return raw_pcm
    if len(raw_pcm) % 2:
        raw_pcm = raw_pcm[:-1]

    samples = array("h")
    samples.frombytes(raw_pcm)
    if sys.byteorder != "little":
        samples.byteswap()
    if not samples:
        return raw_pcm

    # Exclude near-silence from the loudness estimate so natural pauses do not
    # cause an otherwise healthy voice to be over-amplified.
    silence_floor = int(32767 * 0.01)
    active_samples = [
        sample
        for sample in samples
        if abs(sample) >= silence_floor
    ]
    if not active_samples:
        return raw_pcm

    rms = math.sqrt(
        sum(sample * sample for sample in active_samples)
        / len(active_samples)
    )
    if rms <= 0:
        return raw_pcm

    target_rms = 32767 * (10 ** (target_dbfs / 20))
    desired_gain = target_rms / rms
    max_gain = 10 ** (max_gain_db / 20)
    min_gain = 1 / max_gain
    desired_gain = min(max(desired_gain, min_gain), max_gain)

    peak = max(abs(sample) for sample in samples)
    if peak:
        peak_limited_gain = (32767 * peak_ceiling) / peak
        desired_gain = min(desired_gain, peak_limited_gain)

    levelled = array(
        "h",
        (
            max(-32768, min(32767, round(sample * desired_gain)))
            for sample in samples
        ),
    )
    if sys.byteorder != "little":
        levelled.byteswap()
    return levelled.tobytes()


def pcm16_to_wav(pcm_data, sample_rate: int = 24000) -> bytes | None:
    """Wrap signed 16-bit mono PCM in a playable WAV container."""
    clean_pcm = bytes(pcm_data or b"")
    if not clean_pcm:
        return None

    output = BytesIO()
    with wave.open(output, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(clean_pcm)
    return output.getvalue()


def pcm_segments_to_wav(
    segments,
    sample_rate: int = 24000,
    pause_ms: int = 320,
    normalise: bool = True,
) -> bytes | None:
    """Level and join signed 16-bit mono clips into one playable WAV file."""
    clean_segments = [
        normalise_pcm16(segment) if normalise else bytes(segment)
        for segment in segments
        if segment
    ]
    if not clean_segments:
        return None

    samples_per_pause = max(0, int(sample_rate * pause_ms / 1000))
    silence = b"\x00\x00" * samples_per_pause
    combined_pcm = silence.join(clean_segments)
    return pcm16_to_wav(combined_pcm, sample_rate)
