"""Small dependency-free helpers for assembling generated speech."""

from io import BytesIO
import wave


def pcm_segments_to_wav(
    segments,
    sample_rate: int = 24000,
    pause_ms: int = 320,
) -> bytes | None:
    """Join signed 16-bit mono PCM clips and return one playable WAV file."""
    clean_segments = [
        bytes(segment)
        for segment in segments
        if segment
    ]
    if not clean_segments:
        return None

    samples_per_pause = max(0, int(sample_rate * pause_ms / 1000))
    silence = b"\x00\x00" * samples_per_pause
    combined_pcm = silence.join(clean_segments)

    output = BytesIO()
    with wave.open(output, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(combined_pcm)
    return output.getvalue()
