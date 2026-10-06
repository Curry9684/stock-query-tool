# -*- coding: utf-8 -*-
"""
股票查詢器 V2 — 可輸入「股票代號」或「股票名稱」
  輸入 2330        → 當成代號查
  輸入 台積電 / 台積 → 自動對照出代號再查
欄位用全形寬度對齊，數字不會再排亂。
"""
import requests
import unicodedata
from datetime import datetime

LIST_URL = "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"  # 全部上市股票清單
DAY_URL = "https://www.twse.com.tw/exchangeReport/STOCK_DAY"              # 單一股票某月每日


def load_stock_list():
    """抓證交所全部上市股票，建立 代號<->名稱 對照表。"""
    rows = requests.get(LIST_URL, timeout=20).json()
    id2name = {r["Code"]: r["Name"] for r in rows}
    name2id = {r["Name"]: r["Code"] for r in rows}
    return id2name, name2id


def find_code(keyword, id2name, name2id):
    """把使用者輸入（代號或名稱）轉成股票代號。回傳 (代號, 名稱)。"""
    keyword = keyword.strip()
    if keyword.isdigit():                       # 輸入的是代號
        return keyword, id2name.get(keyword, "")
    if keyword in name2id:                       # 名稱完全符合
        return name2id[keyword], keyword
    for name, code in name2id.items():           # 名稱部分符合（例：輸入「台積」）
        if keyword in name:
            return code, name
    return None, None


def get_month(stock_id, date):
    """要某支股票、某個月的每日資料。"""
    params = {"response": "json", "date": date, "stockNo": stock_id}
    data = requests.get(DAY_URL, params=params, timeout=20).json()
    return data["data"] if data.get("stat") == "OK" else []


# ---- 讓中文(全形)與數字欄位對齊的小工具 ----
def disp_width(s):
    """中文/全形字算 2 格，其餘算 1 格。"""
    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in s)


def cell(s, width):
    """把字串靠右補到指定顯示寬度。"""
    return " " * max(width - disp_width(s), 0) + s


if __name__ == "__main__":
    print("載入股票清單中…")
    id2name, name2id = load_stock_list()

    key = input("請輸入股票代號或名稱（例 2330 或 台積電）：")
    code, name = find_code(key, id2name, name2id)
    if not code:
        print("找不到「%s」，請確認代號或名稱是否正確。" % key)
        raise SystemExit

    rows = get_month(code, datetime.now().strftime("%Y%m%d"))
    if not rows:
        print("查無本月資料（可能今天還沒收盤，或代號非上市股票）。")
        raise SystemExit

    print("\n%s（%s）本月共 %d 個交易日\n" % (name, code, len(rows)))
    headers = ["日期", "開盤", "最高", "最低", "收盤", "漲跌", "成交量"]
    widths = [11, 11, 11, 11, 11, 10, 15]
    print("".join(cell(h, w) for h, w in zip(headers, widths)))
    print("-" * sum(widths))
    for r in rows:
        # r = [日期, 成交股數, 成交金額, 開盤, 最高, 最低, 收盤, 漲跌, 成交筆數, 註記]
        vals = [r[0], r[3], r[4], r[5], r[6], r[7], r[1]]
        print("".join(cell(v, w) for v, w in zip(vals, widths)))

    last = rows[-1]
    print("\n最新一筆：%s 收盤 %s 元（漲跌 %s）" % (last[0], last[6], last[7]))
