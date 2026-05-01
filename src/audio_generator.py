"""
音声生成モジュール: Google Cloud TTS Neural2 (Primary) → WaveNet (Fallback)
"""
import json
import logging
from pathlib import Path
from src.config import (
    GOOGLE_TTS_CREDENTIALS_JSON,
    TTS_VOICE_MALE_NEURAL2,
    TTS_VOICE_FEMALE_NEURAL2,
    TTS_VOICE_MALE_WAVENET,
    TTS_VOICE_FEMALE_WAVENET,
    TTS_LANGUAGE_CODE,
)
from src.retry_utils import retry_with_backoff

logger = logging.getLogger(__name__)

# スピーカー別ボイスマッピング
VOICE_MAP = {
    "neural2": {
        "host_male": TTS_VOICE_MALE_NEURAL2,
        "host_female": TTS_VOICE_FEMALE_NEURAL2,
    },
    "wavenet": {
        "host_male": TTS_VOICE_MALE_WAVENET,
        "host_female": TTS_VOICE_FEMALE_WAVENET,
    },
}


def _get_tts_client():
    """Google Cloud TTS クライアントを取得 (サービスアカウント認証)"""
    from google.cloud import texttospeech
    from google.oauth2 import service_account

    if not GOOGLE_TTS_CREDENTIALS_JSON:
        raise ValueError("GOOGLE_TTS_CREDENTIALS が設定されていません")

    credentials_info = json.loads(GOOGLE_TTS_CREDENTIALS_JSON)
    credentials = service_account.Credentials.from_service_account_info(
        credentials_info,
        scopes=["https://www.googleapis.com/auth/cloud-platform"],
    )
    return texttospeech.TextToSpeechClient(credentials=credentials)


@retry_with_backoff(exceptions=(Exception,))
def _synthesize(text: str, speaker: str, voice_type: str) -> bytes:
    """指定したボイスタイプで音声合成"""
    from google.cloud import texttospeech

    voice_name = VOICE_MAP[voice_type][speaker]
    logger.info(f"[TTS] {voice_type}/{voice_name}: {text[:30]!r}...")

    client = _get_tts_client()
    synthesis_input = texttospeech.SynthesisInput(text=text)
    voice = texttospeech.VoiceSelectionParams(
        language_code=TTS_LANGUAGE_CODE,
        name=voice_name,
    )
    audio_config = texttospeech.AudioConfig(
        audio_encoding=texttospeech.AudioEncoding.MP3,
        speaking_rate=0.95,
        pitch=0.0,
    )

    response = client.synthesize_speech(
        input=synthesis_input,
        voice=voice,
        audio_config=audio_config,
    )
    return response.audio_content


def synthesize_segment(text: str, speaker: str, output_path: Path) -> Path:
    """
    1つの台詞を音声合成してファイルに保存。
    Neural2 失敗時は WaveNet にフォールバック。
    """
    # Primary: Neural2
    try:
        audio_data = _synthesize(text, speaker, "neural2")
        output_path.write_bytes(audio_data)
        logger.info(f"[TTS] Neural2 で生成: {output_path.name}")
        return output_path
    except Exception as e:
        logger.warning(f"[TTS] Neural2 失敗: {e} → WaveNet に切り替えます")

    # Fallback: WaveNet (異なるバージョンの API)
    try:
        audio_data = _synthesize(text, speaker, "wavenet")
        output_path.write_bytes(audio_data)
        logger.info(f"[TTS] WaveNet で生成: {output_path.name}")
        return output_path
    except Exception as e:
        logger.error(f"[TTS] WaveNet も失敗: {e}")
        raise RuntimeError(f"音声合成に失敗しました: {text[:30]!r}") from e


def generate_all_segments(dialogue: list[dict], segments_dir: Path) -> list[Path]:
    """
    台本の全台詞を音声合成してセグメントファイルのリストを返す
    """
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
