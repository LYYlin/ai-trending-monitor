#!/usr/bin/env python3
"""
GitHub AI 热点监控脚本
每天自动抓取 GitHub 上 AI 相关的升星热点项目，生成可视化 HTML 报告。

数据来源：
1. GitHub Trending 页面（weekly/daily，按近期 star 增长排序）
2. GitHub Search API（搜索近期活跃的高星 AI 项目，通过历史数据计算 star 增量）
"""

import json
import os
import sys
import time
import datetime
from pathlib import Path

import requests
from bs4 import BeautifulSoup

# ============================================================
# 配置
# ============================================================

SCRIPT_DIR = Path(__file__).parent.resolve()
DATA_DIR = SCRIPT_DIR / "data"
REPORTS_DIR = SCRIPT_DIR / "reports"
HISTORY_FILE = DATA_DIR / "history.json"

# GitHub API 配置（可选 Token，无 Token 也能运行）
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
GITHUB_API_HEADERS = {
    "Accept": "application/vnd.github+json",
}
if GITHUB_TOKEN:
    GITHUB_API_HEADERS["Authorization"] = f"Bearer {GITHUB_TOKEN}"

REQUEST_TIMEOUT = 30
TRENDING_TIMEOUT = 15  # Trending 页面更短的超时时间

# AI 分类关键词
CATEGORIES = {
    "llm_agent": {
        "label": "LLM / Agent",
        "icon": "🤖",
        "keywords": [
            "llm", "agent", "rag", "chatgpt", "gpt", "transformer",
            "langchain", "llama", "mistral", "gemini", "claude",
            "prompt", "chatbot", "assistant", "copilot", "openai",
            "anthropic", "ollama", "vllm", "reasoning", "tool-use",
            "function-calling", "ai-agent", "autonomous", "multi-agent",
        ],
    },
    "aigc": {
        "label": "AIGC 生成式",
        "icon": "🎨",
        "keywords": [
            "stable-diffusion", "midjourney", "image-generation",
            "video-generation", "text-to-image", "text-to-video",
            "diffusion", "gan", "3d-generation", "neural-rendering",
            "ai-art", "comfyui", "automatic1111", "controlnet",
            "dreambooth", "lora", "voice-cloning", "tts", "music-generation",
            "ai-music", "suno", "kling", "sora", "flux",
        ],
    },
    "ml_tools": {
        "label": "ML 工具 / 框架",
        "icon": "🔧",
        "keywords": [
            "pytorch", "tensorflow", "machine-learning", "deep-learning",
            "neural-network", "training", "model", "dataset", "benchmark",
            "inference", "quantization", "fine-tuning", "pretrained",
            "gpu", "cuda", "distributed", "vector-database", "embedding",
            "gpu-optimization", "kernel", "compiler", "serving",
        ],
    },
}

# AI 相关通用关键词（用于 Trending 页面筛选）
AI_GENERAL_KEYWORDS = set()
for cat in CATEGORIES.values():
    AI_GENERAL_KEYWORDS.update(cat["keywords"])
AI_GENERAL_KEYWORDS.update([
    "ai", "artificial-intelligence", "ml", "nlp", "computer-vision",
    "generative", "neural", "deep", "learning", "model", "inference",
])

# Search API 话题查询配置
# 格式: (话题, 分类, 描述)
SEARCH_TOPICS = [
    # LLM / Agent
    ("llm", "llm_agent", "LLM"),
    ("ai-agent", "llm_agent", "AI Agent"),
    ("rag", "llm_agent", "RAG"),
    ("langchain", "llm_agent", "LangChain"),
    ("chatgpt", "llm_agent", "ChatGPT"),
    # AIGC
    ("stable-diffusion", "aigc", "Stable Diffusion"),
    ("generative-ai", "aigc", "Generative AI"),
    ("comfyui", "aigc", "ComfyUI"),
    # ML 工具
    ("machine-learning", "ml_tools", "Machine Learning"),
    ("deep-learning", "ml_tools", "Deep Learning"),
    ("pytorch", "ml_tools", "PyTorch"),
    ("vector-database", "ml_tools", "Vector Database"),
    ("model-inference", "ml_tools", "Model Inference"),
]


