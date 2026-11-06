# -*- coding: utf-8 -*-
"""
股票查詢器 V7 — 完整基本面 + 籌碼面「AI 分析用資料摘要」
  在 V6（股價 + 個股三大法人）之上再加四個面向：
    一、評價指標：本益比 PER / 股價淨值比 PBR / 殖利率（含期間高低區間）
    二、月營收趨勢：近 13 個月營收、年增率 YoY、月增率 MoM、公司自述增減原因
    三、財務季報：近 8 季營收、毛利率、營益率、淨利率、EPS
    四、大盤對照：全市場三大法人 vs 本檔三大法人，判斷順勢或逆勢

  產出一份結構化文字摘要，存成 .txt 並複製到剪貼簿，
  可直接貼給 AI（Claude / ChatGPT）做趨勢分析。

本版不呼叫任何 AI API，不需要金鑰、不需付費。
資料來源：證交所 STOCK_DAY / OpenAPI、FinMind。
註：法人說明會資料需另外爬「公開資訊觀測站」，本版未納入。
"""
import os
import time
import subprocess
import requests
import unicodedata
from datetime import datetime, timedelta

LIST_URL = "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"
DAY_URL = "https://www.twse.com.tw/exchangeReport/STOCK_DAY"
REVENUE_URL = "https://openapi.twse.com.tw/v1/opendata/t187ap05_L"
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

# FinMind 財報欄位 -> 中文
FS = {
    "Revenue": "營業收入",
    "GrossProfit": "營業毛利",
    "OperatingIncome": "營業利益",
    "IncomeAfterTaxes": "稅後淨利",
    "EPS": "每股盈餘",
}

MAX_ROWS = 40          # 每日明細最多列幾筆
N_MONTHS_REV = 13      # 月營收列幾個月
N_QUARTERS = 8         # 財報列幾季


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
    try:
        return float(str(s).replace(",", "").replace("+", ""))
    except ValueError:
        return None


def yi(n):
    """元 -> 億元字串。"""
    return "%.2f" % (n / 1e8)


def lots(n):
    """股 -> 張（整數，淨額用，正數會帶 + 號）。"""
    return comma(int(round(n / 1000)))


def lots_abs(n):
    """股 -> 張（整數，買進/賣出等絕對量用，不加正號）。"""
    return format(int(round(n / 1000)), ",")


