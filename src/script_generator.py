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
from src.retry_utils import retry_with_backoff

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = f"""あなたはポッドキャストの台本作家です。
Claude Code の最新情報について、日本語で分かりやすく解説する台本を書いてください。

ホスト:
- 男性ホスト「{HOST_MALE_NAME}さん」: 技術的な詳細を担当
- 女性ホスト「{HOST_FEMALE_NAME}さん」: 視聴者視点での質問・まとめを担当

要件:
- 目標時間: {PODCAST_DURATION_TARGET_MIN}分（日本語で約1500〜2000文字）
- 自然で聴きやすい口語日本語
- 情報を深く掘り下げた内容（表面的な紹介だけでなく、実用的な意味合いも解説）
- 冒頭の挨拶と締めの言葉を含めること
- 専門用語は適切に説明すること

出力形式: 必ず以下の JSON 形式のみで出力すること（前後に余分なテキスト不要）:
{{
  "title": "エピソードタイトル",
  "topic_summary": "このエピソードで扱うトピックの1文要約",
  "dialogue": [
    {{"speaker": "host_male", "text": "台詞テキスト"}},
    {{"speaker": "host_female", "text": "台詞テキスト"}},
    ...
  ]
}}
"""


def _build_user_prompt(research_data: dict, past_topics_note: str) -> str:
    summary_text = research_data.get("summary_text", "情報なし")
    return f"""以下の最新情報を基に、Claude Code の変更点・新機能についてポッドキャスト台本を作成してください。

=== 最新情報 ===
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
    response = client.models.generate_content(
        model=model,
        contents=user_prompt,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            max_output_tokens=4096,
        ),
    )
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

    # Primary: Gemini 2.0 Flash (無料)
    try:
        script = _generate_with_gemini(user_prompt, GEMINI_MODEL_PRIMARY)
        logger.info(f"[Script] Gemini 2.0 Flash で生成成功: {script['title']}")
        script["generated_by"] = f"gemini/{GEMINI_MODEL_PRIMARY}"
        return script
    except Exception as e:
        logger.warning(f"[Script] Gemini 2.0 Flash 失敗: {e} → Gemini 1.5 Flash に切り替えます")

    # Fallback1: Gemini 1.5 Flash (無料・異なるバージョン)
    try:
        script = _generate_with_gemini(user_prompt, GEMINI_MODEL_FALLBACK)
        logger.info(f"[Script] Gemini 1.5 Flash で生成成功: {script['title']}")
        script["generated_by"] = f"gemini/{GEMINI_MODEL_FALLBACK}"
        return script
    except Exception as e:
        logger.warning(f"[Script] Gemini 1.5 Flash も失敗: {e} → Claude Haiku に切り替えます")

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
