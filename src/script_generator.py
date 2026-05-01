"""
台本生成モジュール:
  Primary  - Gemini 2.0 Flash (Google AI Studio 無料枠)
  Fallback1 - Gemini 1.5 Flash (同じく無料枠・異なるバージョン)
  Fallback2 - Claude Haiku    (有償・ANTHROPIC_API_KEY 設定時のみ)
"""
import json
import logging
import re
from src.config import (
    GOOGLE_GEMINI_API_KEY,
    ANTHROPIC_API_KEY,
    GEMINI_MODEL_PRIMARY,
    GEMINI_MODEL_FALLBACK,
    CLAUDE_MODEL_FALLBACK,
    HOST_MALE_NAME,
    HOST_FEMALE_NAME,
    PODCAST_DURATION_TARGET_MIN,
)
from src.retry_utils import retry_with_backoff, NoRetryError

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = f"""あなたはポッドキャストの台本作家です。
Claude Code の特定バージョンにおける変更点・新機能について、日本語で分かりやすく解説する台本を書いてください。

ホスト:
- 男性ホスト「{HOST_MALE_NAME}さん」: 技術的な詳細を担当
- 女性ホスト「{HOST_FEMALE_NAME}さん」: 視聴者視点での質問・まとめを担当

要件:
- 目標時間: {PODCAST_DURATION_TARGET_MIN}分
- dialogue の全テキスト合計を厳守: 1200〜1800文字以内（これを超えないこと）
- 自然で聴きやすい口語日本語
- 冒頭でバージョン番号と公開日を必ず紹介すること
- そのバージョンで追加・変更・修正された点を具体的に解説すること
- 表面的な紹介だけでなく、実際の使い方や開発者への影響も解説すること
- 冒頭の挨拶と締めの言葉を含めること
- 専門用語は適切に説明すること

出力形式: 必ず以下の JSON 形式のみで出力すること（前後に余分なテキスト不要）:
{{
  "title": "エピソードタイトル（例: Claude Code v1.x.x リリース解説）",
  "topic_summary": "このエピソードで扱うバージョンと変更点の1文要約",
  "dialogue": [
    {{"speaker": "host_male", "text": "台詞テキスト"}},
    {{"speaker": "host_female", "text": "台詞テキスト"}},
    ...
  ]
}}
"""


def _build_user_prompt(research_data: dict, past_topics_note: str) -> str:
    summary_text = research_data.get("summary_text", "情報なし")
    target_release = research_data.get("target_release")

    version_section = ""
    if target_release:
        version = target_release.get("version", "不明")
        published_at = target_release.get("published_at", "不明")
        is_yesterday = target_release.get("is_yesterday", False)
        date_label = "前日公開" if is_yesterday else "直近公開"
        version_section = f"""=== 対象バージョン ({date_label}) ===
バージョン: {version}
公開日時 (UTC): {published_at}
リリースページ: {target_release.get("url", "")}

公式リリースノート:
{target_release.get("body") or "（リリースノート本文なし）"}

"""

    return f"""以下の情報を基に、Claude Code {target_release["version"] if target_release else "最新バージョン"} の変更点・新機能についてポッドキャスト台本を作成してください。

{version_section}=== Web・SNS 上の反応・解説 ===
{summary_text}

=== 注意事項 ===
{past_topics_note if past_topics_note else "特になし"}

上記の情報を基に、具体的で深みのある台本を JSON 形式で作成してください。"""


def _parse_script_json(text: str) -> dict:
    """LLM レスポンスから JSON を抽出してパース"""
    text = text.strip()
    # コードブロックを除去
    text = re.sub(r'^```(?:json)?\s*', '', text, flags=re.MULTILINE)
    text = re.sub(r'\s*```$', '', text, flags=re.MULTILINE)
    text = text.strip()
    data = json.loads(text)
    # 必須フィールドの検証
    assert "title" in data, "title フィールドがありません"
    assert "dialogue" in data, "dialogue フィールドがありません"
    assert len(data["dialogue"]) >= 4, "対話が短すぎます"
    for line in data["dialogue"]:
        assert line.get("speaker") in ("host_male", "host_female"), f"不正な speaker: {line.get('speaker')}"
        assert line.get("text", "").strip(), "空の台詞があります"
    return data


