"""
Discount Hunter - probe kết nối tới 3 site siêu thị từ server nước ngoài.

Chạy 3 cách:
  1. GitHub Actions: push repo, tab Actions -> workflow "probe" -> xem log.
  2. Render free web service (region Singapore): deploy repo, mở URL, bấm nút.
  3. Trên PC để lấy baseline:  pip install httpx gradio  ->  python app.py --cli
"""
import json
import os
import re
import sys
import time
from urllib.parse import quote

import httpx

KEYWORD = "sữa tươi"
TIMEOUT = 25.0

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
BASE_HEADERS = {
    "User-Agent": UA,
    "Accept-Language": "vi-VN,vi;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
}

BLOCK_MARKERS = [
    "just a moment", "cf-chl", "cf_chl", "challenge-platform", "attention required",
    "datadome", "captcha-delivery", "access denied", "request blocked",
    "verify you are human", "ddos-guard", "incapsula", "perimeterx", "_pxhc",
]


def classify(status: int, text: str) -> str:
    low = (text or "")[:20000].lower()
    if status in (403, 429, 503) or any(m in low for m in BLOCK_MARKERS):
        return "BLOCKED"
    if status >= 400:
        return f"HTTP_{status}"
    return "OK"


def _result(site, url, status, text, elapsed, **extra):
    return {
        "site": site,
        "url": url,
        "status": status,
        "verdict": classify(status, text),
        "ms": int(elapsed * 1000),
        "bytes": len(text or ""),
        "snippet": (text or "")[:300].replace("\n", " "),
        **extra,
    }


def _get(client: httpx.Client, url: str, **kw):
    t0 = time.perf_counter()
    r = client.get(url, **kw)
    return r, time.perf_counter() - t0


# ---------------------------------------------------------------- Lotte Mart
def probe_lotte(client: httpx.Client) -> dict:
    url = f"https://www.lottemart.vn/v1/p/mart/es/vi_bdg/search?q={quote(KEYWORD)}&size=5"
    headers = {**BASE_HEADERS, "Accept": "application/json, text/plain, */*",
               "Referer": "https://www.lottemart.vn/vi-bdg"}
    try:
        r, dt = _get(client, url, headers=headers)
        extra = {}
        try:
            data = r.json()["data"]
            items = data.get("items", [])
            extra["total_items"] = data.get("total_items")
            if items:
                it = items[0]
                p = it.get("price", {}).get("VND", {})
                extra["first"] = {
                    "name": it.get("name"), "sku_ean": it.get("sku"),
                    "price": p.get("price"), "special_price": p.get("special_price"),
                    "special_to": p.get("special_to_date"), "in_stock": it.get("in_stock"),
                }
        except Exception as e:  # noqa: BLE001
            extra["parse_error"] = repr(e)
        return _result("Lotte Mart", url, r.status_code, r.text, dt, **extra)
    except Exception as e:  # noqa: BLE001
        return {"site": "Lotte Mart", "url": url, "verdict": "ERROR", "error": repr(e)}


# ---------------------------------------------------------------- GO!
def probe_go(client: httpx.Client) -> dict:
    home = "https://sieuthi-go.vn/"
    try:
        r0, dt0 = _get(client, home, headers=BASE_HEADERS)
        v0 = classify(r0.status_code, r0.text)
        m = re.search(r'"buildId":"([^"]+)"', r0.text)
        if v0 != "OK" or not m:
            return _result("GO! (home)", home, r0.status_code, r0.text, dt0,
                           note="không lấy được buildId" if v0 == "OK" else "")
        build_id = m.group(1)
        url = f"https://sieuthi-go.vn/_next/data/{build_id}/search.json?keyword={quote(KEYWORD)}"
        headers = {**BASE_HEADERS, "Accept": "*/*", "Referer": home, "x-nextjs-data": "1"}
        r, dt = _get(client, url, headers=headers)
        extra = {"build_id": build_id, "home_ms": int(dt0 * 1000)}
        try:
            prods = r.json()["pageProps"]["productsSeach"]
            extra["count"] = len(prods)
            if prods:
                p = prods[0]
                extra["first"] = {
                    "name": p.get("name"), "barcode": p.get("barcode"),
                    "price": p.get("price"), "promotion_price": p.get("promotion_price"),
                    "member_price": p.get("member_price"), "status": p.get("status"),
                }
        except Exception as e:  # noqa: BLE001
            extra["parse_error"] = repr(e)
        return _result("GO!", url, r.status_code, r.text, dt, **extra)
    except Exception as e:  # noqa: BLE001
        return {"site": "GO!", "url": home, "verdict": "ERROR", "error": repr(e)}