def quarter(d):
    """'2026-06-30' -> '2026Q2'。"""
    try:
        y, m, _ = d.split("-")
        return "%sQ%d" % (y, (int(m) - 1) // 3 + 1)
    except Exception:
        return d


def finmind(dataset, start, end=None, stock_id=None):
    """統一的 FinMind 查詢；失敗回傳空 list。"""
    p = {"dataset": dataset, "start_date": start,
         "end_date": end or datetime.now().strftime("%Y-%m-%d")}
    if stock_id:
        p["data_id"] = stock_id
    try:
        d = requests.get(FINMIND_URL, params=p, timeout=40).json()
    except Exception:
        return []
    return d.get("data", []) if d.get("status") == 200 else []


def days_ago(n):
    return (datetime.now() - timedelta(days=n)).strftime("%Y-%m-%d")


# ---------- 抓資料 ----------
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
        r[0] = roc_to_ad(r[0])
    uniq = {r[0]: r for r in all_rows}
    return [uniq[k] for k in sorted(uniq)]


def get_institution(stock_id, days_back):
    return finmind("TaiwanStockInstitutionalInvestorsBuySell",
                   days_ago(days_back), stock_id=stock_id)


def get_market_inst(days_back):
    """全市場三大法人（單位：元）。"""
    return finmind("TaiwanStockTotalInstitutionalInvestors", days_ago(days_back))


def get_per(stock_id, days_back):
    return finmind("TaiwanStockPER", days_ago(max(days_back, 400)), stock_id=stock_id)


def get_month_revenue(stock_id):
    return finmind("TaiwanStockMonthRevenue", days_ago(800), stock_id=stock_id)


def get_financials(stock_id):
    return finmind("TaiwanStockFinancialStatements", days_ago(900), stock_id=stock_id)


def get_revenue_note(stock_id):
    """證交所月營收彙總表有公司自述的增減原因（FinMind 沒有）。"""
    try:
        rows = requests.get(REVENUE_URL, timeout=30).json()
    except Exception:
        return None
    for r in rows:
        if r.get("公司代號") == stock_id:
            return r
    return None


# ---------- 各區塊 ----------
def price_section(rows):
    closes, vols, ups, downs = [], [], 0, 0
    hi = lo = (None, None)
    for r in rows:
        c, v, h, l, d = (to_num(r[6]), to_num(r[1]), to_num(r[4]),
                         to_num(r[5]), to_num(r[7]))
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
        lines.append("期初收盤：%.2f 元（%s）" % (first, rows[0][0]))
        lines.append("期末收盤：%.2f 元（%s）" % (last, rows[-1][0]))
        lines.append("期間漲跌：%+.2f 元（%+.2f%%）" %
                     (chg, (chg / first * 100) if first else 0))
    if hi[0] is not None:
        lines.append("期間最高：%.2f 元（%s）" % hi)
    if lo[0] is not None:
        lines.append("期間最低：%.2f 元（%s）" % lo)
    if hi[0] and lo[0]:
        lines.append("高低振幅：%.2f%%" % ((hi[0] - lo[0]) / lo[0] * 100))
    lines.append("上漲天數：%d 天／下跌天數：%d 天" % (ups, downs))
    if vols:
        avg = sum(vols) / len(vols)
        lines.append("平均成交量：%s 張" % format(int(avg / 1000), ","))
        lines.append("最新成交量：%s 張（為均量的 %.0f%%）" %
                     (format(int(vols[-1] / 1000), ","), vols[-1] / avg * 100))

    show = rows[-MAX_ROWS:]
    heads = ["日期", "開盤", "最高", "最低", "收盤", "漲跌", "成交量(張)"]
    w = [12, 10, 10, 10, 10, 9, 13]
    tbl = ["".join(cell(h, x) for h, x in zip(heads, w)), "-" * sum(w)]
    for r in show:
        v = to_num(r[1])
        tbl.append("".join(cell(s, x) for s, x in zip(
            [r[0], r[3], r[4], r[5], r[6], r[7],
             format(int(v / 1000), ",") if v is not None else "--"], w)))
    note = ("（共 %d 個交易日，以下僅列最近 %d 筆；完整統計見上方概況）\n"
            % (len(rows), MAX_ROWS)) if len(rows) > MAX_ROWS else ""
    return "\n".join(lines), note + "\n".join(tbl)


def valuation_section(per_rows, days_range_start):
    """評價指標：最新 PER/PBR/殖利率 + 近一年區間。"""
    if not per_rows:
        return None
    latest = per_rows[-1]
    pers = [x["PER"] for x in per_rows if x.get("PER")]
    pbrs = [x["PBR"] for x in per_rows if x.get("PBR")]
    lines = ["資料日期：%s" % latest["date"],
             "本益比 PER：%.2f 倍" % latest.get("PER", 0),
             "股價淨值比 PBR：%.2f 倍" % latest.get("PBR", 0),
             "現金殖利率：%.2f%%" % latest.get("dividend_yield", 0)]
    if pers:
        lo_, hi_ = min(pers), max(pers)
        pos = ((latest.get("PER", 0) - lo_) / (hi_ - lo_) * 100) if hi_ > lo_ else 0
        lines.append("近一年 PER 區間：%.2f ~ %.2f 倍（目前位於區間的 %.0f%% 位置，"
                     "0%% 代表最便宜、100%% 代表最貴）" % (lo_, hi_, pos))
    if pbrs:
        lines.append("近一年 PBR 區間：%.2f ~ %.2f 倍" % (min(pbrs), max(pbrs)))
    return "\n".join(lines)


def revenue_section(rev_rows, note_row):
    """月營收趨勢（含 YoY / MoM）。"""
    if not rev_rows:
        return None
    # 依 (年,月) 排序
    rs = sorted(rev_rows, key=lambda x: (x["revenue_year"], x["revenue_month"]))
    by_ym = {(x["revenue_year"], x["revenue_month"]): x["revenue"] for x in rs}
    show = rs[-N_MONTHS_REV:]

    heads = ["年月", "營收(億元)", "年增率YoY", "月增率MoM"]
    w = [11, 14, 13, 13]
    tbl = ["".join(cell(h, x) for h, x in zip(heads, w)), "-" * sum(w)]
    for x in show:
        y, m, v = x["revenue_year"], x["revenue_month"], x["revenue"]
        last_year = by_ym.get((y - 1, m))
        pm = (y, m - 1) if m > 1 else (y - 1, 12)
        last_month = by_ym.get(pm)
        yoy = "%+.1f%%" % ((v - last_year) / last_year * 100) if last_year else "--"
        mom = "%+.1f%%" % ((v - last_month) / last_month * 100) if last_month else "--"
        tbl.append("".join(cell(s, x2) for s, x2 in zip(
            ["%d/%02d" % (y, m), yi(v), yoy, mom], w)))

    extra = []
    if note_row:
        note = (note_row.get("備註") or "").strip()
        if note:
            extra.append("公司自述增減原因（%s）：%s" %
                         (note_row.get("資料年月", ""), note))
        cum = to_num(note_row.get("累計營業收入-前期比較增減(%)"))
        if cum is not None:
            extra.append("今年累計營收年增率：%+.1f%%" % cum)
    return "\n".join(tbl) + ("\n\n" + "\n".join(extra) if extra else "")


def financial_section(fs_rows):
    """近 N 季財報：營收、三率、EPS。"""
    if not fs_rows:
        return None
    piv = {}
    for x in fs_rows:
        piv.setdefault(x["date"], {})[x["type"]] = x["value"]
    dates = sorted(piv)[-N_QUARTERS:]
    if not dates:
        return None

    heads = ["季別", "營收(億)", "毛利率", "營益率", "淨利率", "EPS(元)"]
    w = [13, 13, 10, 10, 10, 11]
    tbl = ["".join(cell(h, x) for h, x in zip(heads, w)), "-" * sum(w)]
    for d in dates:
        v = piv[d]
        rev = v.get("Revenue")
        def rate(key):
            n = v.get(key)
            return "%.1f%%" % (n / rev * 100) if (rev and n is not None) else "--"
        eps = v.get("EPS")
        tbl.append("".join(cell(s, x) for s, x in zip(
            [quarter(d), yi(rev) if rev else "--", rate("GrossProfit"),
             rate("OperatingIncome"), rate("IncomeAfterTaxes"),
             ("%.2f" % eps) if eps is not None else "--"], w)))

    # 最新季 vs 去年同季
    tail = []
    if len(dates) >= 5:
        now_, ago = piv[dates[-1]], piv[dates[-5]]
        if now_.get("Revenue") and ago.get("Revenue"):
            tail.append("最新季營收較去年同季：%+.1f%%" %
                        ((now_["Revenue"] - ago["Revenue"]) / ago["Revenue"] * 100))
        if now_.get("EPS") is not None and ago.get("EPS"):
            tail.append("最新季 EPS 較去年同季：%+.1f%%" %
                        ((now_["EPS"] - ago["EPS"]) / ago["EPS"] * 100))
    tail.append("※ 單位為單季數字（非累計）；財報公布有時間差，最新一季可能尚未收錄。")
    return "\n".join(tbl) + "\n\n" + "\n".join(tail)


def inst_section(data):
    """個股三大法人：累計 + 每日。單位改用「張」。"""
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

    heads = ["法人", "買賣超(淨,張)", "買進(張)", "賣出(張)", "買占%"]
    w = [10, 16, 14, 14, 9]
    tbl = ["".join(cell(h, x) for h, x in zip(heads, w)), "-" * sum(w)]
    tb = ts = 0
    nets = {}
    for g in ["外資", "投信", "自營商"]:
        buy, sell = acc[g]
        nets[g] = buy - sell
        tb += buy
        ts += sell
        tbl.append("".join(cell(s, x) for s, x in zip(
            [g, lots(buy - sell), lots_abs(buy), lots_abs(sell),
             "%.1f%%" % ((buy / (buy + sell) * 100) if (buy + sell) else 0)], w)))
    tbl.append("-" * sum(w))
    nets["三大法人"] = tb - ts
    tbl.append("".join(cell(s, x) for s, x in zip(
        ["三大法人", lots(tb - ts), lots_abs(tb), lots_abs(ts),
         "%.1f%%" % ((tb / (tb + ts) * 100) if (tb + ts) else 0)], w)))

    dheads = ["日期", "外資", "投信", "自營商", "合計"]
    dw = [12, 12, 11, 11, 12]
    dtbl = ["".join(cell(h, x) for h, x in zip(dheads, dw)), "-" * sum(dw)]
    for d in sorted(daily)[-MAX_ROWS:]:
        v = daily[d]
        dtbl.append("".join(cell(s, x) for s, x in zip(
            [d, lots(v["外資"]), lots(v["投信"]), lots(v["自營商"]),
             lots(sum(v.values()))], dw)))
    note = ("（共 %d 個交易日，以下僅列最近 %d 筆）\n" % (len(daily), MAX_ROWS)
            ) if len(daily) > MAX_ROWS else ""
    return "\n".join(tbl), note + "\n".join(dtbl), nets


def market_section(mkt_rows, stock_nets, days):
    """全市場三大法人（金額）vs 本檔（股數）→ 比方向。"""
    if not mkt_rows:
        return None
    picked = set(days)
    acc = {"外資": [0, 0], "投信": [0, 0], "自營商": [0, 0]}
    for x in mkt_rows:
        if x["date"] not in picked:
            continue
        g = GROUP.get(x["name"])
        if g:
            acc[g][0] += x["buy"]
            acc[g][1] += x["sell"]

    if not any(sum(v) for v in acc.values()):
        return None

    heads = ["法人", "全市場買賣超(億元)", "本檔買賣超(張)", "方向比較"]
    w = [10, 20, 17, 14]
    tbl = ["".join(cell(h, x) for h, x in zip(heads, w)), "-" * sum(w)]
    tnet = 0
    for g in ["外資", "投信", "自營商"]:
        mnet = acc[g][0] - acc[g][1]
        tnet += mnet
        snet = stock_nets.get(g, 0)
        if mnet == 0 or snet == 0:
            cmp_ = "--"
        elif (mnet > 0) == (snet > 0):
            cmp_ = "同向"
        else:
            cmp_ = "逆勢"
        tbl.append("".join(cell(s, x) for s, x in zip(
            [g, ("+" if mnet > 0 else "") + yi(mnet), lots(snet), cmp_], w)))
    tbl.append("-" * sum(w))
    snet_all = stock_nets.get("三大法人", 0)
    cmp_all = "--" if (tnet == 0 or snet_all == 0) else (
        "同向" if (tnet > 0) == (snet_all > 0) else "逆勢")
    tbl.append("".join(cell(s, x) for s, x in zip(
        ["三大法人", ("+" if tnet > 0 else "") + yi(tnet), lots(snet_all), cmp_all], w)))
    return ("※ 全市場為「金額」、本檔為「股數」，單位不同不可直接相比，"
            "請只看買賣方向是否一致。\n" + "\n".join(tbl))


ASK = """【請協助分析】
請你扮演一位謹慎的股市資料分析助理，根據「以上所有數據」用繁體中文做分層分析：

一、籌碼面
  1. 三大法人分別站買方還是賣方？外資與投信是同方向還是對做？
  2. 對照「大盤對照」那張表：本檔是順著全市場的法人動向，還是逆勢？
     若逆勢，代表什麼意義？

二、基本面
  3. 月營收的年增率（YoY）趨勢是加速、持平還是轉弱？公司自述的原因說明了什麼？
  4. 季報三率（毛利率／營益率／淨利率）與 EPS 的變化方向為何？獲利體質是改善還是衰退？
  5. 以目前的本益比在近一年區間的位置來看，評價偏貴還是偏便宜？

三、價量與綜合
  6. 價格走勢與成交量是否一致？有沒有量價背離？
  7. 把上面三面向交叉比對，指出「互相印證」與「互相矛盾」的地方。
     例如：法人賣超但營收創高、或股價下跌但三率改善，這類訊號該怎麼解讀？
  8. 最後用三到五句話，總結這段期間的多空傾向與最值得留意的一項風險。

請嚴格遵守：
- 只依據上面提供的數據推論，不要引用任何未提供的資訊（新聞、法說會、分析師預估）。
- 數據不足以判斷的項目，直接說「資料不足」，不要臆測。
- 財報與月營收的公布時間比股價晚，比較時請注意期間不一致的問題。
- 不要提供任何買賣建議或目標價。
"""

DISCLAIMER = """---
※ 本摘要由「股票查詢器 V7」自動產生，資料來自公開資訊（證交所、FinMind），
   僅供課程研究與學習使用，不構成任何投資建議。
   資料可能因來源延遲、財報公布時程而與實際有出入。
"""


def build_summary(name, code, label, days_range, rows, inst, mkt, per, rev, note, fs):
    out = ["=" * 64,
           "股票資料摘要（供 AI 分析使用）",
           "=" * 64, "",
           "【基本資料】",
           "股票：%s（%s）" % (name, code),
           "查詢期間：%s%s" % (label, days_range),
           "產生時間：%s" % datetime.now().strftime("%Y-%m-%d %H:%M"),
           "資料來源：證交所 STOCK_DAY / OpenAPI、FinMind"]
    inst_days = []
    if inst:
        inst_days = sorted(set(x["date"] for x in inst))
        out.append("法人資料期間：%s ~ %s（共 %d 個交易日）" %
                   (inst_days[0], inst_days[-1], len(inst_days)))
        if rows and (inst_days[-1] != rows[-1][0] or inst_days[0] != rows[0][0]):
            out.append("※ 注意：股價與三大法人的資料區間不完全相同"
                       "（法人資料公布時間較晚，且兩邊來源的交易日起算點不同），"
                       "比對時請以各表自己標示的日期為準，不要假設兩張表逐列對齊。")
    out.append("")

    n = 0
    def head(title):
        return "【%s、%s】" % ("一二三四五六七八"[n], title)

    if rows:
        s, d = price_section(rows)
        out += [head("價格概況"), s, ""]
        n += 1
        out += [head("每日股價明細"), d, ""]
        n += 1

    v = valuation_section(per, None) if per else None
    if v:
        out += [head("評價指標"), v, ""]
        n += 1

    r = revenue_section(rev, note) if rev else None
    if r:
        out += [head("月營收趨勢（單位：億元）"), r, ""]
        n += 1

    f = financial_section(fs) if fs else None
    if f:
        out += [head("財務季報"), f, ""]
        n += 1

    stock_nets = {}
    if inst:
        acc_t, daily_t, stock_nets = inst_section(inst)
        out += [head("本檔三大法人累計（正=買超、負=賣超）"), acc_t, ""]
        n += 1
        out += [head("本檔每日三大法人淨買賣超（張）"), daily_t, ""]
        n += 1

    m = market_section(mkt, stock_nets, inst_days) if (mkt and stock_nets) else None
    if m:
        out += [head("大盤對照：全市場三大法人 vs 本檔"), m, ""]
        n += 1

    out += [ASK, DISCLAIMER]
    return "\n".join(out)


def copy_to_clipboard(text):
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

    print("\n開始查詢（共 6 個步驟，請稍候）")
    print("  [1/6] 股價…（%s 需連抓約 %d 個月）" % (label, n_months))
    rows = get_days(code, n_months)[-n_days:]

    print("  [2/6] 本檔三大法人…")
    inst = get_institution(code, days_back)
    if inst:
        dates = sorted(set(x["date"] for x in inst))
        picked = set(dates[-n_days:])
        inst = [x for x in inst if x["date"] in picked]

    print("  [3/6] 全市場三大法人…")
    mkt = get_market_inst(days_back)

    print("  [4/6] 本益比 / 殖利率 / 股價淨值比…")
    per = get_per(code, days_back)

    print("  [5/6] 月營收…")
    rev = get_month_revenue(code)
    note = get_revenue_note(code)

    print("  [6/6] 財務季報…")
    fs = get_financials(code)

    if not rows and not inst:
        print("查無資料。")
        raise SystemExit

    days_range = ("（%s ~ %s，共 %d 個交易日）" %
                  (rows[0][0], rows[-1][0], len(rows))) if rows else ""
    text = build_summary(name, code, label, days_range,
                         rows, inst, mkt, per, rev, note, fs)
    print("\n" + text)

    fname = "分析資料_%s_%s_%s.txt" % (name, label,
                                   datetime.now().strftime("%Y%m%d_%H%M"))
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), fname)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)

    print("=" * 64)
    print("已存檔：%s" % path)
    if copy_to_clipboard(text):
        print("內容已複製到剪貼簿，可直接貼到 Claude 或 ChatGPT 請它分析。")
    else:
        print("請開啟上面的檔案，全選複製後貼到 Claude 或 ChatGPT 請它分析。")