# ============================================================
# 数据采集：GitHub Trending 页面
# ============================================================

def fetch_trending(since="daily", language=""):
    """
    抓取 GitHub Trending 页面。
    since: "daily", "weekly", "monthly"
    language: 空字符串表示所有语言，或 "python", "typescript" 等
    """
    url = "https://github.com/trending"
    params = {"since": since}
    if language:
        url = f"https://github.com/trending/{language}"

    try:
        resp = requests.get(url, params=params, timeout=TRENDING_TIMEOUT, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept-Language": "en-US,en;q=0.9",
        })
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"  [Warning] Trending fetch failed ({since}/{language}): {e}")
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    repos = []

    articles = soup.select("article.Box-row")
    for article in articles:
        try:
            # 项目名
            name_el = article.select_one("h2 a")
            if not name_el:
                continue
            repo_path = name_el.get("href", "").strip().strip("/")
            full_name = repo_path

            # 描述
            desc_el = article.select_one("p")
            description = desc_el.get_text(strip=True) if desc_el else ""

            # 语言
            lang_el = article.select_one("[itemprop='programmingLanguage']")
            language_name = lang_el.get_text(strip=True) if lang_el else ""

            # star 总数
            stars = 0
            star_links = article.select("a.Link")
            for link in star_links:
                href = link.get("href", "")
                if href.endswith("/stargazers"):
                    star_text = link.get_text(strip=True).replace(",", "")
                    try:
                        stars = int(star_text)
                    except ValueError:
                        pass
                    break

            # 今日/本周新增 star
            today_stars = 0
            today_el = article.select_one("span.d-inline-block.float-sm-right")
            if today_el:
                today_text = today_el.get_text(strip=True)
                # "123 stars today" or "456 stars this week"
                parts = today_text.replace(",", "").split()
                for part in parts:
                    if part.isdigit():
                        today_stars = int(part)
                        break

            # forks
            forks = 0
            for link in star_links:
                href = link.get("href", "")
                if href.endswith("/forks"):
                    fork_text = link.get_text(strip=True).replace(",", "")
                    try:
                        forks = int(fork_text)
                    except ValueError:
                        pass
                    break

            repos.append({
                "full_name": full_name,
                "html_url": f"https://github.com/{full_name}",
                "description": description,
                "language": language_name,
                "stars": stars,
                "stars_growth": today_stars,
                "forks": forks,
                "source": f"trending_{since}",
            })
        except Exception as e:
            print(f"  [Warning] Parse error for trending item: {e}")
            continue

    return repos


def fetch_all_trending():
    """抓取多个维度的 Trending 数据"""
    all_repos = []
    seen = set()

    # 所有语言 - weekly（本周升星最快，最符合需求）
    print("  Fetching trending (weekly, all languages)...")
    for repo in fetch_trending(since="weekly"):
        if repo["full_name"] not in seen:
            all_repos.append(repo)
            seen.add(repo["full_name"])

    # 所有语言 - daily（今日升星最快）
    print("  Fetching trending (daily, all languages)...")
    for repo in fetch_trending(since="daily"):
        if repo["full_name"] not in seen:
            all_repos.append(repo)
            seen.add(repo["full_name"])

    # Python - weekly（AI 项目多为 Python）
    print("  Fetching trending (weekly, Python)...")
    for repo in fetch_trending(since="weekly", language="python"):
        if repo["full_name"] not in seen:
            all_repos.append(repo)
            seen.add(repo["full_name"])

    # Python - daily
    print("  Fetching trending (daily, Python)...")
    for repo in fetch_trending(since="daily", language="python"):
        if repo["full_name"] not in seen:
            all_repos.append(repo)
            seen.add(repo["full_name"])

    # TypeScript - daily
    print("  Fetching trending (daily, TypeScript)...")
    for repo in fetch_trending(since="daily", language="typescript"):
        if repo["full_name"] not in seen:
            all_repos.append(repo)
            seen.add(repo["full_name"])

    return all_repos


