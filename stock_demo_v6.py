# -*- coding: utf-8 -*-
"""
股票查詢器 V6 — 產生「AI 分析用資料摘要」
  輸入股票（代號或名稱）→ 選期間 1~6 →
  同時抓「股價(V3)」與「三大法人(V5)」，整理成一份結構化的文字摘要，
  存成 .txt 並嘗試複製到剪貼簿，可直接貼給 AI（Claude / ChatGPT）做趨勢分析。

本版不呼叫任何 AI API，不需要金鑰、不需付費。
資料來源：證交所 STOCK_DAY、證交所 OpenAPI 股票清單、FinMind 三大法人。
"""
import os
import time
import subprocess
import requests
import unicodedata
from datetime import datetime, timedelta

LIST_URL = "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"
DAY_URL = "https://www.twse.com.tw/exchangeReport/STOCK_DAY"
FINMIND_URL = "https://api.finmindtrade.com/api/v4/data"

# 期間代號 -> (名稱, 取幾個交易日, 股價要連抓幾個月, 法人往前抓幾個日曆天)
PERIODS = {
    "1": ("當天", 1, 2, 10),
    "2": ("近三天", 3, 2, 16),
    "3": ("近一週", 5, 2, 12),
    "4": ("近一月", 22, 2, 45),
    "5": ("近一季", 66, 4, 120),
    "6": ("近一年", 252, 13, 400),
}

GROUP = {
    "Foreign_Investor": "外資",
    "Foreign_Dealer_Self": "外資",
    "Investment_Trust": "投信",
    "Dealer_self": "自營商",
    "Dealer_Hedging": "自營商",
}

MAX_ROWS = 40          # 明細表最多列出幾筆，避免貼給 AI 時太長


# ---------- 共用工具 ----------
def disp_width(s):
    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in s)


def cell(s, width):
    return " " * max(width - disp_width(s), 0) + s


def comma(n):
    return ("+" + format(n, ",")) if n > 0 else format(n, ",")


def roc_to_ad(d):
    """民國日期 '115/10/30' -> 西元 '2026-10-30'；轉不了就原樣回傳。"""
    try:
        y, m, dd = d.split("/")
        return "%d-%02d-%02d" % (int(y) + 1911, int(m), int(dd))
    except Exception:
        return d


def to_num(s):
    """把 '1,234.5' 轉成 float；'--' 或空值回傳 None。"""
    try:
        return float(str(s).replace(",", "").replace("+", ""))
    except ValueError:
        return None


# ---------- 抓資料（沿用 V3 / V5） ----------
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


def month_params(n_months):
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
    all_rows = []
    for date in month_params(n_months):
        try:
            d = requests.get(DAY_URL, params={"response": "json", "date": date,
                                              "stockNo": stock_id}, timeout=20).json()
            if d.get("stat") == "OK":
                all_rows += d["data"]
        except Exception:
            pass
        time.sleep(0.3)
    for r in all_rows:
        r[0] = roc_to_ad(r[0])          # 民國 -> 西元，與法人資料一致
    uniq = {r[0]: r for r in all_rows}
    return [uniq[k] for k in sorted(uniq)]


def get_institution(stock_id, days_back):
    end = datetime.now().strftime("%Y-%m-%d")
    start = (datetime.now() - timedelta(days=days_back)).strftime("%Y-%m-%d")
    try:
        d = requests.get(FINMIND_URL, params={
            "dataset": "TaiwanStockInstitutionalInvestorsBuySell",
            "data_id": stock_id, "start_date": start, "end_date": end},
            timeout=30).json()
    except Exception:
        return None
    if d.get("status") != 200:
        return None
    return d.get("data", [])


