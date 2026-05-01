"""
音声結合モジュール: pydub で各セグメントを結合して最終 MP3 を生成
"""
import logging
from pathlib import Path
from src.config import SILENCE_BETWEEN_SPEAKERS_MS

logger = logging.getLogger(__name__)


def merge_segments(segment_paths: list[Path], output_path: Path) -> Path:
    """
    セグメントファイルを順番に結合して MP3 を出力。
    話者切り替え時に無音を挿入して自然な間を作る。
    """
    from pydub import AudioSegment

    logger.info(f"=== 音声結合開始: {len(segment_paths)} セグメント → {output_path.name} ===")

    if not segment_paths:
        raise ValueError("結合するセグメントがありません")

    silence = AudioSegment.silent(duration=SILENCE_BETWEEN_SPEAKERS_MS)
    combined = AudioSegment.empty()
    prev_speaker = None

    for i, seg_path in enumerate(segment_paths):
        if not seg_path.exists():
            raise FileNotFoundError(f"セグメントファイルが見つかりません: {seg_path}")

        # ファイル名からスピーカーを判定
        current_speaker = "host_male" if "host_male" in seg_path.name else "host_female"

        audio = AudioSegment.from_mp3(str(seg_path))

        # 話者が切り替わった場合に無音を挿入
        if prev_speaker is not None and current_speaker != prev_speaker:
            combined += silence

        combined += audio
        prev_speaker = current_speaker
        logger.info(f"[Merger] セグメント {i+1}/{len(segment_paths)} 追加 ({len(audio)/1000:.1f}秒)")

    duration_sec = len(combined) / 1000
    logger.info(f"[Merger] 合計時間: {duration_sec:.1f}秒 ({duration_sec/60:.1f}分)")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    combined.export(str(output_path), format="mp3", bitrate="192k")
    logger.info(f"[Merger] MP3 出力完了: {output_path}")
    return output_path
