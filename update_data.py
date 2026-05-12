"""
서울 아파트 투자 대시보드 - 실거래가 자동 업데이트
재건축(complexes) + 일반매물(regularComplexes) + 내 집(myHome)
"""

import json, os, time, urllib.request, urllib.parse
from datetime import datetime
from dateutil.relativedelta import relativedelta

API_KEY     = os.environ.get("MOLIT_API_KEY", "")
API_URL     = "http://apis.data.go.kr/1613000/RTMSDataSvcAptTradeDev/getRTMSDataSvcAptTradeDev"
DATA_FILE   = "data.json"
TX_COUNT    = 3
MONTHS_BACK = 12

DISTRICT_CODES = {
    "강남구":"11680","서초구":"11650","송파구":"11710",
    "성동구":"11200","용산구":"11140","마포구":"11440","노원구":"11350",
}

# ── 재건축 단지 검색 규칙 ──────────────────────────────
RECON_SEARCH = {
    "잠실장미":         {"include":["장미1","장미2"],                  "exclude":[]},
    "잠실우성1·2·3차":  {"include":["우성아파트"],                     "exclude":["우성4차","가락우성","도곡우성"]},
    "올림픽선수기자촌": {"include":["올림픽선수"],                     "exclude":[]},
    "성수동아":         {"include":["동아"],                           "exclude":["동아그린","서울숲리버그린동아","신동아"]},
    "개포주공6·7단지":  {"include":["개포주공6","개포주공7"],          "exclude":[]},
    "서빙고 신동아":    {"include":["서빙고신동아"],                   "exclude":[]},
    "도곡우성":         {"include":["도곡우성"],                       "exclude":[]},
    "서초진흥":         {"include":["서초진흥"],                       "exclude":[]},
    "올림픽훼미리타운": {"include":["훼미리타운","훼밀리타운"],        "exclude":[]},
    "개포우성7차":      {"include":["우성7차"],                        "exclude":[]},
    "원효산호":         {"include":["산호"],                           "exclude":[]},
}

# ── 일반 매물 검색 규칙 ──────────────────────────────
# 공급면적 기준 평형 범위 지정으로 잘못된 거래 필터링
REGULAR_SEARCH = {
    "잠실엘스":         {"include":["잠실엘스"],         "exclude":[], "area_range":(40,135)},
    "리센츠":           {"include":["리센츠"],            "exclude":[], "area_range":(40,135)},
    "트리지움":         {"include":["트리지움"],          "exclude":[], "area_range":(40,120)},
    "레이크팰리스":     {"include":["레이크팰리스"],      "exclude":[], "area_range":(70,115)},
    "도곡렉슬":         {"include":["도곡렉슬"],          "exclude":[], "area_range":(40,135)},
    "역삼럭키":         {"include":["역삼럭키"],          "exclude":[], "area_range":(70,115)},
    "이촌한가람":       {"include":["한가람"],            "exclude":[], "area_range":(40,135)},
    "디에이치방배":     {"include":["디에이치방배"],      "exclude":[], "area_range":(40,120)},
    "개포자이프레지던스":{"include":["개포자이프레지던스"], "exclude":[], "area_range":(40,120)},
}

# 전용면적 → 평형 라벨 (재건축용)
def area_to_size_recon(area_val):
    try:
        a = float(area_val)
        if a < 50:  return "42㎡"
        if a < 70:  return "59㎡"
        if a < 100: return "84㎡"
        if a < 120: return "105㎡"
        return "126㎡"
    except: return "84㎡"

# 전용면적 → 평형 라벨 (일반매물용 — 120㎡ 버킷 포함)
def area_to_size_regular(area_val):
    try:
        a = float(area_val)
        if a < 50:  return "42㎡"
        if a < 70:  return "59㎡"
        if a < 100: return "84㎡"
        if a < 115: return "105㎡"
        if a < 130: return "114㎡"
        return "126㎡"
    except: return "84㎡"

def classify_floor(v):
    try:
        f = int(v)
        if f >= 15: return "고층"
        if f >= 8:  return "중층"
        return "저층"
    except: return "중층"

def fetch_transactions(district_code, yyyymm):
    encoded_key = urllib.parse.quote(API_KEY, safe='')
    params = urllib.parse.urlencode({
        "LAWD_CD": district_code, "DEAL_YMD": yyyymm,
        "numOfRows": 1000, "pageNo": 1, "_type": "json",
    })
    try:
        with urllib.request.urlopen(f"{API_URL}?serviceKey={encoded_key}&{params}", timeout=15) as r:
            data = json.loads(r.read().decode("utf-8"))
        items = data.get("response",{}).get("body",{}).get("items",{})
        if not items: return []
        item = items.get("item", [])
        return [item] if isinstance(item, dict) else item
    except Exception as e:
        print(f"  ⚠️  API 실패 ({district_code}, {yyyymm}): {e}")
        return []

