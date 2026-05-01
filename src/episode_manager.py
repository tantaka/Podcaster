"""
エピソード管理モジュール: 過去エピソードの履歴管理 (重複回避)
Google Drive の episodes.json で永続化
"""
import logging
from datetime import datetime
from pathlib import Path
import src.drive_client as drive_client
from src.config import EPISODES_FILENAME

logger = logging.getLogger(__name__)


def load_episodes() -> dict:
    """
    Google Drive から episodes.json を読み込む。
    存在しない場合は空の構造を返す。
    """
    logger.info("[Episodes] Google Drive からエピソード履歴を読み込み...")
    try:
        data = drive_client.download_json(EPISODES_FILENAME)
        if data:
            episode_count = len(data.get("episodes", []))
            logger.info(f"[Episodes] {episode_count} 件の過去エピソードを読み込みました")
            return data
    except Exception as e:
        logger.warning(f"[Episodes] 読み込み失敗 (初回実行の可能性): {e}")

    return {"episodes": [], "created_at": datetime.utcnow().isoformat() + "Z"}


def get_past_topics(episodes_data: dict) -> list[str]:
    """過去のトピック一覧を返す (重複チェック用)"""
    return [
        ep.get("topic_summary", ep.get("title", ""))
        for ep in episodes_data.get("episodes", [])
    ]


def add_episode(
    episodes_data: dict,
    title: str,
    topic_summary: str,
    drive_file_id: str,
    duration_sec: float,
    generated_by: str,
) -> dict:
    """エピソードを履歴に追加"""
    episode = {
        "date": datetime.utcnow().strftime("%Y-%m-%d"),
        "title": title,
        "topic_summary": topic_summary,
        "drive_file_id": drive_file_id,
        "duration_sec": round(duration_sec, 1),
        "generated_by": generated_by,
        "created_at": datetime.utcnow().isoformat() + "Z",
    }
    episodes_data["episodes"].append(episode)
    episodes_data["updated_at"] = datetime.utcnow().isoformat() + "Z"
    logger.info(f"[Episodes] エピソード追加: {title}")
    return episodes_data


def save_episodes(episodes_data: dict, tmp_dir: Path) -> str:
    """episodes.json を Google Drive に保存"""
    logger.info("[Episodes] Google Drive にエピソード履歴を保存...")
    file_id = drive_client.upload_json(episodes_data, EPISODES_FILENAME, tmp_dir)
    logger.info(f"[Episodes] 保存完了 (id={file_id})")
    return file_id