@retry_with_backoff(exceptions=(Exception,))
def _generate_with_gemini(user_prompt: str, model: str) -> dict:
    """Google Gemini API で台本生成 (無料枠) — google-genai SDK を使用"""
    from google import genai
    from google.genai import types
    if not GOOGLE_GEMINI_API_KEY:
        raise ValueError("GOOGLE_GEMINI_API_KEY が設定されていません")
    logger.info(f"[Script] Gemini API 使用: {model}")
    client = genai.Client(api_key=GOOGLE_GEMINI_API_KEY)

    # thinking を無効化してトークンを出力に集中、出力上限を余裕持って設定
    try:
        gen_config = types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            max_output_tokens=8192,
            thinking_config=types.ThinkingConfig(thinking_budget=0),
        )
    except AttributeError:
        # SDK バージョンが ThinkingConfig 未対応の場合
        gen_config = types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            max_output_tokens=8192,
        )

    try:
        response = client.models.generate_content(
            model=model,
            contents=user_prompt,
            config=gen_config,
        )
    except Exception as e:
        # limit: 0 はクォータゼロ = 待機しても解決しないので即 Fallback
        if "limit: 0" in str(e):
            raise NoRetryError(f"{model} は無料枠クォータなし") from e
        raise
    raw_text = response.text
    logger.info(f"[Script] Gemini レスポンス受信 ({len(raw_text)} 文字)")
    return _parse_script_json(raw_text)


@retry_with_backoff(exceptions=(Exception,))
def _generate_with_claude(user_prompt: str, model: str) -> dict:
    """Anthropic Claude API で台本生成 (有償 Fallback — API キーが設定されている場合のみ)"""
    import anthropic
    if not ANTHROPIC_API_KEY:
        raise ValueError("ANTHROPIC_API_KEY が設定されていません")
    logger.info(f"[Script] Claude API 使用: {model}")
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    message = client.messages.create(
        model=model,
        max_tokens=4096,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt}],
    )
    raw_text = message.content[0].text
    logger.info(f"[Script] Claude レスポンス受信 ({len(raw_text)} 文字)")
    return _parse_script_json(raw_text)


def generate_script(research_data: dict) -> dict:
    """
    調査データから台本を生成。
    Primary  : Gemini 2.0 Flash (無料枠)
    Fallback1: Gemini 1.5 Flash (同じく無料枠・異なるバージョン)
    Fallback2: Claude Haiku     (有償・ANTHROPIC_API_KEY が必要)
    """
    logger.info("=== 台本生成モジュール開始 ===")
    past_topics_note = research_data.get("past_topics_note", "")
    user_prompt = _build_user_prompt(research_data, past_topics_note)

    if not GOOGLE_GEMINI_API_KEY:
        raise RuntimeError(
            "GOOGLE_GEMINI_API_KEY が設定されていません。"
            "https://aistudio.google.com/ で無料の API キーを取得してください。"
        )

    # Primary: Gemini 2.5 Flash (無料)
    try:
        script = _generate_with_gemini(user_prompt, GEMINI_MODEL_PRIMARY)
        logger.info(f"[Script] {GEMINI_MODEL_PRIMARY} で生成成功: {script['title']}")
        script["generated_by"] = f"gemini/{GEMINI_MODEL_PRIMARY}"
        return script
    except NoRetryError as e:
        logger.warning(f"[Script] {GEMINI_MODEL_PRIMARY} クォータなし → {GEMINI_MODEL_FALLBACK} に切り替えます")
    except Exception as e:
        logger.warning(f"[Script] {GEMINI_MODEL_PRIMARY} 失敗: {e} → {GEMINI_MODEL_FALLBACK} に切り替えます")

    # Fallback1: Gemini 2.5 Pro (無料・異なるバージョン)
    try:
        script = _generate_with_gemini(user_prompt, GEMINI_MODEL_FALLBACK)
        logger.info(f"[Script] {GEMINI_MODEL_FALLBACK} で生成成功: {script['title']}")
        script["generated_by"] = f"gemini/{GEMINI_MODEL_FALLBACK}"
        return script
    except NoRetryError as e:
        logger.warning(f"[Script] {GEMINI_MODEL_FALLBACK} クォータなし → Claude Haiku に切り替えます")
    except Exception as e:
        logger.warning(f"[Script] {GEMINI_MODEL_FALLBACK} も失敗: {e} → Claude Haiku に切り替えます")

    # Fallback2: Claude Haiku (有償 — API キーがある場合のみ)
    if ANTHROPIC_API_KEY:
        try:
            script = _generate_with_claude(user_prompt, CLAUDE_MODEL_FALLBACK)
            logger.info(f"[Script] Claude Haiku で生成成功: {script['title']}")
            script["generated_by"] = f"claude/{CLAUDE_MODEL_FALLBACK}"
            return script
        except Exception as e:
            logger.error(f"[Script] Claude Haiku も失敗: {e}")
            raise RuntimeError("すべての台本生成 API が失敗しました") from e

    raise RuntimeError("Gemini API での台本生成に失敗しました。ログを確認してください。")
