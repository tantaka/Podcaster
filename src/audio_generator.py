"""
音声生成モジュール: Gemini TTS マルチスピーカー (1回のAPI呼び出しで全台本を合成)
  Primary   : gemini-2.5-flash-preview-tts  (マルチスピーカー)
  Fallback1 : gemini-2.5-pro-preview-tts    (マルチスピーカー)
  Fallback2 : per-segment + レート制限遵守 (3 req/min → 22秒間隔)
"""
import base64
import logging
import time
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
from src.retry_utils import retry_with_backoff, NoRetryError

logger = logging.getLogger(__name__)

# 無料枠: 3 req/min → 最低 22 秒間隔を確保
TTS_FREE_TIER_INTERVAL_SEC = 22

VOICE_MAP = {
    "primary": {"host_male": TTS_VOICE_MALE_PRIMARY, "host_female": TTS_VOICE_FEMALE_PRIMARY},
    "fallback": {"host_male": TTS_VOICE_MALE_FALLBACK, "host_female": TTS_VOICE_FEMALE_FALLBACK},
}


def _is_quota_exhausted(e: Exception) -> bool:
    """リトライしても解決しないクォータ超過か判定 (limit:0 または日次上限)"""
    s = str(e)
    return "limit: 0" in s or "GenerateRequestsPerDay" in s


def _pcm_to_mp3(pcm_data: bytes, output_path: Path, mime_type: str = "") -> Path:
    """PCM バイト列を MP3 ファイルに変換して保存"""
    from pydub import AudioSegment

    sample_rate = TTS_SAMPLE_RATE
    if "rate=" in mime_type:
        try:
            sample_rate = int(mime_type.split("rate=")[1].split(";")[0].strip())
        except (ValueError, IndexError):
            pass

    audio = AudioSegment(data=pcm_data, sample_width=2, frame_rate=sample_rate, channels=1)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    audio.export(str(output_path), format="mp3", bitrate="192k")
    return output_path


@retry_with_backoff(exceptions=(Exception,))
def _synthesize_multispeaker(dialogue: list[dict], model: str) -> tuple[bytes, str]:
    """マルチスピーカーTTSで台本全体を1回のAPI呼び出しで合成"""
    from google import genai
    from google.genai import types

    if not GOOGLE_GEMINI_API_KEY:
        raise ValueError("GOOGLE_GEMINI_API_KEY が設定されていません")

    # 台本をマルチスピーカー形式に変換 (Speaker1=男性, Speaker2=女性)
    lines = []
    for line in dialogue:
        label = "Speaker1" if line["speaker"] == "host_male" else "Speaker2"
        lines.append(f"{label}: {line['text']}")
    script_text = "\n".join(lines)
    logger.info(f"[TTS] {model} マルチスピーカー合成開始 ({len(script_text)} 文字)")

    client = genai.Client(api_key=GOOGLE_GEMINI_API_KEY)
    try:
        response = client.models.generate_content(
            model=model,
            contents=script_text,
            config=types.GenerateContentConfig(
                response_modalities=["AUDIO"],
                speech_config=types.SpeechConfig(
                    multi_speaker_voice_config=types.MultiSpeakerVoiceConfig(
                        speaker_voice_configs=[
                            types.SpeakerVoiceConfig(
                                speaker="Speaker1",
                                voice_config=types.VoiceConfig(
                                    prebuilt_voice_config=types.PrebuiltVoiceConfig(
                                        voice_name=TTS_VOICE_MALE_PRIMARY
                                    )
                                ),
                            ),
                            types.SpeakerVoiceConfig(
                                speaker="Speaker2",
                                voice_config=types.VoiceConfig(
                                    prebuilt_voice_config=types.PrebuiltVoiceConfig(
                                        voice_name=TTS_VOICE_FEMALE_PRIMARY
                                    )
                                ),
                            ),
                        ]
                    )
                ),
            ),
        )
    except Exception as e:
        if _is_quota_exhausted(e):
            raise NoRetryError(f"{model} クォータ上限") from e
        raise

    part = response.candidates[0].content.parts[0]
    raw = part.inline_data.data
    if isinstance(raw, str):
        raw = base64.b64decode(raw)
    return raw, part.inline_data.mime_type or ""


@retry_with_backoff(exceptions=(Exception,))
def _synthesize_single(text: str, voice_name: str, model: str) -> tuple[bytes, str]:
    """シングルスピーカーTTS (per-segment fallback 用)"""
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=GOOGLE_GEMINI_API_KEY)
    try:
        response = client.models.generate_content(
            model=model,
            contents=text,
            config=types.GenerateContentConfig(
                response_modalities=["AUDIO"],
                speech_config=types.SpeechConfig(
                    voice_config=types.VoiceConfig(
                        prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice_name)
                    )
                ),
            ),
        )
    except Exception as e:
        if _is_quota_exhausted(e):
            raise NoRetryError(f"{model} クォータ上限") from e
        raise

    part = response.candidates[0].content.parts[0]
    raw = part.inline_data.data
    if isinstance(raw, str):
        raw = base64.b64decode(raw)
    return raw, part.inline_data.mime_type or ""