def fetch_trending_fallback():
    """
    当 Trending 页面不可达时的降级方案：
    使用 Search API 查找近期活跃的热门 AI 项目（高 star + 近期更新）。
    """
    print("  [Fallback] Trending 页面不可达，使用 API 查找活跃热门项目...")
    date_since = (datetime.date.today() - datetime.timedelta(days=7)).strftime("%Y-%m-%d")

    # 查询近期活跃的高 star AI 项目
    queries = [
        ("ai OR llm OR agent stars:>1000 pushed:>" + date_since, "active_ai"),
        ("stable-diffusion OR midjourney OR comfyui stars:>500 pushed:>" + date_since, "active_aigc"),
    ]

    all_repos = []
    for query, tag in queries:
        url = "https://api.github.com/search/repositories"
        params = {
            "q": f"{query} sort:stars-desc",
            "sort": "stars",
            "order": "desc",
            "per_page": 15,
        }

        try:
            resp = requests.get(url, params=params, headers=GITHUB_API_HEADERS,
                                timeout=REQUEST_TIMEOUT)
            if resp.status_code == 403:
                print(f"  [Warning] Rate limited. Waiting 30s...")
                time.sleep(30)
                resp = requests.get(url, params=params, headers=GITHUB_API_HEADERS,
                                    timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
        except requests.RequestException as e:
            print(f"  [Warning] Fallback search failed ({tag}): {e}")
            continue

        data = resp.json()
        for item in data.get("items", []):
            all_repos.append({
                "full_name": item["full_name"],
                "html_url": item["html_url"],
                "description": item.get("description", "") or "",
                "language": item.get("language", "") or "",
                "stars": item.get("stargazers_count", 0),
                "stars_growth": 0,
                "forks": item.get("forks_count", 0),
                "topics": item.get("topics", []),
                "created_at": item.get("created_at", ""),
                "updated_at": item.get("updated_at", ""),
                "source": "trending_api_fallback",
            })

        time.sleep(7)  # 尊重 rate limit

    return all_repos


# ============================================================
# 数据采集：GitHub Search API
# ============================================================

def search_repositories(topic, category, label, days=7, per_page=10):
    """
    使用 GitHub Search API 搜索近期活跃的高星 AI 项目。
    不限制创建时间，而是搜索近期有 push 且 star 较高的项目，
    通过历史数据计算 star 增长量来反映"升星速度"。
    """
    date_since = (datetime.date.today() - datetime.timedelta(days=days)).strftime("%Y-%m-%d")
    query = f"topic:{topic} stars:>500 pushed:>{date_since} sort:stars-desc"

    url = "https://api.github.com/search/repositories"
    params = {
        "q": query,
        "sort": "stars",
        "order": "desc",
        "per_page": per_page,
    }

    try:
        resp = requests.get(url, params=params, headers=GITHUB_API_HEADERS,
                            timeout=REQUEST_TIMEOUT)
        if resp.status_code == 403:
            print(f"  [Warning] Rate limited on search API. Waiting 30s...")
            time.sleep(30)
            resp = requests.get(url, params=params, headers=GITHUB_API_HEADERS,
                                timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"  [Warning] Search API failed for topic '{topic}': {e}")
        return []

    data = resp.json()
    repos = []
    for item in data.get("items", []):
        repos.append({
            "full_name": item["full_name"],
            "html_url": item["html_url"],
            "description": item.get("description", "") or "",
            "language": item.get("language", "") or "",
            "stars": item.get("stargazers_count", 0),
            "stars_growth": 0,
            "forks": item.get("forks_count", 0),
            "topics": item.get("topics", []),
            "created_at": item.get("created_at", ""),
            "updated_at": item.get("updated_at", ""),
            "source": f"search:{label}",
            "category_hint": category,
        })

    return repos


def search_ai_repos_by_keywords(days=7, per_page=10):
    """
    使用关键词搜索（不只是 topic），覆盖面更广。
    搜索 name 和 description 中包含 AI 关键词的项目。
    """
    date_since = (datetime.date.today() - datetime.timedelta(days=days)).strftime("%Y-%m-%d")
    # 搜索名称/描述中包含 AI 相关词的高星项目
    queries = [
        ("ai OR llm OR chatgpt OR agent in:name,description", "general_ai"),
        ("AI agent in:name,description", "agent"),
        ("LLM in:name,description", "llm_name"),
    ]

    all_repos = []
    for query, tag in queries:
        url = "https://api.github.com/search/repositories"
        params = {
            "q": f"{query} stars:>100 pushed:>{date_since} sort:stars-desc",
            "sort": "stars",
            "order": "desc",
            "per_page": per_page,
        }

        try:
            resp = requests.get(url, params=params, headers=GITHUB_API_HEADERS,
                                timeout=REQUEST_TIMEOUT)
            if resp.status_code == 403:
                print(f"  [Warning] Rate limited. Waiting 30s...")
                time.sleep(30)
                resp = requests.get(url, params=params, headers=GITHUB_API_HEADERS,
                                    timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
        except requests.RequestException as e:
            print(f"  [Warning] Keyword search failed ({tag}): {e}")
            continue

        data = resp.json()
        for item in data.get("items", []):
            all_repos.append({
                "full_name": item["full_name"],
                "html_url": item["html_url"],
                "description": item.get("description", "") or "",
                "language": item.get("language", "") or "",
                "stars": item.get("stargazers_count", 0),
                "stars_growth": 0,
                "forks": item.get("forks_count", 0),
                "topics": item.get("topics", []),
                "created_at": item.get("created_at", ""),
                "updated_at": item.get("updated_at", ""),
                "source": f"search_keyword:{tag}",
            })

    return all_repos


def fetch_all_search():
    """执行所有 Search API 查询"""
    all_repos = []

    print("  Searching by AI topics...")
    for topic, category, label in SEARCH_TOPICS:
        print(f"    - topic:{topic} ({label})")
        repos = search_repositories(topic, category, label, days=7, per_page=10)
        all_repos.extend(repos)
        time.sleep(7)  # 尊重 rate limit（无 Token 限制 10 次/分钟）

    print("  Searching by AI keywords...")
    repos = search_ai_repos_by_keywords(days=7, per_page=15)
    all_repos.extend(repos)

    return all_repos


# ============================================================
# AI 分类
# ============================================================

def classify_repo(repo):
    """根据项目名称、描述、话题判断 AI 分类"""
    text = " ".join([
        repo.get("full_name", ""),
        repo.get("description", ""),
        " ".join(repo.get("topics", [])),
    ]).lower()

    # 如果有 category_hint（来自 Search API），优先使用
    if "category_hint" in repo and repo["category_hint"]:
        return repo["category_hint"]

    scores = {}
    for cat_key, cat_info in CATEGORIES.items():
        score = 0
        for kw in cat_info["keywords"]:
            if kw in text:
                score += 1
        scores[cat_key] = score

    best_cat = max(scores, key=scores.get)
    if scores[best_cat] > 0:
        return best_cat

    # 检查是否是 AI 相关
    for kw in AI_GENERAL_KEYWORDS:
        if kw in text:
            return "llm_agent"  # 默认归类

    return None


def is_ai_related(repo):
    """判断项目是否与 AI 相关"""
    text = " ".join([
        repo.get("full_name", ""),
        repo.get("description", ""),
        " ".join(repo.get("topics", [])),
    ]).lower()

    for kw in AI_GENERAL_KEYWORDS:
        if kw in text:
            return True
    return False


# ============================================================
# 历史数据管理
# ============================================================

def load_history():
    """加载历史数据"""
    if HISTORY_FILE.exists():
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return {}
    return {}


def save_history(history):
    """保存历史数据，只保留最近 7 天"""
    cutoff = (datetime.date.today() - datetime.timedelta(days=8)).isoformat()
    history = {
        date: data for date, data in history.items()
        if date >= cutoff
    }

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)


def compute_star_growth(repos, history):
    """根据历史数据计算 star 增量（与7天内最早可用数据对比）"""
    today = datetime.date.today()

    # 收集最近7天的历史数据，取最早可用的一天作为基准
    prev_stars = {}
    for days_back in range(7, 0, -1):
        date_str = (today - datetime.timedelta(days=days_back)).isoformat()
        if date_str in history:
            for repo in history[date_str].get("repos", []):
                name = repo["full_name"]
                if name not in prev_stars:
                    prev_stars[name] = repo.get("stars", 0)

    for repo in repos:
        if repo["full_name"] in prev_stars:
            growth = max(0, repo["stars"] - prev_stars[repo["full_name"]])
            if repo.get("stars_growth", 0) == 0 or growth > repo.get("stars_growth", 0):
                repo["stars_growth"] = growth

    return repos


def update_history(repos, history):
    """更新今天的历史记录"""
    today = datetime.date.today().isoformat()
    # 只存储关键字段
    today_repos = [
        {
            "full_name": r["full_name"],
            "stars": r["stars"],
            "stars_growth": r.get("stars_growth", 0),
        }
        for r in repos
    ]
    history[today] = {"repos": today_repos, "count": len(today_repos)}
    save_history(history)


# ============================================================
# HTML 报告生成
# ============================================================

def format_stars(n):
    """格式化 star 数"""
    if n >= 10000:
        return f"{n/10000:.1f}w"
    elif n >= 1000:
        return f"{n/1000:.1f}k"
    return str(n)


def generate_html_report(all_repos, trending_repos, report_date):
    """生成 HTML 报告"""

    # 分类
    categorized = {"trending": [], "fast_rising": [], "llm_agent": [], "aigc": [], "ml_tools": []}

    # Trending 中的 AI 项目
    for repo in trending_repos:
        if is_ai_related(repo):
            cat = classify_repo(repo)
            repo["ai_category"] = cat or "llm_agent"
            categorized["trending"].append(repo)

    # 按分类归类所有 Search API 项目
    for repo in all_repos:
        cat = classify_repo(repo)
        if cat:
            repo["ai_category"] = cat
            if cat in categorized:
                categorized[cat].append(repo)
            # 升星最快：有 star 增量的项目优先；无增量数据时，高 star 活跃项目作为候补
            if repo.get("stars_growth", 0) > 0:
                categorized["fast_rising"].append(repo)
            elif repo.get("stars", 0) >= 1000:
                categorized["fast_rising"].append(repo)

    # 去重并排序
    for key in categorized:
        seen = set()
        unique = []
        for repo in categorized[key]:
            if repo["full_name"] not in seen:
                seen.add(repo["full_name"])
                unique.append(repo)
        if key == "fast_rising":
            # 升星最快：按 star 增量排序，增量相同按总 star
            unique.sort(key=lambda x: (x.get("stars_growth", 0), x.get("stars", 0)), reverse=True)
        else:
            unique.sort(key=lambda x: x.get("stars", 0), reverse=True)
        categorized[key] = unique[:20]  # 每类最多 20 个

    # 统计数据
    total_repos = sum(len(v) for v in categorized.values())
    all_stars = [r.get("stars", 0) for v in categorized.values() for r in v]
    avg_stars = sum(all_stars) / len(all_stars) if all_stars else 0

    # 语言分布
    lang_dist = {}
    for v in categorized.values():
        for r in v:
            lang = r.get("language", "Unknown") or "Unknown"
            lang_dist[lang] = lang_dist.get(lang, 0) + 1
    top_langs = sorted(lang_dist.items(), key=lambda x: x[1], reverse=True)[:8]

    # 构建 HTML
    html_parts = []

    # HTML head
    html_parts.append(f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>GitHub AI 热点日报 - {report_date}</title>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, "PingFang SC", "Microsoft YaHei", sans-serif;
    background: #f6f8fa;
    color: #1f2328;
    line-height: 1.6;
    padding: 20px;
  }}
  .container {{ max-width: 1200px; margin: 0 auto; }}

  /* 顶部概览 */
  .header {{
    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
    color: white;
    border-radius: 16px;
    padding: 32px;
    margin-bottom: 24px;
    box-shadow: 0 4px 12px rgba(102,126,234,0.2);
  }}
  .header h1 {{ font-size: 28px; margin-bottom: 8px; }}
  .header .date {{ font-size: 14px; opacity: 0.9; }}
  .stats-bar {{
    display: flex;
    gap: 32px;
    margin-top: 20px;
    flex-wrap: wrap;
  }}
  .stat-item {{
    background: rgba(255,255,255,0.15);
    border-radius: 12px;
    padding: 12px 20px;
    backdrop-filter: blur(4px);
  }}
  .stat-item .num {{ font-size: 24px; font-weight: 700; }}
  .stat-item .label {{ font-size: 12px; opacity: 0.85; }}

  /* 板块 */
  .section {{
    background: #ffffff;
    border-radius: 16px;
    padding: 24px;
    margin-bottom: 20px;
    box-shadow: 0 1px 3px rgba(0,0,0,0.06);
  }}
  .section-title {{
    font-size: 20px;
    font-weight: 700;
    margin-bottom: 16px;
    display: flex;
    align-items: center;
    gap: 8px;
  }}
  .section-title .count {{
    font-size: 13px;
    font-weight: 400;
    color: #656d76;
    background: #eaeef2;
    border-radius: 12px;
    padding: 2px 10px;
  }}

  /* 项目卡片 */
  .repo-grid {{
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(340px, 1fr));
    gap: 16px;
  }}
  .repo-card {{
    border: 1px solid #d0d7de;
    border-radius: 12px;
    padding: 16px;
    transition: box-shadow 0.2s, border-color 0.2s;
    background: #fff;
    display: flex;
    flex-direction: column;
  }}
  .repo-card:hover {{
    box-shadow: 0 4px 12px rgba(0,0,0,0.1);
    border-color: #0969da;
  }}
  .repo-card .name {{
    font-size: 15px;
    font-weight: 600;
    margin-bottom: 6px;
  }}
  .repo-card .name a {{
    color: #0969da;
    text-decoration: none;
  }}
  .repo-card .name a:hover {{ text-decoration: underline; }}
  .repo-card .desc {{
    font-size: 13px;
    color: #656d76;
    margin-bottom: 10px;
    display: -webkit-box;
    -webkit-line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
    min-height: 38px;
  }}
  .repo-card .meta {{
    display: flex;
    align-items: center;
    gap: 12px;
    font-size: 12px;
    color: #656d76;
    margin-top: auto;
    flex-wrap: wrap;
  }}
  .repo-card .meta .lang {{
    display: flex;
    align-items: center;
    gap: 4px;
  }}
  .repo-card .meta .lang-dot {{
    width: 10px;
    height: 10px;
    border-radius: 50%;
    display: inline-block;
  }}
  .repo-card .stars {{
    display: flex;
    align-items: center;
    gap: 4px;
    font-weight: 600;
    color: #1f2328;
  }}
  .repo-card .growth {{
    color: #1a7f37;
    font-size: 11px;
    font-weight: 600;
    background: #dafbe1;
    border-radius: 10px;
    padding: 1px 8px;
  }}
  .repo-card .source-tag {{
    font-size: 10px;
    color: #656d76;
    background: #f6f8fa;
    border-radius: 8px;
    padding: 1px 6px;
  }}
  .repo-card .topics {{
    display: flex;
    gap: 4px;
    flex-wrap: wrap;
    margin-bottom: 8px;
  }}
  .repo-card .topic {{
    font-size: 11px;
    color: #0969da;
    background: #ddf4ff;
    border-radius: 10px;
    padding: 1px 8px;
  }}

  /* 语言分布图 */
  .lang-chart {{
    display: flex;
    flex-direction: column;
    gap: 8px;
  }}
  .lang-bar {{
    display: flex;
    align-items: center;
    gap: 8px;
  }}
  .lang-bar .lang-name {{
    width: 100px;
    font-size: 13px;
    text-align: right;
  }}
  .lang-bar .bar-track {{
    flex: 1;
    background: #eaeef2;
    border-radius: 6px;
    height: 20px;
    overflow: hidden;
  }}
  .lang-bar .bar-fill {{
    height: 100%;
    border-radius: 6px;
    display: flex;
    align-items: center;
    padding-left: 8px;
    font-size: 11px;
    color: white;
    font-weight: 600;
  }}

  .footer {{
    text-align: center;
    color: #656d76;
    font-size: 12px;
    padding: 20px;
  }}

  @media (max-width: 600px) {{
    .repo-grid {{ grid-template-columns: 1fr; }}
    .stats-bar {{ gap: 12px; }}
  }}