# ---------- 組摘要 ----------
def price_section(rows):
    """回傳 (概況文字, 明細文字)。rows 為已裁切好的股價列。"""
    closes, vols, ups, downs = [], [], 0, 0
    hi = (None, None)     # (價, 日期)
    lo = (None, None)
    for r in rows:
        c = to_num(r[6])
        v = to_num(r[1])
        h = to_num(r[4])
        l = to_num(r[5])
        d = to_num(r[7])
        if c is not None:
            closes.append(c)
        if v is not None:
            vols.append(v)
        if h is not None and (hi[0] is None or h > hi[0]):
            hi = (h, r[0])
        if l is not None and (lo[0] is None or l < lo[0]):
            lo = (l, r[0])
        if d is not None:
            if d > 0:
                ups += 1
            elif d < 0:
                downs += 1

    lines = []
    if closes:
        first, last = closes[0], closes[-1]
        chg = last - first
        pct = (chg / first * 100) if first else 0
        lines.append("期初收盤：%.2f 元（%s）" % (first, rows[0][0]))
        lines.append("期末收盤：%.2f 元（%s）" % (last, rows[-1][0]))
        lines.append("期間漲跌：%+.2f 元（%+.2f%%）" % (chg, pct))
    if hi[0] is not None:
        lines.append("期間最高：%.2f 元（%s）" % hi)
    if lo[0] is not None:
        lines.append("期間最低：%.2f 元（%s）" % lo)
    if hi[0] and lo[0] and lo[0]:
        lines.append("高低振幅：%.2f%%" % ((hi[0] - lo[0]) / lo[0] * 100))
    lines.append("上漲天數：%d 天／下跌天數：%d 天" % (ups, downs))
    if vols:
        avg = sum(vols) / len(vols) / 1000
        lines.append("平均成交量：%s 張" % format(int(avg), ","))
        lines.append("最新成交量：%s 張（為均量的 %.0f%%）" % (
            format(int(vols[-1] / 1000), ","),
            vols[-1] / (sum(vols) / len(vols)) * 100))

    # 明細表
    show = rows[-MAX_ROWS:]
    heads = ["日期", "開盤", "最高", "最低", "收盤", "漲跌", "成交量(張)"]
    w = [12, 10, 10, 10, 10, 9, 13]
    tbl = ["".join(cell(h, x) for h, x in zip(heads, w)),
           "-" * sum(w)]
    for r in show:
        v = to_num(r[1])
        vtxt = format(int(v / 1000), ",") if v is not None else "--"
        tbl.append("".join(cell(s, x) for s, x in zip(
            [r[0], r[3], r[4], r[5], r[6], r[7], vtxt], w)))
    note = ""
    if len(rows) > MAX_ROWS:
        note = "（共 %d 個交易日，以下僅列最近 %d 筆；完整統計見上方概況）\n" % (
            len(rows), MAX_ROWS)
    return "\n".join(lines), note + "\n".join(tbl)


def inst_section(data, days):
    """回傳 (累計文字, 每日文字)。"""
    acc = {"外資": [0, 0], "投信": [0, 0], "自營商": [0, 0]}
    daily = {}
    for x in data:
        g = GROUP.get(x["name"])
        if not g:
            continue
        acc[g][0] += x["buy"]
        acc[g][1] += x["sell"]
        daily.setdefault(x["date"], {"外資": 0, "投信": 0, "自營商": 0})
        daily[x["date"]][g] += x["buy"] - x["sell"]

    heads = ["法人", "買賣超(淨)", "買進", "賣出", "買占%"]
    w = [10, 16, 15, 15, 9]
    tbl = ["".join(cell(h, x) for h, x in zip(heads, w)), "-" * sum(w)]
    tb = ts = 0
    for g in ["外資", "投信", "自營商"]:
        buy, sell = acc[g]
        net = buy - sell
        pct = (buy / (buy + sell) * 100) if (buy + sell) else 0
        tb += buy
        ts += sell
        tbl.append("".join(cell(s, x) for s, x in zip(
            [g, comma(net), format(buy, ","), format(sell, ","),
             "%.1f%%" % pct], w)))
    tbl.append("-" * sum(w))
    tnet, tpct = tb - ts, (tb / (tb + ts) * 100) if (tb + ts) else 0
    tbl.append("".join(cell(s, x) for s, x in zip(
        ["三大法人", comma(tnet), format(tb, ","), format(ts, ","),
         "%.1f%%" % tpct], w)))

    # 每日淨買賣超
    dheads = ["日期", "外資", "投信", "自營商", "合計"]
    dw = [12, 14, 13, 13, 14]
    dtbl = ["".join(cell(h, x) for h, x in zip(dheads, dw)), "-" * sum(dw)]
    show_days = sorted(daily)[-MAX_ROWS:]
    for d in show_days:
        v = daily[d]
        tot = v["外資"] + v["投信"] + v["自營商"]
        dtbl.append("".join(cell(s, x) for s, x in zip(
            [d, comma(v["外資"]), comma(v["投信"]), comma(v["自營商"]),
             comma(tot)], dw)))
    note = ""
    if len(daily) > MAX_ROWS:
        note = "（共 %d 個交易日，以下僅列最近 %d 筆）\n" % (len(daily), MAX_ROWS)
    return "\n".join(tbl), note + "\n".join(dtbl)


