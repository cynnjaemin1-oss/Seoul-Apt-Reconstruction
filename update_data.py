"""
서울 재건축 대시보드 - 실거래가 자동 업데이트 스크립트
urllib 사용 (requests 인코딩 간섭 방지)
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
MONTHS_BACK = 6

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

def classify_floor(floor_str):
    try:
        floor = int(str(floor_str).strip())
        if floor >= 15: return "고층"
        if floor >= 8:  return "중층"
        return "저층"
    except:
        return "중층"

def area_to_size_label(area_str):
    try:
        area = float(str(area_str).strip())
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
        req = urllib.request.Request(full_url)
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw  = resp.read().decode("utf-8")
            data = json.loads(raw)

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

def get_recent_tx_for_complex(complex_name, district, n=TX_COUNT):
    district_code = DISTRICT_CODES.get(district)
    if not district_code:
        print(f"  ❌ 법정동 코드 없음: {district}")
        return None

    search_names = COMPLEX_SEARCH_NAMES.get(complex_name, [complex_name])
    all_tx = []
    now = datetime.now()

    for i in range(MONTHS_BACK):
        target = now - relativedelta(months=i)
        yyyymm = target.strftime("%Y%m")
        items  = fetch_transactions(district_code, yyyymm)
        time.sleep(0.3)

        for item in items:
            apt_name = str(item.get("아파트", "")).strip()
            if any(s in apt_name for s in search_names):
                year  = str(item.get("년", "")).strip()
                month = str(item.get("월", "")).strip().zfill(2)
                price_raw = str(item.get("거래금액", "0")).replace(",", "").strip()
                try:
                    price_eok = round(int(price_raw) / 10000, 1)
                except:
                    price_eok = 0

                all_tx.append({
                    "date":      f"{year}.{month}",
                    "size":      area_to_size_label(item.get("전용면적", "84")),
                    "floor":     classify_floor(item.get("층", "10")),
                    "price":     price_eok,
                    "_sort_key": f"{year}{month}",
                })

        if len(all_tx) >= n:
            break

    if not all_tx:
        return None

    all_tx.sort(key=lambda x: x["_sort_key"], reverse=True)
    return [{"date": tx["date"], "size": tx["size"], "floor": tx["floor"], "price": tx["price"]}
            for tx in all_tx[:n]]

def main():
    if not API_KEY:
        print("❌ MOLIT_API_KEY 환경변수가 없습니다.")
        return

    print("▶ data.json 로드 중...")
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        complexes = json.load(f)

    updated_count = 0

    for c in complexes:
        name     = c["name"]
        district = c["district"]
        print(f"\n[{name}] ({district}) 조회 중...")

        tx_list = get_recent_tx_for_complex(name, district)

        if tx_list:
            c["recentTx"] = tx_list
            updated_count += 1
            print(f"  ✅ {len(tx_list)}건 업데이트 완료")
            for tx in tx_list:
                print(f"     {tx['date']} | {tx['size']} | {tx['floor']} | {tx['price']}억")
        else:
            print(f"  ⚠️  실거래 데이터 없음 (기존 데이터 유지)")

    today = datetime.now().strftime("%Y.%m.%d")
    print(f"\n▶ 총 {updated_count}개 단지 업데이트 완료 ({today})")

    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(complexes, f, ensure_ascii=False, indent=2)

    print("▶ data.json 저장 완료")

if __name__ == "__main__":
    main()
