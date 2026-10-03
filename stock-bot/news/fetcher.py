"""
News & Macro Data Fetcher
=========================
RSS 뉴스, 원자재 선물, 경제 지표 수집 (전부 무료)
"""

import time
import logging
from datetime import datetime, timezone
from typing import List, Dict, Optional
import feedparser
import yfinance as yf

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# RSS 뉴스 피드 (무료)
# ─────────────────────────────────────────────

RSS_FEEDS = {
    "reuters_business":   "https://feeds.reuters.com/reuters/businessNews",
    "reuters_tech":       "https://feeds.reuters.com/reuters/technologyNews",
    "cnbc_markets":       "https://search.cnbc.com/rs/search/combinedcombined/articleasset/rss?partnerId=wrss01&id=15839135",
    "yahoo_finance":      "https://finance.yahoo.com/news/rssindex",
    "investing_stocks":   "https://www.investing.com/rss/news_25.rss",
    "seeking_alpha":      "https://seekingalpha.com/feed.xml",
}

# ─────────────────────────────────────────────
# 원자재 / 선물 티커 (yfinance)
# ─────────────────────────────────────────────

COMMODITY_TICKERS = {
    "반도체지수(SOXX)": "SOXX",
    "나스닥선물(NQ)":   "NQ=F",
    "S&P500선물(ES)":  "ES=F",
    "금":              "GC=F",
    "원유(WTI)":       "CL=F",
    "천연가스":         "NG=F",
    "구리":            "HG=F",
    "달러인덱스(DXY)": "DX-Y.NYB",
    "10년물국채":       "^TNX",
    "VIX(공포지수)":   "^VIX",
    "DRAM대리지수(MU)": "MU",
    "AI인프라(SMH)":   "SMH",
}

# ─────────────────────────────────────────────
# 뉴스 수집
# ─────────────────────────────────────────────

def fetch_rss_news(max_per_feed: int = 8) -> List[Dict]:
    """
    주요 금융 RSS 피드에서 최신 뉴스 헤드라인 수집.
    반환: [{"source", "title", "summary", "url", "published"}]
    """
    articles = []
    for source, url in RSS_FEEDS.items():
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:max_per_feed]:
                articles.append({
                    "source":    source,
                    "title":     entry.get("title", ""),
                    "summary":   entry.get("summary", "")[:300],
                    "url":       entry.get("link", ""),
                    "published": entry.get("published", ""),
                })
        except Exception as e:
            logger.warning(f"[news] RSS 피드 실패 ({source}): {e}")
        time.sleep(0.3)
    logger.info(f"[news] RSS 뉴스 {len(articles)}건 수집")
    return articles


def fetch_stock_news(ticker: str, max_items: int = 5) -> List[Dict]:
    """yfinance를 통한 종목 뉴스 수집"""
    try:
        tk = yf.Ticker(ticker)
        news = tk.news or []
        return [
            {
                "source":  item.get("publisher", ""),
                "title":   item.get("title", ""),
                "summary": "",
                "url":     item.get("link", ""),
                "published": datetime.fromtimestamp(
                    item.get("providerPublishTime", 0), tz=timezone.utc
                ).strftime("%Y-%m-%d %H:%M UTC"),
            }
            for item in news[:max_items]
        ]
    except Exception as e:
        logger.warning(f"[news] {ticker} 뉴스 수집 실패: {e}")
        return []


# ─────────────────────────────────────────────
# 원자재·지수 현황
# ─────────────────────────────────────────────

def fetch_commodity_snapshot() -> Dict[str, Dict]:
    """
    원자재 및 주요 지수 현재가·등락률 수집.
    반환: {"금": {"price": 2350.5, "change_pct": 0.8, "ticker": "GC=F"}, ...}
    """
    result = {}
    for name, ticker in COMMODITY_TICKERS.items():
        try:
            tk   = yf.Ticker(ticker)
            info = tk.fast_info
            price  = getattr(info, "last_price", None) or getattr(info, "regularMarketPrice", None)
            prev   = getattr(info, "previous_close", None)
            chg    = ((price - prev) / prev * 100) if price and prev else None
            result[name] = {
                "ticker":     ticker,
                "price":      round(float(price), 4) if price else None,
                "change_pct": round(float(chg), 2) if chg is not None else None,
            }
        except Exception:
            result[name] = {"ticker": ticker, "price": None, "change_pct": None}
        time.sleep(0.2)
    return result


# ─────────────────────────────────────────────
# 종합 시장 스냅샷 (분석 모듈용)
# ─────────────────────────────────────────────

def fetch_market_snapshot() -> Dict:
    """
    뉴스 + 원자재 + 주요 지수를 한 번에 수집.
    반환: {"news": [...], "commodities": {...}, "timestamp": "..."}
    """
    logger.info("[news] 시장 스냅샷 수집 시작")
    news       = fetch_rss_news(max_per_feed=6)
    commodities = fetch_commodity_snapshot()
    return {
        "news":        news,
        "commodities": commodities,
        "timestamp":   datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
    }
