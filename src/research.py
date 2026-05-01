"""
調査モジュール: Tavily API (X/Twitter含む) を Primary、Brave Search を Fallback として使用
GitHub API で前日公開バージョンを特定し、バージョン指定の検索クエリを使用
"""
import logging
import requests
from datetime import datetime, timedelta, timezone
from typing import Optional
from src.config import (
    TAVILY_API_KEY,
    BRAVE_SEARCH_API_KEY,
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
def _find_target_release(repo: str) -> dict | None:
    """
    前日 (UTC) に公開されたリリースを GitHub API で探す。
    前日公開がなければ直近のリリースを返す。
    """
    now = datetime.now(timezone.utc)
    yesterday_date = (now - timedelta(days=1)).date()

    logger.info(f"[GitHub] リリース情報取得: {repo} (前日={yesterday_date})")
    response = requests.get(
        f"{GITHUB_API_URL}/repos/{repo}/releases",
        headers={"Accept": "application/vnd.github.v3+json"},
        params={"per_page": 20},
        timeout=30,
    )
    response.raise_for_status()
    releases = response.json()

    if not releases:
        logger.warning("[GitHub] リリース情報が取得できませんでした")
        return None

    # 前日公開のリリースを優先
    for r in releases:
        published_at = r.get("published_at", "")
        if published_at:
            pub_dt = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
            if pub_dt.date() == yesterday_date:
                version = r.get("name") or r.get("tag_name", "")
                logger.info(f"[GitHub] 前日公開バージョン発見: {version} ({published_at})")
                return {
                    "version": version,
                    "tag": r.get("tag_name", ""),
                    "published_at": published_at,
                    "body": (r.get("body") or "")[:3000],
                    "url": r.get("html_url", ""),
                    "is_yesterday": True,
                }

    # 前日公開なし → 直近のリリースを使用
    r = releases[0]
    version = r.get("name") or r.get("tag_name", "")
    published_at = r.get("published_at", "")
    logger.info(f"[GitHub] 前日公開なし → 直近バージョン使用: {version} ({published_at})")
    return {
        "version": version,
        "tag": r.get("tag_name", ""),
        "published_at": published_at,
        "body": (r.get("body") or "")[:3000],
        "url": r.get("html_url", ""),
        "is_yesterday": False,
    }


def _search_with_fallback(query: str, include_domains: list | None = None) -> list[dict]:
    """Tavily → Brave Search の順でフォールバック検索"""
    if TAVILY_API_KEY:
        try:
            return _search_tavily(query, include_domains=include_domains)
        except Exception as e:
            logger.warning(f"[Research] Tavily 失敗: {e} → Brave Search に切り替えます")
    else:
        logger.warning("[Research] TAVILY_API_KEY 未設定 → Brave Search を使用します")

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
    Claude Code の特定バージョン情報を調査して構造化された調査結果を返す。
    前日公開バージョンを優先し、なければ直近バージョンを対象とする。
    """
    logger.info("=== 調査モジュール開始 ===")
    past_topics = past_topics or []

    # 0. ターゲットバージョンを GitHub API で特定
    target_release = None
    try:
        target_release = _find_target_release(CLAUDE_CODE_REPO)
    except Exception as e:
        logger.warning(f"[Research] GitHub リリース取得失敗: {e}")

    # バージョン指定の検索クエリを構築
    if target_release:
        version = target_release["version"]
        x_query = f"Claude Code {version} site:x.com OR site:twitter.com"
        gh_query = f"Claude Code {version} release changelog changes"
    else:
        version = ""
        x_query = "Claude Code update changelog site:x.com OR site:twitter.com"
        gh_query = "Claude Code release notes changelog"

    results = {}

    # 1. X/Twitter 検索
    logger.info(f"[Research] X/Twitter 検索: {x_query!r}")
    try:
        results["web_search"] = _search_with_fallback(
            x_query,
            include_domains=["twitter.com", "x.com"],
        )
    except Exception as e:
        logger.error(f"[Research] Web 検索失敗: {e}")
        results["web_search"] = []

    # 2. 公式情報検索
    logger.info(f"[Research] 公式情報検索: {gh_query!r}")
    try:
        results["general_search"] = _search_with_fallback(
            gh_query,
            include_domains=["anthropic.com", "github.com"],
        )
    except Exception as e:
        logger.error(f"[Research] 一般検索失敗: {e}")
        results["general_search"] = []

    # GitHub リリース情報はターゲットリリースとして既に取得済み
    if target_release and target_release.get("body"):
        results["github_releases"] = [{
            "title": f"GitHub Release: {target_release['version']}",
            "url": target_release["url"],
            "content": target_release["body"],
        }]
    else:
        results["github_releases"] = []

    # 重複排除 (URLベース)
    all_items = (
        results.get("web_search", [])
        + results.get("general_search", [])
        + results.get("github_releases", [])
    )
    seen_urls: set[str] = set()
    unique_items = []
    for item in all_items:
        url = item.get("url", "")
        if url and url not in seen_urls:
            seen_urls.add(url)
            unique_items.append(item)

    if not unique_items:
        raise RuntimeError("調査結果が0件です。API キーを確認してください。")

    logger.info(f"[Research] 合計 {len(unique_items)} 件のユニーク情報を収集")

    past_topics_note = ""
    if past_topics:
        past_topics_note = "【過去に扱ったトピック（重複を避けること）】\n" + "\n".join(
            f"- {t}" for t in past_topics[-10:]
        )

    summary_text = _build_summary_text(unique_items)

    research_data = {
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "target_release": target_release,
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
    for i, item in enumerate(items[:15], 1):
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
