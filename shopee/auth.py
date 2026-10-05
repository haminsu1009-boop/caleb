"""최초 1회 인증 도구.

1) python -m shopee.auth url --redirect https://www.taein.io.kr
   → 출력된 URL을 브라우저로 열고 쇼피 메인계정으로 승인
2) 승인 후 주소창에 붙은 ?code=...&main_account_id=... 값을 복사
3) python -m shopee.auth token --code <code> --main-account-id <id>
   → shopee/.tokens.json 에 토큰 저장 (git 에 올라가지 않음)
"""
import argparse
import json

from .shopee_api import ShopeeClient


def main() -> None:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    u = sub.add_parser("url")
    u.add_argument("--redirect", required=True)
    t = sub.add_parser("token")
    t.add_argument("--code", required=True)
    t.add_argument("--main-account-id", required=True, type=int)
    sub.add_parser("shops")
    args = p.parse_args()

    client = ShopeeClient.from_env()
    if args.cmd == "url":
        print(client.auth_url(args.redirect))
    elif args.cmd == "token":
        data = client.get_token_by_code(args.code, args.main_account_id)
        print("토큰 저장 완료. merchant:", data.get("merchant_id_list"), "shops:", data.get("shop_id_list"))
    else:
        print(json.dumps(client.get_shops(), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
