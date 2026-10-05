# 쇼피 자동화

한국 상품을 쇼피(동남아·대만·브라질)에 **무재고(주문 후 구매)** 방식으로 판매하기 위한 자동화 도구예요.

```
[수요 조사]  demand.py        웹 검색 → 국가별 팔리는 한국 상품 아이디어 + 근거
     ↓ (마음에 드는 상품을 골라 products.csv 에 원가·무게·이미지 입력)
[상품글]     run_pipeline.py  국가별 판매가 계산 → AI 번역·상품글 → 위험도 점검
     ↓ (결과 CSV 확인)
[업로드]     run_pipeline.py --live   쇼피 Open API 로 글로벌 상품 등록 → 국가별 샵에 게시
```

## 파일 구성

| 파일 | 역할 |
|---|---|
| `config.yaml` | 판매 국가, 수수료, 배송비, 마진, 발송 준비일수 설정 |
| `pricing.py` | 원가 + 배송비 + 수수료 + 마진 → 국가별 판매가 |
| `listing_ai.py` | Claude로 국가별 언어의 제목·설명·키워드 생성 + 판매 위험도(ok/caution/block) |
| `demand.py` | Claude 웹 검색으로 수요 조사 리포트 생성 |
| `shopee_api.py` | 쇼피 Open Platform v2 클라이언트 (서명, 토큰 갱신, 이미지·상품 등록) |
| `auth.py` | 최초 1회 쇼피 앱 인증 |
| `products.csv` | 올릴 상품 목록 (예시 1줄 포함) |

## 준비물

1. **쇼피 Open Platform 앱 (partner_id, partner_key).** 셀러 계정 승인과는 별개예요. [open.shopee.com](https://open.shopee.com)에서 개발자 앱을 만들고 승인을 받아야 해요. 크로스보더 셀러는 쇼피코리아 담당자에게 API 사용을 문의하면 빨라요.
2. **Anthropic API 키** (`ANTHROPIC_API_KEY`). 상품글 생성과 수요 조사에 쓰여요.
3. **실제 요율.** `config.yaml`의 수수료·배송비는 **예시값**이에요. 쇼피코리아 요율표로 바꾼 뒤 `verified: true`로 바꿔야 업로드가 열려요.

## 사용법

```bash
pip install -r shopee/requirements.txt
export ANTHROPIC_API_KEY=...

# 1. 수요 조사
python -m shopee.demand --markets SG,MY,TW --category "beauty, snacks"

# 2. 미리보기 (업로드 없음) → shopee/output/listings_*.csv 확인
python -m shopee.run_pipeline

# 3. 쇼피 인증 (최초 1회)
export SHOPEE_PARTNER_ID=... SHOPEE_PARTNER_KEY=...
python -m shopee.auth url --redirect https://www.taein.io.kr
python -m shopee.auth token --code <code> --main-account-id <id>
python -m shopee.auth shops          # 연결된 국가별 샵 확인

# 4. 실제 업로드 — 처음엔 반드시 1개만
python -m shopee.run_pipeline --live --limit 1
```

## GitHub Actions

- `🛒 쇼피 수요 조사 (주간)`: 매주 월요일 자동 실행. 결과는 Actions 아티팩트로 남아요.
- `🛒 쇼피 상품글 미리보기`: 수동 실행. `products.csv`로 가격과 상품글을 만들어요.
- 저장소 Settings → Secrets 에 `ANTHROPIC_API_KEY`를 등록해야 해요.
- 실제 업로드는 아직 로컬에서만 실행해요. 쇼피 refresh_token이 갱신될 때마다 바뀌어서, Actions에서 쓰려면 새 토큰을 저장하는 장치가 더 필요해요.

## 안전장치

- `verified: false`인 동안 `--live`는 실행되지 않아요.
- 위험도 `block`(위조품·금지품 의심)은 업로드하지 않고, `caution`(화장품·식품·배터리 등)은 `--allow-caution`을 줄 때만 올려요.
- 무재고 운영이라 `pre_order`(예약판매)와 `days_to_ship`으로 국내 구매 시간을 확보해요. 국가마다 예약판매 허용 일수와 비율 제한이 있으니 셀러센터에서 확인하세요.

## 아직 확인이 필요한 부분

- 쇼피 API의 일부 필드(`category_recommend` 응답 형식, 카테고리별 필수 속성 `attribute_list`)는 실제 응답을 보고 맞춰야 해요. 그래서 첫 업로드는 `--limit 1`로 해요.
- 카테고리마다 필수 속성이 있으면 등록이 실패해요. 이때 오류 메시지를 보고 속성 자동 채우기를 추가하면 돼요.