</style>
</head>
<body>
<div class="container">
  <div class="header">
    <h1>🔥 GitHub AI 热点日报</h1>
    <div class="date">📅 {report_date} · 自动监控 · 数据来源：GitHub Trending + Search API</div>
    <div class="stats-bar">
      <div class="stat-item">
        <div class="num">{total_repos}</div>
        <div class="label">追踪项目</div>
      </div>
      <div class="stat-item">
        <div class="num">{len(categorized['trending'])}</div>
        <div class="label">Trending 热门</div>
      </div>
      <div class="stat-item">
        <div class="num">{len(categorized['fast_rising'])}</div>
        <div class="label">本周升星</div>
      </div>
      <div class="stat-item">
        <div class="num">{format_stars(int(avg_stars))}</div>
        <div class="label">平均 Star</div>
      </div>
    </div>
  </div>
""")

    # 各板块渲染
    sections = [
        ("trending", "🔥 Trending 热门", "GitHub Trending 本周/今日升星最快的 AI 项目"),
        ("fast_rising", "⚡ 本周升星最快", "近期 Star 增长最快的 AI 项目（基于历史数据增量）"),
        ("llm_agent", "🤖 LLM / Agent", "大语言模型、Agent 框架、RAG、提示工程"),
        ("aigc", "🎨 AIGC 生成式", "图像/视频/3D/音乐生成、Stable Diffusion 等"),
        ("ml_tools", "🔧 ML 工具 / 框架", "ML 框架、训练工具、推理引擎、向量数据库"),
    ]

    for key, title, subtitle in sections:
        repos = categorized[key]
        if not repos:
            continue

        html_parts.append(f"""
  <div class="section">
    <div class="section-title">
      {title}
      <span class="count">{len(repos)} 个项目</span>
    </div>
    <p style="font-size:13px;color:#656d76;margin-bottom:16px;">{subtitle}</p>
    <div class="repo-grid">
