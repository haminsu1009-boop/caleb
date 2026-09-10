"""
KIS API (한국투자증권)
====================
한국투자증권 KIS Developers API 래퍼
실시간 주가·잔고·주문 조회/발주
https://apiportal.koreainvestment.com/
"""

import os
import time
import json
import logging
import requests
from datetime import datetime, timedelta
from typing import Dict, Optional, Tuple

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# KIS REST 엔드포인트
# ─────────────────────────────────────────────
KIS_BASE_REAL  = "https://openapi.koreainvestment.com:9443"
KIS_BASE_MOCK  = "https://openapivts.koreainvestment.com:29443"   # 모의 투자


class KISClient:
    """한국투자증권 REST API 클라이언트"""

    def __init__(
        self,
        app_key: str  = "",
        app_secret: str = "",
        account_no: str = "",
        account_suffix: str = "01",
        mock: bool = True,          # True = 모의투자, False = 실투자
    ):
        self.app_key        = app_key or os.getenv("KIS_APP_KEY", "")
        self.app_secret     = app_secret or os.getenv("KIS_APP_SECRET", "")
        self.account_no     = account_no or os.getenv("KIS_ACCOUNT_NO", "")
        self.account_suffix = account_suffix or os.getenv("KIS_ACCOUNT_SUFFIX", "01")
        self.mock           = mock
        self.base_url       = KIS_BASE_MOCK if mock else KIS_BASE_REAL

        self._access_token: Optional[str] = None
        self._token_expires: float = 0.0

    # ─────────────────────────────────────────
    # 인증 토큰
    # ─────────────────────────────────────────

    def _get_token(self) -> str:
        """액세스 토큰 발급 (만료 시 자동 갱신)"""
        if self._access_token and time.time() < self._token_expires - 60:
            return self._access_token

        url = f"{self.base_url}/oauth2/tokenP"
        body = {
            "grant_type": "client_credentials",
            "appkey":     self.app_key,
            "appsecret":  self.app_secret,
        }
        resp = requests.post(url, json=body, timeout=10)
        resp.raise_for_status()
        data = resp.json()

        self._access_token  = data["access_token"]
        expires_in          = int(data.get("expires_in", 86400))
        self._token_expires = time.time() + expires_in
        logger.info("[KIS] 토큰 발급 성공")
        return self._access_token

    def _headers(self, tr_id: str, extra: Dict = None) -> Dict:
        """공통 요청 헤더"""
        h = {
            "Content-Type":  "application/json; charset=utf-8",
            "Authorization": f"Bearer {self._get_token()}",
            "appkey":        self.app_key,
            "appsecret":     self.app_secret,
            "tr_id":         tr_id,
            "custtype":      "P",   # 개인
        }
        if extra:
            h.update(extra)
        return h

    # ─────────────────────────────────────────
    # 국내 현재가 조회
    # ─────────────────────────────────────────

    def get_domestic_price(self, symbol: str) -> Dict:
        """
        국내 주식 현재가 조회 (FHKST01010100).
        symbol: 6자리 종목코드 (예: "005930")
        """
        url    = f"{self.base_url}/uapi/domestic-stock/v1/quotations/inquire-price"
        tr_id  = "FHKST01010100"
        params = {
            "FID_COND_MRKT_DIV_CODE": "J",   # 주식
            "FID_INPUT_ISCD":          symbol,
        }
        try:
            resp = requests.get(url, headers=self._headers(tr_id), params=params, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            output = data.get("output", {})
            return {
                "symbol":        symbol,
                "current_price": float(output.get("stck_prpr", 0)),
                "open":          float(output.get("stck_oprc", 0)),
                "high":          float(output.get("stck_hgpr", 0)),
                "low":           float(output.get("stck_lwpr", 0)),
                "volume":        int(output.get("acml_vol", 0)),
                "change_rate":   float(output.get("prdy_ctrt", 0)),  # 전일 대비 등락률(%)
                "market_cap":    int(output.get("hts_avls", 0)),      # 시가총액(억원)
            }
        except Exception as e:
            logger.error(f"[KIS] 현재가 조회 실패 ({symbol}): {e}")
            return {}

    # ─────────────────────────────────────────
    # 국내 일별 OHLCV 조회
    # ─────────────────────────────────────────

    def get_domestic_ohlcv(self, symbol: str, start: str, end: str) -> list:
        """
        국내 주식 기간별 시세 (FHKST03010100).
        start/end: "YYYYMMDD"
        반환: [{"date": "YYYY-MM-DD", "open": ..., "high": ..., "low": ..., "close": ..., "volume": ...}, ...]
        """
        url    = f"{self.base_url}/uapi/domestic-stock/v1/quotations/inquire-daily-chartprice"
        tr_id  = "FHKST03010100"
        params = {
            "FID_COND_MRKT_DIV_CODE": "J",
            "FID_INPUT_ISCD":          symbol,
            "FID_INPUT_DATE_1":        start,
            "FID_INPUT_DATE_2":        end,
            "FID_PERIOD_DIV_CODE":     "D",   # 일봉
            "FID_ORG_ADJ_PRC":         "0",   # 수정주가
        }
        try:
            resp = requests.get(url, headers=self._headers(tr_id), params=params, timeout=10)
            resp.raise_for_status()
            rows = resp.json().get("output2", [])
            result = []
            for r in rows:
                result.append({
                    "date":   r.get("stck_bsop_date", ""),
                    "open":   float(r.get("stck_oprc", 0)),
                    "high":   float(r.get("stck_hgpr", 0)),
                    "low":    float(r.get("stck_lwpr", 0)),
                    "close":  float(r.get("stck_clpr", 0)),
                    "volume": int(r.get("acml_vol", 0)),
                })
            return result
        except Exception as e:
            logger.error(f"[KIS] OHLCV 조회 실패 ({symbol}): {e}")
            return []

    # ─────────────────────────────────────────
    # 잔고 조회
    # ─────────────────────────────────────────

    def get_balance(self) -> Dict:
        """
        주식 잔고 조회 (VTTC8434R: 모의 / TTTC8434R: 실거래).
        반환: {"total_eval": float, "holdings": [{"symbol", "name", "qty", "avg_price", "current_price", "pnl_pct"}]}
        """
        url   = f"{self.base_url}/uapi/domestic-stock/v1/trading/inquire-balance"
        tr_id = "VTTC8434R" if self.mock else "TTTC8434R"
        params = {
            "CANO":            self.account_no,
            "ACNT_PRDT_CD":    self.account_suffix,
            "AFHR_FLPR_YN":    "N",
            "OFL_YN":          "N",
            "INQR_DVSN":       "02",
            "UNPR_DVSN":       "01",
            "FUND_STTL_ICLD_YN":"N",
            "FNCG_AMT_AUTO_RDPT_YN":"N",
            "PRCS_DVSN":       "00",
            "CTX_AREA_FK100":  "",
            "CTX_AREA_NK100":  "",
        }
        try:
            resp = requests.get(url, headers=self._headers(tr_id), params=params, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            output1 = data.get("output1", [])
            output2 = data.get("output2", [{}])

            total = float(output2[0].get("tot_evlu_amt", 0)) if output2 else 0.0
            holdings = []
            for item in output1:
                qty = int(item.get("hldg_qty", 0))
                if qty == 0:
                    continue
                holdings.append({
                    "symbol":        item.get("pdno", ""),
                    "name":          item.get("prdt_name", ""),
                    "qty":           qty,
                    "avg_price":     float(item.get("pchs_avg_pric", 0)),
                    "current_price": float(item.get("prpr", 0)),
                    "pnl_pct":       float(item.get("evlu_pfls_rt", 0)),
                })
            return {"total_eval": total, "holdings": holdings}
        except Exception as e:
            logger.error(f"[KIS] 잔고 조회 실패: {e}")
            return {"total_eval": 0, "holdings": []}

    # ─────────────────────────────────────────
    # 주문 (매수/매도)
    # ─────────────────────────────────────────

    def order(self, symbol: str, side: str, qty: int, price: int = 0, order_type: str = "01") -> Dict:
        """
        국내 주식 주문.
        side: "buy" | "sell"
        order_type: "01" = 시장가, "00" = 지정가
        price: 지정가 주문 시 입력 (시장가 = 0)
        반환: {"success": bool, "order_no": str}
        """
        url = f"{self.base_url}/uapi/domestic-stock/v1/trading/order-cash"

        if side == "buy":
            tr_id = "VTTC0802U" if self.mock else "TTTC0802U"
        else:
            tr_id = "VTTC0801U" if self.mock else "TTTC0801U"

        body = {
            "CANO":         self.account_no,
            "ACNT_PRDT_CD": self.account_suffix,
            "PDNO":         symbol,
            "ORD_DVSN":     order_type,
            "ORD_QTY":      str(qty),
            "ORD_UNPR":     str(price),
        }

        try:
            resp = requests.post(url, headers=self._headers(tr_id), json=body, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            output = data.get("output", {})
            return {
                "success":  data.get("rt_cd") == "0",
                "order_no": output.get("ODNO", ""),
                "message":  data.get("msg1", ""),
            }
        except Exception as e:
            logger.error(f"[KIS] 주문 실패 ({symbol} {side}): {e}")
            return {"success": False, "order_no": "", "message": str(e)}


# ─────────────────────────────────────────────
# 유틸리티
# ─────────────────────────────────────────────

def symbol_from_yf_ticker(yf_ticker: str) -> str:
    """Yahoo Finance 티커 → KIS 종목코드 (예: "005930.KS" → "005930")"""
    return yf_ticker.split(".")[0]
