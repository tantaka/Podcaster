"""
音声生成モジュール: Gemini TTS (無料枠) — google-genai SDK
  Primary  : gemini-2.5-flash-preview-tts
  Fallback : gemini-2.5-pro-preview-tts  (異なるバージョン)
"""
import base64
import logging
from pathlib import Path
from src.config import (
    GOOGLE_GEMINI_API_KEY,
    TTS_MODEL_PRIMARY,
    TTS_MODEL_FALLBACK,
    TTS_VOICE_MALE_PRIMARY,
    TTS_VOICE_FEMALE_PRIMARY,
    TTS_VOICE_MALE_FALLBACK,
    TTS_VOICE_FEMALE_FALLBACK,
    TTS_SAMPLE_RATE,
)
from src.retry_utils import retry_with_backoff

logger = logging.getLogger(__name__)

VOICE_MAP = {
    "primary": {
        "host_male":   TTS_VOICE_MALE_PRIMARY,
        "host_female": TTS_VOICE_FEMALE_PRIMARY,
    },
    "fallback": {
        "host_male":   TTS_VOICE_MALE_FALLBACK,
        "host_female": TTS_VOICE_FEMALE_FALLBACK,
    },
}


def _pcm_to_mp3(pcm_data: bytes, output_path: Path, mime_type: str = "") -> Path:
    """PCM バイト列を MP3 ファイルに変換して保存"""
    from pydub import AudioSegment

    sample_rate = TTS_SAMPLE_RATE
    if "rate=" in mime_type:
        try:
            sample_rate = int(mime_type.split("rate=")[1].split(";")[0].strip())
        except (ValueError, IndexError):
            pass

    audio = AudioSegment(
        data=pcm_data,
        sample_width=2,   # 16-bit PCM = 2 bytes/sample
        frame_rate=sample_rate,
        channels=1,       # mono
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    audio.export(str(output_path), format="mp3", bitrate="192k")
    return output_path


@retry_with_backoff(exceptions=(Exception,))
def _synthesize(text: str, voice_name: str, model: str) -> tuple[bytes, str]:
    """Gemini TTS で音声合成。(PCMバイト列, mime_type) を返す。"""
    from google import genai
    from google.genai import types

    if not GOOGLE_GEMINI_API_KEY:
        raise ValueError("GOOGLE_GEMINI_API_KEY が設定されていません")

    logger.info(f"[TTS] {model} / {voice_name}: {text[:30]!r}...")
    client = genai.Client(api_key=GOOGLE_GEMINI_API_KEY)
    response = client.models.generate_content(
        model=model,
        contents=text,
        config=types.GenerateContentConfig(
            response_modalities=["AUDIO"],
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(
                        voice_name=voice_name
                    )
                )
            ),
        ),
    )

    part = response.candidates[0].content.parts[0]
    raw = part.inline_data.data
    # SDK バージョンによって bytes / base64文字列 どちらの場合もある
    if isinstance(raw, str):
        raw = base64.b64decode(raw)
    mime_type = part.inline_data.mime_type or ""
    return raw, mime_type


def synthesize_segment(text: str, speaker: str, output_path: Path) -> Path:
    """
    1つの台詞を音声合成して MP3 ファイルに保存。
    Primary 失敗 → Fallback ボイス → Fallback モデル の順で試みる。
    """
    # Primary: Flash モデル + Primary ボイス
    try:
        pcm, mime = _synthesize(text, VOICE_MAP["primary"][speaker], TTS_MODEL_PRIMARY)
        _pcm_to_mp3(pcm, output_path, mime)
        logger.info(f"[TTS] Primary で生成: {output_path.name}")
        return output_path
    except Exception as e:
        logger.warning(f"[TTS] Primary 失敗: {e} → Fallback ボイスで再試行")

    # Fallback1: Flash モデル + Fallback ボイス
    try:
        pcm, mime = _synthesize(text, VOICE_MAP["fallback"][speaker], TTS_MODEL_PRIMARY)
        _pcm_to_mp3(pcm, output_path, mime)
        logger.info(f"[TTS] Fallback ボイスで生成: {output_path.name}")
        return output_path
    except Exception as e:
        logger.warning(f"[TTS] Fallback ボイスも失敗: {e} → Pro モデルで再試行")

    # Fallback2: Pro モデル (異なるバージョンの API)
    try:
        pcm, mime = _synthesize(text, VOICE_MAP["primary"][speaker], TTS_MODEL_FALLBACK)
        _pcm_to_mp3(pcm, output_path, mime)
        logger.info(f"[TTS] Pro モデルで生成: {output_path.name}")
        return output_path
    except Exception as e:
        logger.error(f"[TTS] すべての TTS 試行が失敗: {e}")
        raise RuntimeError(f"音声合成に失敗しました: {text[:30]!r}") from e


def generate_all_segments(dialogue: list[dict], segments_dir: Path) -> list[Path]:
    """台本の全台詞を音声合成してセグメントファイルのリストを返す"""
    logger.info(f"=== 音声生成開始: {len(dialogue)} セグメント ===")
    segments_dir.mkdir(parents=True, exist_ok=True)
    segment_paths = []

    for i, line in enumerate(dialogue):
        speaker = line["speaker"]
        text = line["text"]
        output_path = segments_dir / f"segment_{i:03d}_{speaker}.mp3"
        logger.info(f"[TTS] セグメント {i+1}/{len(dialogue)}: {speaker}")
        path = synthesize_segment(text, speaker, output_path)
        segment_paths.append(path)

    logger.info(f"=== 音声生成完了: {len(segment_paths)} セグメント ===")
    return segment_paths
