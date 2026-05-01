"""
Google Drive & Cloud TTS の初回認証セットアップスクリプト
Google Colab (https://colab.research.google.com) で実行してください。
ローカルへのインストール不要です。

【実行手順】
1. https://colab.research.google.com を開く
2. 新しいノートブックを作成
3. このファイルの内容を「セルごと」に分けて貼り付けて実行
4. 出力された値を GitHub Secrets に設定する
"""

# ==============================================================
# 【セル 1】ライブラリのインストール
# ==============================================================
# 以下を Colab セルに貼り付けて実行してください:
# !pip install -q google-auth google-auth-oauthlib google-api-python-client

# ==============================================================
# 【セル 2】Google Cloud Console での事前準備 (1回だけ実施)
# ==============================================================
# 1. https://console.cloud.google.com でプロジェクトを作成
#
# 2. 「APIとサービス」→「ライブラリ」で以下を有効化:
#    - Google Drive API
#    - Cloud Text-to-Speech API
#
# 3. 「APIとサービス」→「認証情報」→「+ 認証情報を作成」
#    →「OAuth クライアント ID」を選択
#    - アプリケーションの種類: デスクトップアプリ
#    - 名前: Podcaster
#    - 作成後、「クライアント ID」と「クライアント シークレット」をメモ
#
# 4. 同ページ「OAuth 同意画面」→「テストユーザーを追加」
#    → 自分のGmailアドレスを追加

# ==============================================================
# 【セル 3】Google Drive OAuth2 認証 (以下を Colab セルに貼り付けて実行)
# ==============================================================

CLIENT_ID = "YOUR_CLIENT_ID_HERE"          # ← Google Cloud Console から取得
CLIENT_SECRET = "YOUR_CLIENT_SECRET_HERE"  # ← Google Cloud Console から取得

from google_auth_oauthlib.flow import Flow

SCOPES = ["https://www.googleapis.com/auth/drive.file"]

client_config = {
    "installed": {
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "redirect_uris": ["http://localhost"],
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
    }
}

flow = Flow.from_client_config(client_config, SCOPES)
flow.redirect_uri = "http://localhost"

auth_url, _ = flow.authorization_url(
    access_type="offline",
    prompt="consent",  # 毎回 refresh_token を取得するために必要
    include_granted_scopes="true",
)

print("=" * 60)
print("以下の URL をブラウザで開いて Google アカウントで認証してください:")
print("=" * 60)
print(auth_url)
print("=" * 60)
print()
print("認証後、リダイレクト先 URL (http://localhost/?code=...) の")
print("URL 全体をコピーして以下に貼り付けてください:")

redirect_response = input("リダイレクト URL を貼り付け > ")

flow.fetch_token(authorization_response=redirect_response)
creds = flow.credentials

print("\n" + "=" * 60)
print("=== 以下の値を GitHub Secrets に設定してください ===")
print("=" * 60)
print(f"\nGOOGLE_DRIVE_CLIENT_ID:\n{CLIENT_ID}")
print(f"\nGOOGLE_DRIVE_CLIENT_SECRET:\n{CLIENT_SECRET}")
print(f"\nGOOGLE_DRIVE_REFRESH_TOKEN:\n{creds.refresh_token}")
print("\n" + "=" * 60)

# ==============================================================
# 【セル 4 (参考)】GitHub Secrets に設定が必要な値の一覧
# ==============================================================
print("""
GitHub Secrets の設定手順:
  1. GitHub リポジトリを開く
  2. Settings → Secrets and variables → Actions
  3. 「New repository secret」で以下を追加:

  ── 必須 ──────────────────────────────────────────────────────
  GOOGLE_DRIVE_CLIENT_ID      ← セル 3 の出力
  GOOGLE_DRIVE_CLIENT_SECRET  ← セル 3 の出力
  GOOGLE_DRIVE_REFRESH_TOKEN  ← セル 3 の出力
  GOOGLE_GEMINI_API_KEY       ← https://aistudio.google.com/ (無料・TTS兼用)
  TAVILY_API_KEY              ← https://tavily.com/ (無料: 1000回/月)

  ── フォールバック用 (任意・有償) ──────────────────────────
  ANTHROPIC_API_KEY           ← https://console.anthropic.com/ (有償)
  BRAVE_SEARCH_API_KEY        ← https://brave.com/search/api/
""")
