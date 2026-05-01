"""
Google Drive クライアント: OAuth2 refresh token で認証 (初回手動認証後は自動)
"""
import io
import json
import logging
from pathlib import Path
from typing import Optional
from src.config import (
    GOOGLE_DRIVE_CLIENT_ID,
    GOOGLE_DRIVE_CLIENT_SECRET,
    GOOGLE_DRIVE_REFRESH_TOKEN,
    GOOGLE_DRIVE_FOLDER_NAME,
    EPISODES_FILENAME,
)
from src.retry_utils import retry_with_backoff

logger = logging.getLogger(__name__)


def _get_credentials():
    """環境変数の refresh token から Google Drive 認証情報を取得"""
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request

    if not all([GOOGLE_DRIVE_CLIENT_ID, GOOGLE_DRIVE_CLIENT_SECRET, GOOGLE_DRIVE_REFRESH_TOKEN]):
        raise ValueError(
            "Google Drive の認証情報が不足しています。"
            "GOOGLE_DRIVE_CLIENT_ID / GOOGLE_DRIVE_CLIENT_SECRET / GOOGLE_DRIVE_REFRESH_TOKEN を設定してください。"
        )

    creds = Credentials(
        token=None,
        refresh_token=GOOGLE_DRIVE_REFRESH_TOKEN,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=GOOGLE_DRIVE_CLIENT_ID,
        client_secret=GOOGLE_DRIVE_CLIENT_SECRET,
        scopes=["https://www.googleapis.com/auth/drive.file"],
    )
    creds.refresh(Request())
    logger.info("[Drive] 認証成功")
    return creds


def _get_service():
    """Google Drive API サービスを取得"""
    from googleapiclient.discovery import build

    creds = _get_credentials()
    service = build("drive", "v3", credentials=creds, cache_discovery=False)
    return service


def _find_or_create_folder(service, folder_name: str) -> str:
    """フォルダを検索、なければ作成してフォルダ ID を返す"""
    query = (
        f"name='{folder_name}' and mimeType='application/vnd.google-apps.folder' "
        "and trashed=false"
    )
    results = service.files().list(q=query, fields="files(id, name)").execute()
    files = results.get("files", [])
    if files:
        folder_id = files[0]["id"]
        logger.info(f"[Drive] 既存フォルダ発見: {folder_name} (id={folder_id})")
        return folder_id

    file_metadata = {
        "name": folder_name,
        "mimeType": "application/vnd.google-apps.folder",
    }
    folder = service.files().create(body=file_metadata, fields="id").execute()
    folder_id = folder["id"]
    logger.info(f"[Drive] フォルダ作成: {folder_name} (id={folder_id})")
    return folder_id


@retry_with_backoff(exceptions=(Exception,))
def upload_file(local_path: Path, filename: Optional[str] = None) -> str:
    """
    ファイルを Google Drive の Podcaster フォルダにアップロード。
    ファイルが既に存在する場合は上書き。
    Returns: アップロードされたファイルの ID
    """
    from googleapiclient.http import MediaFileUpload

    service = _get_service()
    folder_id = _find_or_create_folder(service, GOOGLE_DRIVE_FOLDER_NAME)
    upload_name = filename or local_path.name

    # 既存ファイルの確認
    query = f"name='{upload_name}' and '{folder_id}' in parents and trashed=false"
    results = service.files().list(q=query, fields="files(id, name)").execute()
    existing = results.get("files", [])

    mime_type = "audio/mpeg" if local_path.suffix == ".mp3" else "application/json"
    media = MediaFileUpload(str(local_path), mimetype=mime_type, resumable=True)

    if existing:
        # 上書き
        file_id = existing[0]["id"]
        service.files().update(fileId=file_id, media_body=media).execute()
        logger.info(f"[Drive] 上書きアップロード完了: {upload_name} (id={file_id})")
    else:
        # 新規
        file_metadata = {"name": upload_name, "parents": [folder_id]}
        uploaded = service.files().create(
            body=file_metadata, media_body=media, fields="id"
        ).execute()
        file_id = uploaded["id"]
        logger.info(f"[Drive] 新規アップロード完了: {upload_name} (id={file_id})")

    return file_id


@retry_with_backoff(exceptions=(Exception,))
def download_json(filename: str) -> Optional[dict]:
    """
    Google Drive から JSON ファイルをダウンロードして dict を返す。
    ファイルが存在しない場合は None を返す。
    """
    from googleapiclient.http import MediaIoBaseDownload

    service = _get_service()
    folder_id = _find_or_create_folder(service, GOOGLE_DRIVE_FOLDER_NAME)

    query = f"name='{filename}' and '{folder_id}' in parents and trashed=false"
    results = service.files().list(q=query, fields="files(id, name)").execute()
    files = results.get("files", [])

    if not files:
        logger.info(f"[Drive] ファイルが見つかりません: {filename}")
        return None

    file_id = files[0]["id"]
    request = service.files().get_media(fileId=file_id)
    fh = io.BytesIO()
    downloader = MediaIoBaseDownload(fh, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()

    fh.seek(0)
    data = json.loads(fh.read().decode("utf-8"))
    logger.info(f"[Drive] ダウンロード完了: {filename}")
    return data


def upload_json(data: dict, filename: str, tmp_dir: Path) -> str:
    """dict を JSON ファイルとして Google Drive にアップロード"""
    tmp_path = tmp_dir / filename
    tmp_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return upload_file(tmp_path, filename)