""")

        for repo in repos:
            name = repo.get("full_name", "")
            url = repo.get("html_url", "")
            desc = repo.get("description", "") or "暂无描述"
            lang = repo.get("language", "") or "Unknown"
            stars = repo.get("stars", 0)
            growth = repo.get("stars_growth", 0)
            source = repo.get("source", "")
            topics = repo.get("topics", [])

            # 语言颜色
            lang_colors = {
                "Python": "#3572A5", "TypeScript": "#3178c6", "JavaScript": "#f1e05a",
                "Rust": "#dea584", "Go": "#00ADD8", "C++": "#f34b7d",
                "Java": "#b07219", "Jupyter Notebook": "#DA5B0B",
                "Cuda": "#3A4E3A", "Shell": "#89e051", "C": "#555555",
            }
            lang_color = lang_colors.get(lang, "#8250df")

            # 话题标签
            topics_html = ""
            if topics:
                topics_html = '<div class="topics">' + "".join(
                    f'<span class="topic">{t}</span>' for t in topics[:4]
                ) + '</div>'

            growth_html = ""
            if growth > 0:
                growth_html = f'<span class="growth">+{format_stars(growth)} ⭐</span>'

            source_label = ""
            if "trending" in source:
                source_label = f'<span class="source-tag">Trending</span>'
            elif "search" in source:
                source_label = f'<span class="source-tag">Search</span>'

            html_parts.append(f"""      <div class="repo-card">
        <div class="name"><a href="{url}" target="_blank">{name}</a></div>
        <div class="desc">{desc}</div>
        {topics_html}
        <div class="meta">
          <span class="lang"><span class="lang-dot" style="background:{lang_color}"></span>{lang}</span>
          <span class="stars">⭐ {format_stars(stars)}</span>
          {growth_html}
          {source_label}
        </div>
      </div>
