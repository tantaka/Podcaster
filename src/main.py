"""
メインオーケストレーター: Podcast 生成の全工程を管理
"""
import json
import logging
import re
import sys
from datetime import datetime
from pathlib import Path

from src.config import OUTPUT_DIR
import src.research as research_module
import src.script_generator as script_gen
import src.audio_generator as audio_gen
import src.audio_merger as audio_merger
import src.drive_client as drive_client
import src.episode_manager as episode_manager

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)


def main():
    run_date = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    run_dir = OUTPUT_DIR / run_date
    run_dir.mkdir(parents=True, exist_ok=True)

    logger.info("=" * 60)
    logger.info(f"Podcast 生成開始: {run_date}")
    logger.info("=" * 60)

    # ─────────────────────────────────────────
    # Step 1: 過去エピソード読み込み (重複回避)
    # ─────────────────────────────────────────
    logger.info("\n[Step 1/6] 過去エピソード読み込み...")
    episodes_data = episode_manager.load_episodes()
    past_topics = episode_manager.get_past_topics(episodes_data)
    logger.info(f"  過去トピック数: {len(past_topics)}")

    # ─────────────────────────────────────────
    # Step 2: 調査 (X/Twitter, GitHub, Web)
    # ─────────────────────────────────────────
    logger.info("\n[Step 2/6] 最新情報を調査中...")
    research_data = research_module.research(past_topics=past_topics)

    # 調査結果を保存
    research_path = run_dir / "research.json"
    research_path.write_text(
        json.dumps(research_data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    logger.info(f"  調査結果保存: {research_path}")

    # ─────────────────────────────────────────
    # Step 3: 台本生成
    # ─────────────────────────────────────────
    logger.info("\n[Step 3/6] 台本を生成中...")
    script = script_gen.generate_script(research_data)

    # 台本を保存
    script_path = run_dir / "script.json"
    script_path.write_text(
        json.dumps(script, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    logger.info(f"  台本保存: {script_path}")
    logger.info(f"  タイトル: {script['title']}")
    logger.info(f"  対話行数: {len(script['dialogue'])} 行")

    # ─────────────────────────────────────────
    # Step 4: 音声合成 (セグメント生成)
    # ─────────────────────────────────────────
    logger.info("\n[Step 4/6] 音声を合成中...")
    segments_dir = run_dir / "audio_segments"
    segment_paths = audio_gen.generate_all_segments(script["dialogue"], segments_dir)
    logger.info(f"  {len(segment_paths)} セグメント生成完了")

    # ─────────────────────────────────────────
    # Step 5: 音声結合 → MP3
    # ─────────────────────────────────────────
    logger.info("\n[Step 5/6] 音声を結合中...")
    date_str = datetime.utcnow().strftime("%Y%m%d")
    safe_title = re.sub(r'[\\/:*?"<>|　\s]+', "_", script["title"])[:50].strip("_")
    mp3_filename = f"podcast_{date_str}_{safe_title}.mp3"
    mp3_path = run_dir / mp3_filename
    merged_path = audio_merger.merge_segments(segment_paths, mp3_path)

    from pydub import AudioSegment
    audio_len = len(AudioSegment.from_mp3(str(merged_path))) / 1000
    logger.info(f"  MP3 生成完了: {merged_path.name} ({audio_len:.1f}秒 / {audio_len/60:.1f}分)")

    # ─────────────────────────────────────────
    # Step 6: Google Drive アップロード
    # ─────────────────────────────────────────
    logger.info("\n[Step 6/6] Google Drive にアップロード中...")

    # MP3 アップロード
    mp3_file_id = drive_client.upload_file(merged_path, mp3_filename)
    logger.info(f"  MP3 アップロード完了 (id={mp3_file_id})")

    # 台本 JSON もアップロード (参考用)
    script_filename = f"script_{date_str}_{safe_title}.json"
    drive_client.upload_file(script_path, script_filename)
    logger.info(f"  台本アップロード完了: {script_filename}")

    # エピソード履歴を更新・保存
    episodes_data = episode_manager.add_episode(
        episodes_data=episodes_data,
        title=script["title"],
        topic_summary=script.get("topic_summary", ""),
        drive_file_id=mp3_file_id,
        duration_sec=audio_len,
        generated_by=script.get("generated_by", "unknown"),
    )
    episode_manager.save_episodes(episodes_data, run_dir)

    logger.info("\n" + "=" * 60)
    logger.info("Podcast 生成完了!")
    logger.info(f"  タイトル : {script['title']}")
    logger.info(f"  時間     : {audio_len:.1f}秒 ({audio_len/60:.1f}分)")
    logger.info(f"  Drive ID : {mp3_file_id}")
    logger.info(f"  成果物   : {run_dir}")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
