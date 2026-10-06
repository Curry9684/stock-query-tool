# -*- coding: utf-8 -*-
"""
股票查詢器 — Request function 實際執行示範（快速版：固定查台積電）
向證交所 STOCK_DAY 要資料：回傳本月每個交易日的開高低收與成交量。
"""
import requests
import unicodedata
from datetime import datetime


def get_stock(stock_id, date):
    """向證交所要某支股票、某個月的每日資料，回傳 list（每個交易日一列）。"""
    url = "https://www.twse.com.tw/exchangeReport/STOCK_DAY"
    params = {
        "response": "json",
        "date": date,          # YYYYMMDD，會回傳該「月」全部交易日
        "stockNo": stock_id,   # 股票代號，例 "2330" 台積電
    }
    res = requests.get(url, params=params)   # ← 送出請求 (Request)
    data = res.json()                        # ← 收到 JSON

    if data.get("stat") != "OK":
        raise ValueError("查詢失敗：" + str(data.get("stat")))
    return data["data"]


# ---- 讓中文(全形)與數字欄位對齊的小工具 ----
def disp_width(s):
    """中文/全形字算 2 格，其餘算 1 格。"""
    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in s)


def cell(s, width):
    """把字串靠右補到指定顯示寬度。"""
    return " " * max(width - disp_width(s), 0) + s


if __name__ == "__main__":
    STOCK = "2330"                              # 台積電
    today = datetime.now().strftime("%Y%m%d")   # 抓「這個月」的資料
    rows = get_stock(STOCK, today)

    print("股票代號：%s（台積電）  本月共 %d 個交易日\n" % (STOCK, len(rows)))
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