def generate_podcast_audio(dialogue: list[dict], output_path: Path) -> Path:
    """
    台本全体を音声合成して MP3 を生成。
    Primary   : マルチスピーカーTTS / Flash (1回のAPI呼び出し)
    Fallback1 : マルチスピーカーTTS / Pro
    Fallback2 : セグメント別TTS / Flash (22秒間隔でレート制限を遵守)
    Fallback3 : セグメント別TTS / Pro
    """
    logger.info("=== 音声生成開始 ===")

    # Primary: マルチスピーカー (Flash TTS)
    try:
        pcm, mime = _synthesize_multispeaker(dialogue, TTS_MODEL_PRIMARY)
        _pcm_to_mp3(pcm, output_path, mime)
        duration = len(__import__('pydub').AudioSegment.from_mp3(str(output_path))) / 1000
        logger.info(f"[TTS] マルチスピーカー生成完了: {output_path.name} ({duration:.1f}秒)")
        return output_path
    except NoRetryError:
        logger.warning(f"[TTS] {TTS_MODEL_PRIMARY} クォータ上限 → {TTS_MODEL_FALLBACK} を試みます")
    except Exception as e:
        logger.warning(f"[TTS] {TTS_MODEL_PRIMARY} 失敗: {e} → {TTS_MODEL_FALLBACK} を試みます")

    # Fallback1: マルチスピーカー (Pro TTS)
    try:
        pcm, mime = _synthesize_multispeaker(dialogue, TTS_MODEL_FALLBACK)
        _pcm_to_mp3(pcm, output_path, mime)
        duration = len(__import__('pydub').AudioSegment.from_mp3(str(output_path))) / 1000
        logger.info(f"[TTS] {TTS_MODEL_FALLBACK} マルチスピーカー生成完了: {output_path.name} ({duration:.1f}秒)")
        return output_path
    except NoRetryError:
        logger.warning(f"[TTS] {TTS_MODEL_FALLBACK} もクォータ上限 → セグメント方式に切り替えます")
    except Exception as e:
        logger.warning(f"[TTS] {TTS_MODEL_FALLBACK} 失敗: {e} → セグメント方式に切り替えます")

    # Fallback2/3: セグメント別TTS (レート制限 3 req/min を遵守)
    logger.info(f"[TTS] セグメント方式で生成 ({len(dialogue)} セグメント、{TTS_FREE_TIER_INTERVAL_SEC}秒間隔)")
    segments_dir = output_path.parent / "audio_segments"
    segments_dir.mkdir(parents=True, exist_ok=True)
    segment_paths = []
    last_call_time = 0.0

    for i, line in enumerate(dialogue):
        # レート制限: 前の呼び出しから一定時間待機
        elapsed = time.time() - last_call_time
        if last_call_time > 0 and elapsed < TTS_FREE_TIER_INTERVAL_SEC:
            wait = TTS_FREE_TIER_INTERVAL_SEC - elapsed
            logger.info(f"[TTS] レート制限待機: {wait:.1f}秒 ({i+1}/{len(dialogue)})")
            time.sleep(wait)

        speaker = line["speaker"]
        seg_path = segments_dir / f"segment_{i:03d}_{speaker}.mp3"

        # Flash → Pro の順で試行、ボイスも primary → fallback の順
        synthesized = False
        for model in (TTS_MODEL_PRIMARY, TTS_MODEL_FALLBACK):
            for voice_key in ("primary", "fallback"):
                voice = VOICE_MAP[voice_key][speaker]
                try:
                    logger.info(f"[TTS] セグメント {i+1}/{len(dialogue)}: {speaker} / {voice} ({model})")
                    pcm, mime = _synthesize_single(line["text"], voice, model)
                    _pcm_to_mp3(pcm, seg_path, mime)
                    synthesized = True
                    break
                except NoRetryError:
                    logger.warning(f"[TTS] {model}/{voice} クォータ上限 → 次の候補を試みます")
                except Exception as e:
                    logger.warning(f"[TTS] {model}/{voice} 失敗: {e}")
                    break  # 同モデルのボイス切り替えは意味がないので次モデルへ
            if synthesized:
                break

        if not synthesized:
            raise RuntimeError(f"セグメント {i+1} の合成に失敗しました (すべての TTS モデル/ボイスが利用不可)")

        segment_paths.append(seg_path)
        last_call_time = time.time()

    # セグメントを結合
    from src.audio_merger import merge_segments
    merged = merge_segments(segment_paths, output_path)
    logger.info("=== 音声生成完了 (セグメント方式) ===")
    return merged