# ---------------------------------------------------------------- Bách Hóa Xanh
def probe_bhx(client: httpx.Client) -> dict:
    url = f"https://www.bachhoaxanh.com/tim-kiem?key={quote(KEYWORD)}"
    try:
        r, dt = _get(client, url, headers=BASE_HEADERS)
        html = r.text
        cards = html.count('class="box_product')
        titles = re.findall(r'product-code="(\d+)">\s*<a[^>]*title="([^"]+)"', html)
        prices = re.findall(r'(\d{1,3}(?:\.\d{3})+)đ', html)
        extra = {"product_cards": cards}
        if titles:
            extra["first"] = {"product_code": titles[0][0], "name": titles[0][1],
                              "first_price_seen": prices[0] if prices else None}
        return _result("Bách Hóa Xanh", url, r.status_code, html, dt, **extra)
    except Exception as e:  # noqa: BLE001
        return {"site": "Bách Hóa Xanh", "url": url, "verdict": "ERROR", "error": repr(e)}


# ---------------------------------------------------------------- where am I
def probe_ip(client: httpx.Client) -> dict:
    try:
        r = client.get("https://ipinfo.io/json", headers={"User-Agent": UA, "Accept": "application/json"})
        j = r.json()
        return {"ip": j.get("ip"), "country": j.get("country"), "region": j.get("region"),
                "city": j.get("city"), "org": j.get("org")}
    except Exception as e:  # noqa: BLE001
        return {"error": repr(e)}


def run_all() -> dict:
    with httpx.Client(timeout=TIMEOUT, follow_redirects=True, http2=False) as client:
        return {
            "origin": probe_ip(client),
            "keyword": KEYWORD,
            "results": [probe_lotte(client), probe_go(client), probe_bhx(client)],
        }


def to_markdown(out: dict) -> str:
    o = out["origin"]
    lines = [
        f"**Chạy từ:** `{o.get('ip')}` — {o.get('city')}, {o.get('region')}, {o.get('country')} — {o.get('org')}",
        "",
        "| Site | Verdict | HTTP | ms | Dữ liệu đọc được |",
        "|---|---|---|---|---|",
    ]
    for r in out["results"]:
        got = ""
        if "first" in r:
            got = json.dumps(r["first"], ensure_ascii=False)
        elif "error" in r:
            got = r["error"]
        elif "parse_error" in r:
            got = "parse_error: " + r["parse_error"]
        count = r.get("total_items", r.get("count", r.get("product_cards", "")))
        lines.append(f"| {r['site']} | **{r.get('verdict')}** | {r.get('status','')} | {r.get('ms','')} | "
                     f"n={count} {got} |")
    lines += ["", "Copy toàn bộ JSON bên dưới gửi lại để phân tích."]
    return "\n".join(lines)


def main_cli():
    out = run_all()
    print(to_markdown(out))
    print()
    print(json.dumps(out, ensure_ascii=False, indent=2))


def main_gradio():
    import gradio as gr

    def go():
        out = run_all()
        return to_markdown(out), out

    with gr.Blocks(title="Discount Hunter – probe") as demo:
        gr.Markdown("## Discount Hunter – kiểm tra kết nối tới Lotte Mart / GO! / Bách Hóa Xanh")
        btn = gr.Button("Chạy probe", variant="primary")
        md = gr.Markdown()
        js = gr.JSON(label="Kết quả chi tiết (copy gửi lại)")
        btn.click(go, outputs=[md, js])
    demo.launch(server_name="0.0.0.0", server_port=int(os.environ.get("PORT", 7860)))


if __name__ == "__main__":
    if "--cli" in sys.argv:
        main_cli()
    else:
        main_gradio()
