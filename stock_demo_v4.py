# -*- coding: utf-8 -*-
"""
股票查詢器 V4 — 三大法人 + 買賣比例
  輸入股票（代號或名稱）→ 顯示「最近交易日」的：
    外資 / 投信 / 自營商 的買賣超
    三大法人合計買賣超
    三大法人「買進 : 賣出」比例
資料來源：證交所 T86（三大法人買賣超日報）、STOCK_DAY（取最近交易日）。
"""
import requests
import unicodedata
from datetime import datetime

LIST_URL = "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"
DAY_URL = "https://www.twse.com.tw/exchangeReport/STOCK_DAY"
T86_URL = "https://www.twse.com.tw/fund/T86"


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


def latest_trade_date(stock_id):
    """用 STOCK_DAY 找最近一個有交易的日期，回傳 (民國字串, 西元YYYYMMDD)。"""
    y, m = datetime.now().year, datetime.now().month
    for back in range(0, 2):                      # 本月沒有就看上個月
        yy, mm = (y, m) if back == 0 else (y - (m == 1), (m - 1) or 12)
        d = requests.get(DAY_URL, params={"response": "json",
                         "date": "%d%02d01" % (yy, mm), "stockNo": stock_id}, timeout=20).json()
        if d.get("stat") == "OK" and d["data"]:
            roc = d["data"][-1][0]                 # 例 "115/10/05"
            yr, mo, da = roc.split("/")
            return roc, "%d%s%s" % (int(yr) + 1911, mo, da)
    return None, None


def num(s):
    """把 '1,234' 轉成整數；空白或 '--' 當 0。"""
    s = s.strip().replace(",", "")
    return int(s) if s.lstrip("-").isdigit() else 0


def get_t86(stock_id, date_ad):
    """抓某日 T86，回傳該股票那一列（找不到回 None）。"""
    d = requests.get(T86_URL, params={"response": "json",
                     "date": date_ad, "selectType": "ALL"}, timeout=30).json()
    if d.get("stat") != "OK":
        return None
    for row in d.get("data", []):
        if row[0].strip() == stock_id:
            return row
    return None


def comma(n):
    return format(n, ",")


if __name__ == "__main__":
    print("載入股票清單中…")
    id2name, name2id = load_stock_list()

    key = input("請輸入股票代號或名稱（例 2330 或 台積電）：")
    code, name = find_code(key, id2name, name2id)
    if not code:
        print("找不到「%s」，請確認代號或名稱。" % key)
        raise SystemExit

    print("\n查詢三大法人資料中…")
    roc, date_ad = latest_trade_date(code)
    if not roc:
        print("查無交易資料。")
        raise SystemExit

    row = get_t86(code, date_ad)
    if row is None:
        print("%s 這天沒有三大法人資料（可能非上市或當天無資料）。" % roc)
        raise SystemExit

    # 三大法人各自買賣超（股）：正=買超，負=賣超
    foreign = num(row[4]) + num(row[7])            # 外資(含外資自營商)
    trust = num(row[10])                           # 投信
    dealer = num(row[11])                          # 自營商
    total = num(row[18])                           # 三大法人合計

    # 三大法人 買進 / 賣出 總量（算買賣比例）
    buy = sum(num(row[i]) for i in (2, 5, 8, 12, 15))
    sell = sum(num(row[i]) for i in (3, 6, 9, 13, 16))
    ratio = (buy / sell) if sell else 0
    buy_pct = (buy / (buy + sell) * 100) if (buy + sell) else 0

    def tag(n):                                    # 買超/賣超 標示
        return ("買超 +" + comma(n)) if n >= 0 else ("賣超 " + comma(n))

    print("\n%s（%s）  %s  三大法人買賣超（單位：股）" % (name, code, roc))
    print("-" * 44)
    print("外　資 ： %s" % tag(foreign))
    print("投　信 ： %s" % tag(trust))
    print("自營商 ： %s" % tag(dealer))
    print("-" * 44)
    print("三大法人合計 ： %s" % tag(total))
    print()
    print("買賣比例（三大法人）：")
    print("  買進 %s 股 ： 賣出 %s 股" % (comma(buy), comma(sell)))
    print("  買賣比 = %.2f : 1 （買進占 %.1f%%）" % (ratio, buy_pct))
