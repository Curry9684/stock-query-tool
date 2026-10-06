# -*- coding: utf-8 -*-
"""
股票查詢器 V5 — 三大法人（依選擇的期間）
  輸入股票（代號或名稱）→ 選期間 1~6 → 顯示該期間內：
    外資 / 投信 / 自營商「各自」的 買超/賣超、買進、賣出、買占比例
    以及三大法人合計
正=買超、負=賣超。
資料來源：FinMind（一次就能取某股票一段期間的三大法人；數字與證交所 T86 一致）。
股票清單用證交所 OpenAPI 做「名稱 <-> 代號」對照。
"""
import requests
import unicodedata
from datetime import datetime, timedelta

LIST_URL = "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"
FINMIND_URL = "https://api.finmindtrade.com/api/v4/data"

# 期間代號 -> (名稱, 往前抓幾個日曆天, 取最後幾個交易日)
PERIODS = {
    "1": ("當天", 10, 1),
    "2": ("近三天", 16, 3),
    "3": ("近一週", 12, 5),
    "4": ("近一月", 45, 22),
    "5": ("近一季", 120, 66),
    "6": ("近一年", 400, 252),
}

# FinMind 法人名稱 -> 歸到哪一類（外資 / 投信 / 自營商）
GROUP = {
    "Foreign_Investor": "外資",
    "Foreign_Dealer_Self": "外資",
    "Investment_Trust": "投信",
    "Dealer_self": "自營商",
    "Dealer_Hedging": "自營商",
}


def load_stock_list():
    rows = requests.get(LIST_URL, timeout=20).json()
    return ({r["Code"]: r["Name"] for r in rows},
            {r["Name"]: r["Code"] for r in rows})


def find_code(keyword, id2name, name2id):
    keyword = keyword.strip()
    if keyword.isdigit():
        return keyword, id2name.get(keyword, "")
    if keyword in name2id:
        return name2id[keyword], keyword
    for name, code in name2id.items():
        if keyword in name:
            return code, name
    return None, None


def get_institution(stock_id, days_back):
    """抓某股票最近 days_back 天的三大法人買賣（FinMind），回傳 list。"""
    end = datetime.now().strftime("%Y-%m-%d")
    start = (datetime.now() - timedelta(days=days_back)).strftime("%Y-%m-%d")
    r = requests.get(FINMIND_URL, params={
        "dataset": "TaiwanStockInstitutionalInvestorsBuySell",
        "data_id": stock_id, "start_date": start, "end_date": end}, timeout=30)
    d = r.json()
    if d.get("status") != 200:
        return None
    return d.get("data", [])


# ---- 對齊工具 ----
def disp_width(s):
    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in s)


def cell(s, width):
    return " " * max(width - disp_width(s), 0) + s


def comma(n):
    return ("+" + format(n, ",")) if n > 0 else format(n, ",")


if __name__ == "__main__":
    print("載入股票清單中…")
    id2name, name2id = load_stock_list()

    key = input("請輸入股票代號或名稱（例 2330 或 台積電）：")
    code, name = find_code(key, id2name, name2id)
    if not code:
        print("找不到「%s」，請確認代號或名稱。" % key)
        raise SystemExit

    print("\n請選擇期間：")
    print("  1 當天   2 近三天   3 近一週   4 近一月   5 近一季   6 近一年")
    choice = input("輸入 1~6：").strip()
    if choice not in PERIODS:
        print("請輸入 1 到 6。")
        raise SystemExit
    label, days_back, keep_n = PERIODS[choice]

    print("\n查詢中…")
    data = get_institution(code, days_back)
    if not data:
        print("查無資料（可能超過 FinMind 免費額度，稍後再試；或該股無法人資料）。")
        raise SystemExit

    # 取最後 keep_n 個交易日
    dates = sorted(set(x["date"] for x in data))
    picked = set(dates[-keep_n:])
    data = [x for x in data if x["date"] in picked]
    days = sorted(picked)

    # 累計每一類法人的買進、賣出
    acc = {"外資": [0, 0], "投信": [0, 0], "自營商": [0, 0]}   # [買, 賣]
    for x in data:
        g = GROUP.get(x["name"])
        if g:
            acc[g][0] += x["buy"]
            acc[g][1] += x["sell"]

    print("\n%s（%s）— %s（%s ~ %s，共 %d 個交易日）" %
          (name, code, label, days[0], days[-1], len(days)))
    print("單位：股；正=買超、負=賣超\n")

    heads = ["法人", "買賣超(淨)", "買進", "賣出", "買占%"]
    w = [8, 15, 14, 14, 9]
    print("".join(cell(h, x) for h, x in zip(heads, w)))
    print("-" * sum(w))

    tb = ts = 0
    for g in ["外資", "投信", "自營商"]:
        buy, sell = acc[g]
        net = buy - sell
        pct = (buy / (buy + sell) * 100) if (buy + sell) else 0
        tb += buy
        ts += sell
        print("".join(cell(v, x) for v, x in zip(
            [g, comma(net), format(buy, ","), format(sell, ","), "%.1f%%" % pct], w)))

    print("-" * sum(w))
    tnet = tb - ts
    tpct = (tb / (tb + ts) * 100) if (tb + ts) else 0
    print("".join(cell(v, x) for v, x in zip(
        ["三大法人", comma(tnet), format(tb, ","), format(ts, ","), "%.1f%%" % tpct], w)))
