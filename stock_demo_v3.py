# -*- coding: utf-8 -*-
"""
股票查詢器 V3 — 可輸入代號或名稱 + 可選 6 種期間
  期間：1 當天 / 2 近三天 / 3 近一週 / 4 近一月 / 5 近一季 / 6 近一年
說明：證交所 STOCK_DAY 一次只回傳「一個月」，所以較長的期間會自動連抓多個月再合併。
"""
import time
import requests
import unicodedata
from datetime import datetime

LIST_URL = "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"
DAY_URL = "https://www.twse.com.tw/exchangeReport/STOCK_DAY"

# 期間代號 -> (名稱, 要取幾個交易日, 要連抓幾個月)
PERIODS = {
    "1": ("當天", 1, 2),
    "2": ("近三天", 3, 2),
    "3": ("近一週", 5, 2),
    "4": ("近一月", 22, 2),
    "5": ("近一季", 66, 4),
    "6": ("近一年", 252, 13),
}


def load_stock_list():
    """抓全部上市股票，建立 代號<->名稱 對照表。"""
    rows = requests.get(LIST_URL, timeout=20).json()
    id2name = {r["Code"]: r["Name"] for r in rows}
    name2id = {r["Name"]: r["Code"] for r in rows}
    return id2name, name2id


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


def month_params(n_months):
    """回傳最近 n_months 個月的日期參數（YYYYMMDD，每月第一天）。"""
    y, m = datetime.now().year, datetime.now().month
    out = []
    for i in range(n_months):
        yy, mm = y, m - i
        while mm <= 0:
            mm += 12
            yy -= 1
        out.append("%d%02d01" % (yy, mm))
    return out


def get_days(stock_id, n_months):
    """連抓最近 n_months 個月的每日資料，合併後依日期排序。"""
    all_rows = []
    for date in month_params(n_months):
        try:
            d = requests.get(DAY_URL, params={"response": "json", "date": date,
                                              "stockNo": stock_id}, timeout=20).json()
            if d.get("stat") == "OK":
                all_rows += d["data"]
        except Exception:
            pass
        time.sleep(0.3)   # 禮貌性間隔，避免被證交所擋
    uniq = {r[0]: r for r in all_rows}          # 以日期去重
    return [uniq[k] for k in sorted(uniq)]      # 依日期由舊到新


# ---- 讓中文(全形)與數字欄位對齊 ----
def disp_width(s):
    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in s)


def cell(s, width):
    return " " * max(width - disp_width(s), 0) + s


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
    label, n_days, n_months = PERIODS[choice]

    print("\n查詢中…（%s 需連抓約 %d 個月）" % (label, n_months))
    rows = get_days(code, n_months)
    rows = rows[-n_days:]                        # 取最後 N 個交易日
    if not rows:
        print("查無資料。")
        raise SystemExit

    print("\n%s（%s）— %s，共 %d 個交易日\n" % (name, code, label, len(rows)))
    headers = ["日期", "開盤", "最高", "最低", "收盤", "漲跌", "成交量"]
    widths = [11, 11, 11, 11, 11, 10, 15]
    print("".join(cell(h, w) for h, w in zip(headers, widths)))
    print("-" * sum(widths))
    for r in rows:
        vals = [r[0], r[3], r[4], r[5], r[6], r[7], r[1]]
        print("".join(cell(v, w) for v, w in zip(vals, widths)))

    last = rows[-1]
    print("\n最新一筆：%s 收盤 %s 元（漲跌 %s）" % (last[0], last[6], last[7]))
