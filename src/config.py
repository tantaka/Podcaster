import os
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent
OUTPUT_DIR = BASE_DIR / "output"
DATA_DIR = BASE_DIR / "data"

# Research
TAVILY_API_KEY = os.environ.get("TAVILY_API_KEY", "")
BRAVE_SEARCH_API_KEY = os.environ.get("BRAVE_SEARCH_API_KEY", "")
SEARCH_TOPIC = "Claude Code 最新バージョン 変更点 アップデート"
SEARCH_QUERY_X = 'Claude Code update changelog site:x.com OR site:twitter.com'
SEARCH_QUERY_GITHUB = 'Claude Code release notes changelog'
GITHUB_API_URL = "https://api.github.com"
CLAUDE_CODE_REPO = "anthropics/claude-code"

# Script Generation
# Primary は Gemini Flash (Google AI Studio 無料枠: 1500 req/日)
# Fallback は Claude Haiku (有償、ANTHROPIC_API_KEY が設定されている場合のみ使用)
GOOGLE_GEMINI_API_KEY = os.environ.get("GOOGLE_GEMINI_API_KEY", "")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
GEMINI_MODEL_PRIMARY = "gemini-2.5-flash"
GEMINI_MODEL_FALLBACK = "gemini-2.5-pro"
CLAUDE_MODEL_FALLBACK = "claude-haiku-4-5-20251001"

# Audio Generation (Gemini TTS — google-genai SDK、無料枠)
# Primary モデル / Fallback モデル
TTS_MODEL_PRIMARY = "gemini-2.5-flash-preview-tts"
TTS_MODEL_FALLBACK = "gemini-2.5-pro-preview-tts"
# 男性: Charon(低め落ち着いた声) / 女性: Kore(明瞭な声)
TTS_VOICE_MALE_PRIMARY   = "Charon"
TTS_VOICE_FEMALE_PRIMARY = "Kore"
TTS_VOICE_MALE_FALLBACK  = "Fenrir"
TTS_VOICE_FEMALE_FALLBACK = "Aoede"
TTS_SAMPLE_RATE = 24000   # Gemini TTS の PCM 出力サンプルレート
SILENCE_BETWEEN_SPEAKERS_MS = 400  # 話者切り替え時の無音(ms)

# Google Drive
GOOGLE_DRIVE_CLIENT_ID = os.environ.get("GOOGLE_DRIVE_CLIENT_ID", "")
GOOGLE_DRIVE_CLIENT_SECRET = os.environ.get("GOOGLE_DRIVE_CLIENT_SECRET", "")
GOOGLE_DRIVE_REFRESH_TOKEN = os.environ.get("GOOGLE_DRIVE_REFRESH_TOKEN", "")
GOOGLE_DRIVE_FOLDER_NAME = "Podcaster"
EPISODES_FILENAME = "episodes.json"

# Retry settings (負荷を与えすぎないよう十分な待機時間を設定)
RETRY_MAX_ATTEMPTS = 3
RETRY_INITIAL_DELAY_SEC = 5
RETRY_MAX_DELAY_SEC = 120
RETRY_BACKOFF_FACTOR = 2

# Podcast settings
PODCAST_DURATION_TARGET_MIN = 5
HOST_MALE_NAME = "田中"
HOST_FEMALE_NAME = "佐藤"