""")

        html_parts.append("    </div>\n  </div>\n")

    # 语言分布图
    if top_langs:
        max_count = top_langs[0][1]
        lang_colors = {
            "Python": "#3572A5", "TypeScript": "#3178c6", "JavaScript": "#f1e05a",
            "Rust": "#dea584", "Go": "#00ADD8", "C++": "#f34b7d",
            "Java": "#b07219", "Jupyter Notebook": "#DA5B0B",
            "Cuda": "#3A4E3A", "Shell": "#89e051", "C": "#555555",
            "Unknown": "#8250df",
        }

        html_parts.append("""
  <div class="section">
    <div class="section-title">📊 语言分布</div>
    <div class="lang-chart">
""")
        for lang, count in top_langs:
            pct = int(count / max_count * 100) if max_count > 0 else 0
            color = lang_colors.get(lang, "#8250df")
            html_parts.append(
                f'      <div class="lang-bar">\n'
                f'        <span class="lang-name">{lang}</span>\n'
                f'        <div class="bar-track">\n'
                f'          <div class="bar-fill" style="width:{pct}%;background:{color}">{count}</div>\n'
                f'        </div>\n'
                f'      </div>\n'
            )
        html_parts.append("    </div>\n  </div>\n")

    # Footer
    html_parts.append(f"""
  <div class="footer">
    <p>Generated by GitHub AI Monitor · {report_date}</p>
    <p>数据来源：GitHub Trending Page + GitHub Search API</p>
  </div>
