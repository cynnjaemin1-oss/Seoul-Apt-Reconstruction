"""
서울 재건축 대시보드 - 실거래가 + 시세 자동 업데이트
- recentTx: 최근 3건
- priceBySize: 최근 12개월 실거래 기반 low/mid/high 자동 계산
"""

import json
import os
import time
import urllib.request
import urllib.parse
from datetime import datetime
from dateutil.relativedelta import relativedelta

API_KEY     = os.environ.get("MOLIT_API_KEY", "")
API_URL     = "http://apis.data.go.kr/1613000/RTMSDataSvcAptTradeDev/getRTMSDataSvcAptTradeDev"
DATA_FILE   = "data.json"
TX_COUNT    = 3
MONTHS_BACK = 12  # 시세 계산용으로 12개월 조회

DISTRICT_CODES = {
    "강남구": "11680",
    "서초구": "11650",
    "송파구": "11710",
    "성동구": "11200",
    "용산구": "11140",
    "마포구": "11440",
    "노원구": "11350",
}

COMPLEX_SEARCH_NAMES = {
    "잠실장미":          ["잠실장미"],
    "잠실우성1·2·3차":   ["잠실우성1차", "잠실우성2차", "잠실우성3차"],
    "올림픽선수기자촌":  ["올림픽선수기자촌"],
    "잠실우성4차":       ["잠실우성4차"],
    "성수동아":          ["성수동아"],
    "개포주공6·7단지":   ["개포주공6단지", "개포주공7단지"],
    "서빙고 신동아":     ["서빙고신동아"],
    "도곡우성":          ["도곡우성"],
}

def classify_floor(floor_val):
    try:
        floor = int(floor_val)
        if floor >= 15: return "고층"
        if floor >= 8:  return "중층"
        return "저층"
    except:
        return "중층"

def area_to_size_label(area_val):
    try:
        area = float(area_val)
        if area < 50:  return "42㎡"
        if area < 70:  return "59㎡"
        if area < 100: return "84㎡"
        if area < 120: return "105㎡"
        return "126㎡"
    except:
        return "84㎡"

def fetch_transactions(district_code, yyyymm):
    encoded_key = urllib.parse.quote(API_KEY, safe='')
    params = urllib.parse.urlencode({
        "LAWD_CD":   district_code,
        "DEAL_YMD":  yyyymm,
        "numOfRows": 1000,
        "pageNo":    1,
        "_type":     "json",
    })
    full_url = f"{API_URL}?serviceKey={encoded_key}&{params}"
    try:
        with urllib.request.urlopen(full_url, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        items = data.get("response", {}).get("body", {}).get("items", {})
        if not items:
            return []
        item = items.get("item", [])
        if isinstance(item, dict):
            item = [item]
        return item
    except Exception as e:
        print(f"  ⚠️  API 호출 실패 ({district_code}, {yyyymm}): {e}")
        return []

def get_all_tx_for_complex(complex_name, district):
    """최근 12개월 전체 실거래 반환"""
    district_code = DISTRICT_CODES.get(district)
    if not district_code:
        return []

    search_names = COMPLEX_SEARCH_NAMES.get(complex_name, [complex_name])
    all_tx = []
    now = datetime.now()

    for i in range(MONTHS_BACK):
        target = now - relativedelta(months=i)
        yyyymm = target.strftime("%Y%m")
        items  = fetch_transactions(district_code, yyyymm)
        time.sleep(0.3)

        for item in items:
            apt_name = str(item.get("aptNm", "")).strip()
            if any(s in apt_name for s in search_names):
                year  = str(item.get("dealYear",  "")).strip()
                month = str(item.get("dealMonth", "")).strip().zfill(2)
                price_raw = str(item.get("dealAmount", "0")).replace(",", "").strip()
                try:
                    price_eok = round(int(price_raw) / 10000, 1)
                except:
                    continue

                all_tx.append({
                    "date":      f"{year}.{month}",
                    "size":      area_to_size_label(item.get("excluUseAr", 84)),
                    "floor":     classify_floor(item.get("floor", 10)),
                    "price":     price_eok,
                    "_sort_key": f"{year}{month}",
                })

    return all_tx

def compute_price_by_size(all_tx, existing_price_by_size):
    """실거래 데이터로 평형별 low/mid/high 계산"""
    size_prices = {}
    for tx in all_tx:
        s = tx["size"]
        if s not in size_prices:
            size_prices[s] = []
        size_prices[s].append(tx["price"])

    updated = []
    for entry in existing_price_by_size:
        size = entry["size"]
        prices = size_prices.get(size, [])

        if len(prices) >= 2:
            prices_sorted = sorted(prices)
            low  = round(prices_sorted[0], 1)
            high = round(prices_sorted[-1], 1)
            mid  = round(sum(prices) / len(prices), 1)
            updated.append({**entry, "low": low, "mid": mid, "high": high})
            print(f"     {size}: {low}~{mid}~{high}억 ({len(prices)}건 기반)")
        elif len(prices) == 1:
            # 거래 1건이면 mid만 업데이트
            mid = prices[0]
            updated.append({**entry, "mid": mid})
            print(f"     {size}: 거래 1건 → mid {mid}억만 업데이트")
        else:
            # 거래 없으면 기존 유지
            updated.append(entry)
            print(f"     {size}: 실거래 없음 → 기존 유지")

    return updated

def main():
    if not API_KEY:
        print("❌ MOLIT_API_KEY 환경변수가 없습니다.")
        return

    print("▶ data.json 로드 중...")
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        complexes = json.load(f)

    today      = datetime.now().strftime("%Y.%m")
    updated_count = 0

    for c in complexes:
        name     = c["name"]
        district = c["district"]
        print(f"\n[{name}] ({district}) 조회 중...")

        all_tx = get_all_tx_for_complex(name, district)

        if not all_tx:
            print(f"  ⚠️  최근 {MONTHS_BACK}개월 실거래 없음 (기존 유지)")
            continue

        # 최근 실거래 3건
        sorted_tx = sorted(all_tx, key=lambda x: x["_sort_key"], reverse=True)
        c["recentTx"] = [
            {"date": tx["date"], "size": tx["size"], "floor": tx["floor"], "price": tx["price"]}
            for tx in sorted_tx[:TX_COUNT]
        ]

        # 평형별 시세 계산
        print(f"  📊 시세 계산 ({len(all_tx)}건 기반):")
        c["priceBySize"]      = compute_price_by_size(all_tx, c["priceBySize"])
        c["priceLastUpdated"] = today

        updated_count += 1
        print(f"  ✅ 업데이트 완료")
        for tx in c["recentTx"]:
            print(f"     최근거래: {tx['date']} | {tx['size']} | {tx['floor']} | {tx['price']}억")

    print(f"\n▶ 총 {updated_count}개 단지 업데이트 완료 ({datetime.now().strftime('%Y.%m.%d')})")

    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(complexes, f, ensure_ascii=False, indent=2)

    print("▶ data.json 저장 완료")

if __name__ == "__main__":
    main()
