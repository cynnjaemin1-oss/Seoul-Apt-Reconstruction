"""
서울 재건축 대시보드 - 실거래가 + 시세 자동 업데이트
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
MONTHS_BACK = 12

DISTRICT_CODES = {
    "강남구": "11680",
    "서초구": "11650",
    "송파구": "11710",
    "성동구": "11200",
    "용산구": "11140",
    "마포구": "11440",
    "노원구": "11350",
}

# ✅ 진단 결과 반영한 실제 API 아파트명
COMPLEX_SEARCH_NAMES = {
    "잠실장미":          {"include": ["장미1", "장미2"],       "exclude": []},
    "잠실우성1·2·3차":   {"include": ["우성아파트"],            "exclude": ["우성4차", "가락우성", "도곡우성"]},
    "올림픽선수기자촌":  {"include": ["올림픽선수"],            "exclude": []},
   "성수동아":          {"include": ["동아"],                  "exclude": ["동아그린", "서울숲리버그린동아", "신동아"]},
    "개포주공6·7단지":   {"include": ["개포주공6", "개포주공7"],"exclude": []},
    "서빙고 신동아":     {"include": ["서빙고신동아"],          "exclude": []},
    "도곡우성":          {"include": ["도곡우성"],              "exclude": []},
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
    district_code = DISTRICT_CODES.get(district)
    if not district_code:
        return []

    rule         = COMPLEX_SEARCH_NAMES.get(complex_name, {"include": [complex_name], "exclude": []})
    include_kw   = rule["include"]
    exclude_kw   = rule["exclude"]

    all_tx = []
    found_apt_names = set()
    now = datetime.now()

    for i in range(MONTHS_BACK):
        target = now - relativedelta(months=i)
        yyyymm = target.strftime("%Y%m")
        items  = fetch_transactions(district_code, yyyymm)
        time.sleep(0.3)

        for item in items:
            apt_name = str(item.get("aptNm", "")).strip()
            # include 키워드 중 하나라도 포함 AND exclude 키워드는 하나도 없어야 함
            if not any(k in apt_name for k in include_kw):
                continue
            if any(k in apt_name for k in exclude_kw):
                continue

            found_apt_names.add(apt_name)
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

    if found_apt_names:
        print(f"  📌 매칭된 아파트명: {', '.join(sorted(found_apt_names))}")

    return all_tx

def compute_price_by_size(all_tx, existing_price_by_size):
    # 평형별로 가장 최근 거래 1건만 추출
    size_latest = {}
    for tx in sorted(all_tx, key=lambda x: x["_sort_key"], reverse=True):
        s = tx["size"]
        if s not in size_latest:
            size_latest[s] = tx  # 최신순 정렬이므로 첫 번째가 최근 거래

    updated = []
    for entry in existing_price_by_size:
        size   = entry["size"]
        latest = size_latest.get(size)
        if latest:
            mid = latest["price"]
            updated.append({**entry, "mid": mid, "low": mid, "high": mid})
            print(f"     {size}: 최근거래 {mid}억 ({latest['date']})")
        else:
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

    today = datetime.now().strftime("%Y.%m")
    updated_count = 0

    for c in complexes:
        name     = c["name"]
        district = c["district"]
        print(f"\n[{name}] ({district}) 조회 중...")

        all_tx = get_all_tx_for_complex(name, district)

        if not all_tx:
            print(f"  ⚠️  최근 {MONTHS_BACK}개월 실거래 없음 (기존 유지)")
            continue

        sorted_tx = sorted(all_tx, key=lambda x: x["_sort_key"], reverse=True)
        c["recentTx"] = [
            {"date": tx["date"], "size": tx["size"], "floor": tx["floor"], "price": tx["price"]}
            for tx in sorted_tx[:TX_COUNT]
        ]

        print(f"  📊 시세 계산 ({len(all_tx)}건 기반):")
        c["priceBySize"]      = compute_price_by_size(all_tx, c["priceBySize"])
        c["priceLastUpdated"] = today
        updated_count += 1
        print(f"  ✅ 업데이트 완료")

    print(f"\n▶ 총 {updated_count}개 단지 업데이트 완료 ({datetime.now().strftime('%Y.%m.%d')})")
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(complexes, f, ensure_ascii=False, indent=2)
    print("▶ data.json 저장 완료")

if __name__ == "__main__":
    main()