ASK = """【請協助分析】
請你扮演一位謹慎的股市資料分析助理，根據「以上數據」用繁體中文回答下列問題：

1. 價格走勢：這段期間整體方向為何？波動是大是小？有沒有明顯的轉折點？
2. 籌碼面：三大法人分別站在買方還是賣方？外資與投信是同方向還是對做？
3. 量價關係：成交量與價格的變化是否一致？有沒有量價背離的情形？
4. 綜合判斷：用三句話總結這段期間的多空傾向。

請嚴格遵守：
- 只依據上面提供的數據推論，不要引用任何未提供的資訊（新聞、財報、其他期間）。
- 數據不足以判斷的項目，直接說「資料不足」，不要臆測。
- 不要提供任何買賣建議或目標價。
"""

DISCLAIMER = """---
※ 本摘要由「股票查詢器 V6」自動產生，資料來自公開資訊（證交所、FinMind），
   僅供課程研究與學習使用，不構成任何投資建議。資料可能因來源延遲而與實際有出入。
"""


def build_summary(name, code, label, days_range, rows, inst_data):
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    out = []
    out.append("=" * 60)
    out.append("股票資料摘要（供 AI 分析使用）")
    out.append("=" * 60)
    out.append("")
    out.append("【基本資料】")
    out.append("股票：%s（%s）" % (name, code))
    out.append("查詢期間：%s%s" % (label, days_range))
    out.append("產生時間：%s" % now)
    out.append("資料來源：證交所 STOCK_DAY（股價）、FinMind（三大法人）")
    if inst_data:
        idates = sorted(set(x["date"] for x in inst_data))
        out.append("法人資料期間：%s ~ %s（共 %d 個交易日）" %
                   (idates[0], idates[-1], len(idates)))
        if rows and idates[-1] != rows[-1][0]:
            out.append("※ 注意：三大法人資料公布時間比股價晚，因此兩者的日期區間"
                       "可能相差一個交易日，比對時請以各自標示的日期為準。")
    out.append("")

    if rows:
        summary, detail = price_section(rows)
        out.append("【一、價格概況】")
        out.append(summary)
        out.append("")
        out.append("【二、每日股價明細】")
        out.append(detail)
        out.append("")
    else:
        out.append("【一、價格概況】查無股價資料。")
        out.append("")

    if inst_data:
        acc_tbl, daily_tbl = inst_section(inst_data, None)
        out.append("【三、三大法人累計買賣超】單位：股；正=買超、負=賣超")
        out.append(acc_tbl)
        out.append("")
        out.append("【四、每日三大法人淨買賣超】單位：股")
        out.append(daily_tbl)
        out.append("")
    else:
        out.append("【三、三大法人】查無資料（可能超過 FinMind 免費額度或該股無法人進出）。")
        out.append("")

    out.append(ASK)
    out.append(DISCLAIMER)
    return "\n".join(out)


def copy_to_clipboard(text):
    """macOS 用 pbcopy；其他系統或失敗就安靜略過。"""
    try:
        p = subprocess.Popen(["pbcopy"], stdin=subprocess.PIPE)
        p.communicate(text.encode("utf-8"))
        return p.returncode == 0
    except Exception:
        return False


# ---------- 主程式 ----------
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
    label, n_days, n_months, days_back = PERIODS[choice]

    print("\n查詢股價中…（%s 需連抓約 %d 個月）" % (label, n_months))
    rows = get_days(code, n_months)[-n_days:]

    print("查詢三大法人中…")
    inst = get_institution(code, days_back)
    if inst:
        dates = sorted(set(x["date"] for x in inst))
        picked = set(dates[-n_days:])
        inst = [x for x in inst if x["date"] in picked]

    if not rows and not inst:
        print("查無資料。")
        raise SystemExit

    days_range = ""
    if rows:
        days_range = "（%s ~ %s，共 %d 個交易日）" % (rows[0][0], rows[-1][0], len(rows))

    text = build_summary(name, code, label, days_range, rows, inst)
    print("\n" + text)

    fname = "分析資料_%s_%s_%s.txt" % (name, label, datetime.now().strftime("%Y%m%d_%H%M"))
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), fname)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)

    print("=" * 60)
    print("已存檔：%s" % path)
    if copy_to_clipboard(text):
        print("內容已複製到剪貼簿，可直接貼到 Claude 或 ChatGPT 請它分析。")
    else:
        print("請開啟上面的檔案，全選複製後貼到 Claude 或 ChatGPT 請它分析。")