</div>
</body>
</html>
""")

    return "".join(html_parts)


# ============================================================
# 主流程
# ============================================================

def main():
    print("=" * 60)
    print("  GitHub AI 热点监控")
    print(f"  日期: {datetime.date.today().isoformat()}")
    print("=" * 60)

    # 1. 加载历史数据
    print("\n[1/5] 加载历史数据...")
    history = load_history()
    print(f"  已加载 {len(history)} 天历史记录")

    # 2. 抓取 Trending 页面
    print("\n[2/5] 抓取 GitHub Trending 页面...")
    trending_repos = fetch_all_trending()
    if not trending_repos:
        print("  Trending 页面不可达，启用 API 降级方案...")
        trending_repos = fetch_trending_fallback()
    print(f"  共获取 {len(trending_repos)} 个 Trending 项目")

    # 3. 调用 Search API
    print("\n[3/5] 调用 GitHub Search API...")
    search_repos = fetch_all_search()
    print(f"  共获取 {len(search_repos)} 个 Search 项目")

    # 4. 合并去重、分类、计算增量
    print("\n[4/5] 数据处理...")
    all_repos = search_repos  # Search API 的项目
    # 给 trending 项目也分类
    for repo in trending_repos:
        repo["ai_category"] = classify_repo(repo) or "llm_agent"

    # 合并：trending 项目也加入 all_repos 用于历史追踪
    seen = set(r["full_name"] for r in all_repos)
    for repo in trending_repos:
        if repo["full_name"] not in seen:
            all_repos.append(repo)
            seen.add(repo["full_name"])

    # 计算 star 增量
    all_repos = compute_star_growth(all_repos, history)
    trending_repos = compute_star_growth(trending_repos, history)

    print(f"  合并去重后共 {len(all_repos)} 个项目")

    # 更新历史
    update_history(all_repos, history)
    print(f"  历史数据已更新")

    # 5. 生成报告
    print("\n[5/5] 生成 HTML 报告...")
    report_date = datetime.date.today().isoformat()
    html = generate_html_report(all_repos, trending_repos, report_date)

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    report_file = REPORTS_DIR / f"report_{report_date}.html"
    with open(report_file, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"\n✅ 报告已生成: {report_file}")
    print(f"   文件大小: {report_file.stat().st_size / 1024:.1f} KB")
    print("\n" + "=" * 60)
    print("  监控完成!")
    print("=" * 60)

    return str(report_file)


if __name__ == "__main__":
    report_path = main()
    # 输出报告路径供自动化使用
    print(f"\nREPORT_PATH={report_path}")