def collect_tx(name, district, search_map, size_fn):
    dc = DISTRICT_CODES.get(district)
    if not dc: return []
    rule = search_map.get(name, {"include":[name],"exclude":[]})
    inc  = rule["include"]
    exc  = rule["exclude"]
    area_min, area_max = rule.get("area_range", (0, 9999))
    all_tx, found = [], set()
    now = datetime.now()
    for i in range(MONTHS_BACK):
        yyyymm = (now - relativedelta(months=i)).strftime("%Y%m")
        items = fetch_transactions(dc, yyyymm)
        time.sleep(0.3)
        for item in items:
            apt = str(item.get("aptNm","")).strip()
            if not any(k in apt for k in inc): continue
            if any(k in apt for k in exc):     continue
            area = float(item.get("excluUseAr", 0) or 0)
            if not (area_min <= area <= area_max): continue  # 면적 필터
            found.add(apt)
            year  = str(item.get("dealYear","")).strip()
            month = str(item.get("dealMonth","")).strip().zfill(2)
            price_raw = str(item.get("dealAmount","0")).replace(",","").strip()
            try: price_eok = round(int(price_raw)/10000, 1)
            except: continue
            all_tx.append({
                "date":      f"{year}.{month}",
                "size":      size_fn(area),
                "floor":     classify_floor(item.get("floor", 10)),
                "price":     price_eok,
                "_sort_key": f"{year}{month}",
                "_area":     area,
            })
    if found: print(f"  📌 {', '.join(sorted(found))}")
    return all_tx

def compute_price(all_tx, existing):
    """평형별 가장 최근 거래 1건으로 mid 업데이트"""
    size_latest = {}
    for tx in sorted(all_tx, key=lambda x: x["_sort_key"], reverse=True):
        if tx["size"] not in size_latest:
            size_latest[tx["size"]] = tx
    updated = []
    for entry in existing:
        s = entry["size"]
        latest = size_latest.get(s)
        if latest:
            updated.append({**entry, "mid": latest["price"], "low": latest["price"], "high": latest["price"]})
            print(f"     {s}({latest['_area']}㎡): {latest['price']}억 ({latest['date']})")
        else:
            updated.append(entry)
            print(f"     {s}: 실거래 없음 → 기존 유지")
    return updated

def update_list(complexes, search_map, size_fn, label):
    today, cnt = datetime.now().strftime("%Y.%m"), 0
    for c in complexes:
        print(f"\n[{label}] {c['name']} ({c['district']})")
        all_tx = collect_tx(c["name"], c["district"], search_map, size_fn)
        if not all_tx:
            print(f"  ⚠️  실거래 없음"); continue
        st = sorted(all_tx, key=lambda x: x["_sort_key"], reverse=True)
        c["recentTx"] = [{"date":t["date"],"size":t["size"],"floor":t["floor"],"price":t["price"]} for t in st[:TX_COUNT]]
        print(f"  📊 시세:")
        c["priceBySize"]      = compute_price(all_tx, c["priceBySize"])
        c["priceLastUpdated"] = today
        cnt += 1; print(f"  ✅ 완료")
    return cnt

def update_my_home(mh):
    dc = DISTRICT_CODES.get(mh["district"])
    sn = mh["searchName"]
    print(f"\n[내 집] {mh['name']}")
    now = datetime.now()
    for i in range(MONTHS_BACK):
        yyyymm = (now - relativedelta(months=i)).strftime("%Y%m")
        items = fetch_transactions(dc, yyyymm)
        time.sleep(0.3)
        matches = []
        for item in items:
            if sn not in str(item.get("aptNm","")): continue
            area = float(item.get("excluUseAr", 0) or 0)
            if not (55 <= area <= 75): continue
            try: p = round(int(str(item.get("dealAmount","0")).replace(",","")) / 10000, 1)
            except: continue
                try: p = round(int(str(item.get("dealAmount","0")).replace(",","")), 0)/10000
                except: continue
            year  = str(item.get("dealYear","")).strip()
            month = str(item.get("dealMonth","")).strip().zfill(2)
            matches.append({"price":p,"date":f"{year}.{month}","sortkey":f"{year}{month}"})
        if matches:
            latest = sorted(matches, key=lambda x: x["sortkey"], reverse=True)[0]
            mh["latestPrice"] = latest["price"]
            mh["latestDate"]  = latest["date"]
            print(f"  ✅ {latest['price']}억 ({latest['date']})")
            return mh
    print(f"  ⚠️  실거래 없음"); return mh

def main():
    if not API_KEY:
        print("❌ MOLIT_API_KEY 없음"); return
    print("▶ data.json 로드...")
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    n1 = update_list(data["complexes"],        RECON_SEARCH,   area_to_size_recon,    "재건축")
    n2 = update_list(data["regularComplexes"], REGULAR_SEARCH, area_to_size_regular,  "일반매물")
    data["myHome"] = update_my_home(data["myHome"])

    print(f"\n▶ 재건축 {n1}개 + 일반매물 {n2}개 완료 ({datetime.now().strftime('%Y.%m.%d')})")
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print("▶ 저장 완료")

if __name__ == "__main__":
    main()
