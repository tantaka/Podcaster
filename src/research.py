"""
調査モジュール: Tavily API (X/Twitter含む) を Primary、Brave Search を Fallback として使用
GitHub API で公式リリース情報も取得
"""
import json
import logging
import requests
from datetime import datetime, timedelta
from typing import Optional
from src.config import (
    TAVILY_API_KEY,
    BRAVE_SEARCH_API_KEY,
    SEARCH_QUERY_X,
    SEARCH_QUERY_GITHUB,
    GITHUB_API_URL,
    CLAUDE_CODE_REPO,
)
from src.retry_utils import retry_with_backoff

logger = logging.getLogger(__name__)


@retry_with_backoff(exceptions=(requests.RequestException, Exception))
def _search_tavily(query: str, max_results: int = 10, include_domains: list | None = None) -> list[dict]:
    """Tavily API で検索 (X/Twitter を含む Web 全体)"""
    if not TAVILY_API_KEY:
        raise ValueError("TAVILY_API_KEY が設定されていません")
    logger.info(f"[Tavily] 検索クエリ: {query!r}")
    payload: dict = {
        "api_key": TAVILY_API_KEY,
        "query": query,
        "search_depth": "advanced",
        "max_results": max_results,
    }
    if include_domains:
        payload["include_domains"] = include_domains
    response = requests.post(
        "https://api.tavily.com/search",
        json=payload,
        timeout=30,
    )
    response.raise_for_status()
    data = response.json()
    results = data.get("results", [])
    logger.info(f"[Tavily] {len(results)} 件取得")
    return results


@retry_with_backoff(exceptions=(requests.RequestException, Exception))
def _search_brave(query: str, max_results: int = 10) -> list[dict]:
    """Brave Search API で検索 (Tavily 失敗時の Fallback)"""
    if not BRAVE_SEARCH_API_KEY:
        raise ValueError("BRAVE_SEARCH_API_KEY が設定されていません")
    logger.info(f"[Brave] 検索クエリ: {query!r}")
    response = requests.get(
        "https://api.search.brave.com/res/v1/web/search",
        headers={
            "Accept": "application/json",
            "Accept-Encoding": "gzip",
            "X-Subscription-Token": BRAVE_SEARCH_API_KEY,
        },
        params={"q": query, "count": max_results, "freshness": "pd"},  # 直近1日
        timeout=30,
    )
    response.raise_for_status()
    data = response.json()
    web_results = data.get("web", {}).get("results", [])
    results = [
        {"title": r.get("title", ""), "url": r.get("url", ""), "content": r.get("description", "")}
        for r in web_results
    ]
    logger.info(f"[Brave] {len(results)} 件取得")
    return results


@retry_with_backoff(exceptions=(requests.RequestException, Exception))
def _get_github_releases(repo: str, limit: int = 5) -> list[dict]:
    """GitHub API でリリース情報を取得 (完全無料)"""
    logger.info(f"[GitHub] リリース情報取得: {repo}")
    response = requests.get(
        f"{GITHUB_API_URL}/repos/{repo}/releases",
        headers={"Accept": "application/vnd.github.v3+json"},
        params={"per_page": limit},
        timeout=30,
    )
    response.raise_for_status()
    releases = response.json()
    results = []
    for r in releases:
        published_at = r.get("published_at", "")
        # 過去30日以内のリリースのみ
        if published_at:
            pub_date = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
            if pub_date > datetime.now(pub_date.tzinfo) - timedelta(days=30):
                results.append({
                    "title": f"GitHub Release: {r.get('name') or r.get('tag_name', '')}",
                    "url": r.get("html_url", ""),
                    "content": r.get("body", "")[:2000],  # 長すぎる場合は切り詰め
                })
    logger.info(f"[GitHub] {len(results)} 件のリリース情報取得")
    return results


