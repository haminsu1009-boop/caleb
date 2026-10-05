"""Shopee Open Platform v2 클라이언트 (크로스보더 셀러용 글로벌 상품 API 중심).

서명 원리: 요청마다 "누가(partner_id) + 어디에(path) + 언제(timestamp) + 어떤 권한으로
(access_token, shop_id/merchant_id)" 를 이어 붙인 문자열을 partner_key 로 HMAC-SHA256 한다.
서버는 같은 계산을 해 보고 결과가 같으면 진짜 요청으로 인정한다. 키 자체는 전송되지 않는다.

⚠️ 엔드포인트별 필드는 Shopee 문서 개정에 따라 바뀔 수 있다. 첫 실사용은
   `python -m shopee.run_pipeline --live --limit 1` 로 1개만 올려 응답을 확인할 것.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
from pathlib import Path
from urllib.parse import urlencode

import requests

LIVE_HOST = "https://partner.shopeemobile.com"
TEST_HOST = "https://partner.test-stable.shopeemobile.com"
DEFAULT_TOKEN_FILE = Path(__file__).parent / ".tokens.json"


class ShopeeError(RuntimeError):
    pass


def sign(partner_key: str, *parts: object) -> str:
    base = "".join(str(p) for p in parts)
    return hmac.new(partner_key.encode(), base.encode(), hashlib.sha256).hexdigest()


class TokenStore:
    """access_token(약 4시간)·refresh_token(약 30일)을 파일에 보관. 갱신 때마다 새 refresh_token 저장."""

    def __init__(self, path: Path):
        self.path = path

    def load(self) -> dict:
        return json.loads(self.path.read_text()) if self.path.exists() else {}

    def save(self, data: dict) -> None:
        self.path.write_text(json.dumps(data, indent=2))
        os.chmod(self.path, 0o600)


class ShopeeClient:
    def __init__(self, partner_id: int, partner_key: str, *, test: bool = False,
                 token_file: Path = DEFAULT_TOKEN_FILE):
        self.partner_id = int(partner_id)
        self.partner_key = partner_key
        self.host = TEST_HOST if test else LIVE_HOST
        self.tokens = TokenStore(token_file)

    @classmethod
    def from_env(cls) -> "ShopeeClient":
        try:
            pid, key = os.environ["SHOPEE_PARTNER_ID"], os.environ["SHOPEE_PARTNER_KEY"]
        except KeyError as e:
            raise ShopeeError(f"환경변수 {e.args[0]} 가 필요합니다") from None
        token_file = Path(os.environ.get("SHOPEE_TOKEN_FILE", DEFAULT_TOKEN_FILE))
        return cls(pid, key, test=os.environ.get("SHOPEE_TEST") == "1", token_file=token_file)

    # ── 인증 ──────────────────────────────────────────────
    def auth_url(self, redirect_url: str) -> str:
        """셀러가 브라우저로 열어 앱 권한을 승인하는 URL."""
        path = "/api/v2/shop/auth_partner"
        ts = int(time.time())
        query = urlencode({
            "partner_id": self.partner_id, "timestamp": ts,
            "sign": sign(self.partner_key, self.partner_id, path, ts),
            "redirect": redirect_url,
        })
        return f"{self.host}{path}?{query}"

    def _public_post(self, path: str, body: dict) -> dict:
        ts = int(time.time())
        query = {"partner_id": self.partner_id, "timestamp": ts,
                 "sign": sign(self.partner_key, self.partner_id, path, ts)}
        resp = requests.post(f"{self.host}{path}", params=query, json=body, timeout=30)
        return self._check(resp)

    def get_token_by_code(self, code: str, main_account_id: int) -> dict:
        """승인 후 redirect 로 받은 code 와 main_account_id 로 첫 토큰 발급 (크로스보더 메인계정)."""
        data = self._public_post("/api/v2/auth/token/get", {
            "code": code, "partner_id": self.partner_id, "main_account_id": int(main_account_id),
        })
        self._store_tokens(data, extra={
            "merchant_id": (data.get("merchant_id_list") or [None])[0],
            "shop_id_list": data.get("shop_id_list", []),
        })
        return data

    def refresh(self) -> dict:
        saved = self.tokens.load()
        if not saved.get("refresh_token"):
            raise ShopeeError("저장된 토큰이 없습니다. 먼저 python -m shopee.auth 로 인증하세요")
        body = {"refresh_token": saved["refresh_token"], "partner_id": self.partner_id}
        if saved.get("merchant_id"):
            body["merchant_id"] = int(saved["merchant_id"])
        else:
            body["shop_id"] = int(saved["shop_id_list"][0])
        data = self._public_post("/api/v2/auth/access_token/get", body)
        self._store_tokens(data)
        return data

    def _store_tokens(self, data: dict, extra: dict | None = None) -> None:
        saved = self.tokens.load()
        saved.update(extra or {})
        saved.update({
            "access_token": data["access_token"],
            "refresh_token": data["refresh_token"],
            "expire_at": int(time.time()) + int(data.get("expire_in", 14400)),
        })
        self.tokens.save(saved)

    def _access_token(self) -> str:
        saved = self.tokens.load()
        if not saved or saved.get("expire_at", 0) - 300 < time.time():
            self.refresh()
            saved = self.tokens.load()
        return saved["access_token"]

    # ── 공통 호출 ─────────────────────────────────────────
    def call(self, path: str, *, method: str = "GET", level: str = "shop",
             shop_id: int | None = None, params: dict | None = None,
             body: dict | None = None, files: dict | None = None) -> dict:
        """level='shop' 은 shop_id, level='merchant' 는 merchant_id 로 서명한다."""
        saved = self.tokens.load()
        token = self._access_token()
        ts = int(time.time())
        if level == "merchant":
            owner_key, owner_id = "merchant_id", int(saved["merchant_id"])
        else:
            owner_key, owner_id = "shop_id", int(shop_id or saved["shop_id_list"][0])
        query = {
            "partner_id": self.partner_id, "timestamp": ts, "access_token": token,
            owner_key: owner_id,
            "sign": sign(self.partner_key, self.partner_id, path, ts, token, owner_id),
            **(params or {}),
        }
        url = f"{self.host}{path}"
        if method == "GET":
            resp = requests.get(url, params=query, timeout=30)
        elif files:
            resp = requests.post(url, params=query, files=files, timeout=60)
        else:
            resp = requests.post(url, params=query, json=body or {}, timeout=30)
        return self._check(resp)

    @staticmethod
    def _check(resp: requests.Response) -> dict:
        try:
            data = resp.json()
        except ValueError:
            raise ShopeeError(f"HTTP {resp.status_code}: {resp.text[:300]}") from None
        if data.get("error"):
            raise ShopeeError(f"{data.get('error')}: {data.get('message')} (request_id={data.get('request_id')})")
        return data.get("response", data)

    # ── 상품 등록에 쓰는 API ───────────────────────────────
    def upload_image_from_url(self, image_url: str) -> str:
        img = requests.get(image_url, timeout=30)
        img.raise_for_status()
        data = self.call("/api/v2/media_space/upload_image", method="POST",
                         files={"image": ("image.jpg", img.content)})
        return data["image_info"]["image_id"]

    def recommend_category(self, item_name: str) -> int | None:
        data = self.call("/api/v2/global_product/category_recommend", level="merchant",
                         params={"global_item_name": item_name})
        ids = data.get("category_id") or data.get("category_id_list") or []
        return ids[0] if isinstance(ids, list) and ids else (ids or None)

    def add_global_item(self, body: dict) -> int:
        data = self.call("/api/v2/global_product/add_global_item", method="POST",
                         level="merchant", body=body)
        return data["global_item_id"]

    def publish(self, global_item_id: int, shop_id: int, region: str, item: dict) -> dict:
        return self.call("/api/v2/global_product/create_publish_task", method="POST",
                         level="merchant", body={
                             "global_item_id": global_item_id, "shop_id": shop_id,
                             "shop_region": region, "item": item,
                         })

    def get_shops(self) -> list[dict]:
        data = self.call("/api/v2/merchant/get_shop_list_by_merchant", level="merchant",
                         params={"page_no": 1, "page_size": 100})
        return data.get("shop_list", [])