def _search_with_fallback(query: str, include_domains: list | None = None) -> list[dict]:
    """Tavily → Brave Search の順でフォールバック検索"""
    # Primary: Tavily
    if TAVILY_API_KEY:
        try:
            return _search_tavily(query, include_domains=include_domains)
        except Exception as e:
            logger.warning(f"[Research] Tavily 失敗: {e} → Brave Search に切り替えます")
    else:
        logger.warning("[Research] TAVILY_API_KEY 未設定 → Brave Search を使用します")

    # Fallback: Brave Search (include_domains は query に site: として組み込む)
    if BRAVE_SEARCH_API_KEY:
        brave_query = query
        if include_domains:
            site_filter = " OR ".join(f"site:{d}" for d in include_domains)
            brave_query = f"{query} ({site_filter})"
        try:
            return _search_brave(brave_query)
        except Exception as e:
            logger.error(f"[Research] Brave Search も失敗: {e}")
            raise RuntimeError("すべての検索 API が失敗しました") from e

    raise RuntimeError("利用可能な検索 API がありません (TAVILY_API_KEY または BRAVE_SEARCH_API_KEY を設定してください)")


def research(past_topics: Optional[list[str]] = None) -> dict:
    """
    Claude Code の最新情報を調査して構造化された調査結果を返す。
    past_topics: 重複を避けるために渡す過去のトピックリスト
    """
    logger.info("=== 調査モジュール開始 ===")
    past_topics = past_topics or []

    results = {}

    # 1. X/Twitter に絞った検索 (Tavily or Brave)
    logger.info("[Research] X/Twitter 検索...")
    try:
        web_results = _search_with_fallback(
            SEARCH_QUERY_X,
            include_domains=["twitter.com", "x.com"],
        )
        results["web_search"] = web_results
    except Exception as e:
        logger.error(f"[Research] Web 検索失敗: {e}")
        results["web_search"] = []

    # 2. 公式情報検索 (anthropic.com + GitHub)
    logger.info("[Research] 公式情報検索...")
    try:
        general_results = _search_with_fallback(
            SEARCH_QUERY_GITHUB,
            include_domains=["anthropic.com", "github.com"],
        )
        results["general_search"] = general_results
    except Exception as e:
        logger.error(f"[Research] 一般検索失敗: {e}")
        results["general_search"] = []

    # 3. GitHub リリース情報 (無料・安定)
    logger.info("[Research] GitHub リリース情報取得...")
    try:
        github_results = _get_github_releases(CLAUDE_CODE_REPO)
        results["github_releases"] = github_results
    except Exception as e:
        logger.warning(f"[Research] GitHub リリース取得失敗: {e}")
        results["github_releases"] = []

    # 収集した情報をまとめてテキスト化
    all_items = (
        results.get("web_search", [])
        + results.get("general_search", [])
        + results.get("github_releases", [])
    )

    if not all_items:
        raise RuntimeError("調査結果が0件です。API キーを確認してください。")

    # 重複排除 (URLベース)
    seen_urls = set()
    unique_items = []
    for item in all_items:
        url = item.get("url", "")
        if url and url not in seen_urls:
            seen_urls.add(url)
            unique_items.append(item)

    logger.info(f"[Research] 合計 {len(unique_items)} 件のユニーク情報を収集")

    # 過去トピックの注記
    past_topics_note = ""
    if past_topics:
        past_topics_note = "【過去に扱ったトピック（重複を避けること）】\n" + "\n".join(
            f"- {t}" for t in past_topics[-10:]
        )

    summary_text = _build_summary_text(unique_items)

    research_data = {
        "collected_at": datetime.utcnow().isoformat() + "Z",
        "raw_results": results,
        "unique_items": unique_items,
        "summary_text": summary_text,
        "past_topics_note": past_topics_note,
        "item_count": len(unique_items),
    }

    logger.info("=== 調査モジュール完了 ===")
    return research_data


def _build_summary_text(items: list[dict]) -> str:
    """調査結果を台本生成用のテキストにまとめる"""
    lines = []
    for i, item in enumerate(items[:15], 1):  # 最大15件
        title = item.get("title", "タイトル不明")
        url = item.get("url", "")
        content = item.get("content", "")
        lines.append(f"【情報 {i}】")
        lines.append(f"タイトル: {title}")
        if url:
            lines.append(f"URL: {url}")
        if content:
            lines.append(f"内容: {content[:500]}")
        lines.append("")
    return "\n".join(lines)
