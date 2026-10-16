#!/usr/bin/env python3
"""
Mock ledger for a tokenised-equities issuer (illustrative only).

Models a simplified issuer entity that issues tokens backed 1:1 by listed shares:
  * token issuance (mint) and redemption (burn)
  * hedge trades in the underlying shares, with T+1 settlement
  * daily fair-value remeasurement of both sides
  * a three-way reconciliation: on-chain supply vs ledger vs custodian
  * transaction-level completeness / existence / accuracy tests

Three breaks are injected on purpose so the controls have something to find.
All prices, tickers' quantities and hashes are synthetic. The accounting policy
is an ASSUMPTION for demonstration, not any real company's actual model.

Run:  python3 tokenized_equities_ledger.py
"""
import sqlite3
from datetime import date, timedelta

# ---------------------------------------------------------------- assumptions
DAYS = [date(2026, 10, d) for d in range(5, 10)]          # Mon-Fri
REPORT_DATE = DAYS[-1]
PRICES = {                                                 # synthetic closing prices
    "AAPL": [210.00, 212.00, 211.00, 215.00, 214.00],
    "NVDA": [120.00, 118.00, 125.00, 127.00, 126.00],
}
FEE_RATE = 0.005                                           # 0.5% on issue and redeem

ACCOUNTS = {
    1000: ("Cash", "Asset"),
    1100: ("Investments in underlying shares (FVTPL)", "Asset"),
    1200: ("Due from broker (unsettled sales)", "Asset"),
    2000: ("Token liability (FVTPL)", "Liability"),
    2100: ("Due to broker (unsettled purchases)", "Liability"),
    4000: ("Fee income", "Income"),
    4100: ("FV gain/loss - underlying investments", "Income"),
    4200: ("FV gain/loss - token liability", "Expense"),
}
CASH, INV, DUE_FROM, TOKEN, DUE_TO, FEE, FV_INV, FV_TOK = 1000, 1100, 1200, 2000, 2100, 4000, 4100, 4200

db = sqlite3.connect(":memory:")
db.executescript("""
CREATE TABLE accounts(code INTEGER PRIMARY KEY, name TEXT, type TEXT);
CREATE TABLE journal(je_id INTEGER PRIMARY KEY, je_date TEXT, ref TEXT, memo TEXT);
CREATE TABLE lines(je_id INTEGER, account INTEGER, debit REAL, credit REAL, ticker TEXT, qty REAL);
CREATE TABLE onchain(tx_hash TEXT PRIMARY KEY, tx_date TEXT, kind TEXT, ticker TEXT, qty REAL, wallet TEXT);
CREATE TABLE trades(ref TEXT PRIMARY KEY, trade_date TEXT, settle_date TEXT, ticker TEXT,
                    side TEXT, qty REAL, amount REAL, status TEXT);
CREATE TABLE custodian_confirms(trade_id TEXT PRIMARY KEY, ticker TEXT, signed_qty REAL, settle_date TEXT);
""")
db.executemany("INSERT INTO accounts VALUES (?,?,?)", [(c, n, t) for c, (n, t) in ACCOUNTS.items()])


# -------------------------------------------------------------------- helpers
def price(ticker, d):
    return PRICES[ticker][DAYS.index(d)]


def next_business_day(d):
    d += timedelta(days=1)
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d


def post_je(d, ref, memo, lines):
    """lines: (account, debit, credit, ticker, qty). Control: every entry must balance."""
    dr = round(sum(l[1] for l in lines), 2)
    cr = round(sum(l[2] for l in lines), 2)
    if dr != cr:
        raise ValueError(f"Unbalanced journal {ref}: Dr {dr} vs Cr {cr}")
    je_id = db.execute("INSERT INTO journal(je_date, ref, memo) VALUES (?,?,?)",
                       (d.isoformat(), ref, memo)).lastrowid
    db.executemany("INSERT INTO lines VALUES (?,?,?,?,?,?)",
                   [(je_id, a, dr_, cr_, t, q) for a, dr_, cr_, t, q in lines])


def ledger_units(account, ticker):
    return db.execute("SELECT COALESCE(SUM(qty),0) FROM lines WHERE account=? AND ticker=?",
                      (account, ticker)).fetchone()[0]


def balance(account):
    return db.execute("SELECT COALESCE(SUM(debit)-SUM(credit),0) FROM lines WHERE account=?",
                      (account,)).fetchone()[0]


# --------------------------------------------------------------------- events
def mint(d, tx, ticker, qty, wallet, post_to_ledger=True, hedge_executes=True):
    """Customer subscribes: tokens minted on-chain, shares bought to back them."""
    p = price(ticker, d)
    n = round(qty * p, 2)
    fee = round(n * FEE_RATE, 2)
    sd = next_business_day(d)
    db.execute("INSERT INTO onchain VALUES (?,?,?,?,?,?)", (tx, d.isoformat(), "MINT", ticker, qty, wallet))
    hedge = f"HEDGE-{tx}"
    if hedge_executes:
        db.execute("INSERT INTO custodian_confirms VALUES (?,?,?,?)", (hedge, ticker, qty, sd.isoformat()))
    if post_to_ledger:
        post_je(d, tx, f"Issue {qty} {ticker} tokens", [
            (CASH, n + fee, 0, None, None),
            (TOKEN, 0, n, ticker, qty),
            (FEE, 0, fee, None, None)])
        post_je(d, hedge, f"Buy {qty} {ticker} to back issuance", [
            (INV, n, 0, ticker, qty),
            (DUE_TO, 0, n, None, None)])
        db.execute("INSERT INTO trades VALUES (?,?,?,?,?,?,?,?)",
                   (hedge, d.isoformat(), sd.isoformat(), ticker, "BUY", qty, n, "OPEN"))


def burn(d, tx, ticker, qty, wallet, ledger_qty=None):
    """Customer redeems: tokens burned on-chain, shares sold, cash returned."""
    lq = qty if ledger_qty is None else ledger_qty        # ledger_qty simulates a keying error
    p = price(ticker, d)
    n_l, n = round(lq * p, 2), round(qty * p, 2)
    fee = round(n_l * FEE_RATE, 2)
    sd = next_business_day(d)
    hedge = f"HEDGE-{tx}"
    db.execute("INSERT INTO onchain VALUES (?,?,?,?,?,?)", (tx, d.isoformat(), "BURN", ticker, qty, wallet))
    db.execute("INSERT INTO custodian_confirms VALUES (?,?,?,?)", (hedge, ticker, -qty, sd.isoformat()))
    post_je(d, tx, f"Redeem {lq} {ticker} tokens", [
        (TOKEN, n_l, 0, ticker, -lq),
        (CASH, 0, n_l - fee, None, None),
        (FEE, 0, fee, None, None)])
    post_je(d, hedge, f"Sell {qty} {ticker} to fund redemption", [
        (DUE_FROM, n, 0, None, None),
        (INV, 0, n, ticker, -qty)])
    db.execute("INSERT INTO trades VALUES (?,?,?,?,?,?,?,?)",
               (hedge, d.isoformat(), sd.isoformat(), ticker, "SELL", qty, n, "OPEN"))


def settle_due_trades(d):
    """Post cash settlement only for trades the custodian has confirmed."""
    rows = db.execute("""SELECT t.ref, t.side, t.amount FROM trades t
                         JOIN custodian_confirms c ON c.trade_id = t.ref
                         WHERE t.settle_date=? AND t.status='OPEN'""", (d.isoformat(),)).fetchall()
    for ref, side, amt in rows:
        if side == "BUY":
            post_je(d, f"SETTLE-{ref}", "Settle purchase", [(DUE_TO, amt, 0, None, None), (CASH, 0, amt, None, None)])
        else:
            post_je(d, f"SETTLE-{ref}", "Settle sale", [(CASH, amt, 0, None, None), (DUE_FROM, 0, amt, None, None)])
        db.execute("UPDATE trades SET status='SETTLED' WHERE ref=?", (ref,))


def remeasure(d, ticker, p0, p1):
    """Daily FVTPL remeasurement of the shares held and the token liability, on ledger units."""
    dp = round(p1 - p0, 2)
    a = round(ledger_units(INV, ticker) * dp, 2)
    l = round(ledger_units(TOKEN, ticker) * dp, 2)
    lines = []
    if a > 0:   lines += [(INV, a, 0, ticker, 0), (FV_INV, 0, a, None, None)]
    elif a < 0: lines += [(FV_INV, -a, 0, None, None), (INV, 0, -a, ticker, 0)]
    if l > 0:   lines += [(FV_TOK, l, 0, None, None), (TOKEN, 0, l, ticker, 0)]
    elif l < 0: lines += [(TOKEN, -l, 0, ticker, 0), (FV_TOK, 0, -l, None, None)]
    if lines:
        post_je(d, f"REVAL-{ticker}-{d.isoformat()}", f"Remeasure {ticker} to fair value", lines)


# ------------------------------------------------------------------- scenario
D1, D2, D3, D4, D5 = DAYS
SCENARIO = {
    D1: [lambda: mint(D1, "0xT01", "AAPL", 100, "walletA"),
         lambda: mint(D1, "0xT02", "NVDA", 500, "walletB")],
    D2: [lambda: mint(D2, "0xT03", "AAPL", 50, "walletC")],
    D3: [lambda: burn(D3, "0xT04", "AAPL", 30, "walletA"),
         # BREAK 1: mint happened on-chain and at the custodian, but the ledger feed dropped it
         lambda: mint(D3, "0xT05", "NVDA", 200, "walletD", post_to_ledger=False)],
    D4: [# BREAK 2: redemption keyed as 10 tokens in the ledger instead of 100
         lambda: burn(D4, "0xT06", "NVDA", 100, "walletB", ledger_qty=10),
         # BREAK 3: tokens minted and booked, but the custodian never executed the hedge buy
         lambda: mint(D4, "0xT07", "AAPL", 40, "walletE", hedge_executes=False)],
    D5: [lambda: mint(D5, "0xT08", "NVDA", 25, "walletF"),
         lambda: burn(D5, "0xT09", "AAPL", 20, "walletC")],
}

for i, d in enumerate(DAYS):
    settle_due_trades(d)
    if i > 0:
        for t in PRICES:
            remeasure(d, t, PRICES[t][i - 1], PRICES[t][i])
    for event in SCENARIO[d]:
        event()

# --------------------------------------------------------------------- report
out = []
w = out.append
rd = REPORT_DATE.isoformat()
w(f"# Tokenised equities mock ledger - reconciliation report as at {rd}\n")
w("All data is synthetic. Accounting policy is an illustrative assumption: tokens are financial liabilities "
  "and the backing shares financial assets, both at FVTPL.\n")

# 1. Trial balance
w("## 1. Trial balance\n")
w("| Account | Name | Debit | Credit |\n|---|---|---:|---:|")
tb_total = 0.0
for code, (name, _) in ACCOUNTS.items():
    b = round(balance(code), 2)
    tb_total += b
    w(f"| {code} | {name} | {b:,.2f} | |" if b >= 0 else f"| {code} | {name} | | {-b:,.2f} |")
w(f"\nTrial balance check (debits - credits): **{round(tb_total, 2) + 0.0:,.2f}**\n")
net_fv = -(balance(FV_INV) + balance(FV_TOK))
w(f"Net fair-value result (should be ~0 when the token book and the hedge book match): **{net_fv:,.2f}**\n")

# 2. Three-way unit reconciliation
w("## 2. Unit reconciliation (on-chain vs ledger vs custodian)\n")
w("| Ticker | On-chain supply | Ledger tokens | Ledger shares | Custodian settled | Custodian pending | Custodian trade-date | "
  "R1 chain-ledger | R2 ledger shares-custodian | R3 backing gap | R4 tokens-shares |\n"
  "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
breaks = []
for t in PRICES:
    chain = db.execute("SELECT COALESCE(SUM(CASE kind WHEN 'MINT' THEN qty ELSE -qty END),0) FROM onchain WHERE ticker=?", (t,)).fetchone()[0]
    liab, inv = ledger_units(TOKEN, t), ledger_units(INV, t)
    cust = db.execute("SELECT COALESCE(SUM(signed_qty),0) FROM custodian_confirms WHERE ticker=?", (t,)).fetchone()[0]
    settled = db.execute("SELECT COALESCE(SUM(signed_qty),0) FROM custodian_confirms WHERE ticker=? AND settle_date<=?", (t, rd)).fetchone()[0]
    r1, r2, r3, r4 = chain - liab, inv - cust, chain - cust, liab - inv
    w(f"| {t} | {chain:g} | {liab:g} | {inv:g} | {settled:g} | {cust - settled:g} | {cust:g} | {r1:g} | {r2:g} | {r3:g} | {r4:g} |")
    if r1: breaks.append(f"{t}: on-chain supply differs from ledger token units by {r1:g}")
    if r2: breaks.append(f"{t}: ledger share holdings differ from custodian trade-date position by {r2:g}")
    if r3: breaks.append(f"{t}: tokens in circulation exceed custodian-held shares by {r3:g} (backing shortfall)" if r3 > 0
                         else f"{t}: custodian holds {-r3:g} more shares than tokens issued")
    if r4: breaks.append(f"{t}: ledger token units differ from ledger share units by {r4:g}")
w("\nThe 'pending' column is a legitimate timing difference (T+1 settlement). Differences in R1-R4 are not.\n")

# 3. Transaction-level tests
w("## 3. Transaction-level tests\n")
w("**T1 Completeness - on-chain events with no ledger entry**\n")
rows = db.execute("""SELECT o.tx_hash, o.kind, o.ticker, o.qty FROM onchain o
                     LEFT JOIN journal j ON j.ref = o.tx_hash WHERE j.je_id IS NULL""").fetchall()
for r in rows or [("none",)]:
    w(f"- {' | '.join(str(x) for x in r)}")
    if rows: breaks.append(f"T1: on-chain {r[1]} {r[3]:g} {r[2]} ({r[0]}) has no journal entry")

w("\n**T2 Existence - ledger entries with no on-chain event**\n")
rows = db.execute("""SELECT j.ref FROM journal j WHERE j.ref LIKE '0x%'
                     AND j.ref NOT IN (SELECT tx_hash FROM onchain)""").fetchall()
w("\n".join(f"- {r[0]}" for r in rows) if rows else "- none")

w("\n**T3 Accuracy - token quantity in ledger vs on-chain**\n")
rows = db.execute("""SELECT o.tx_hash, o.ticker, o.qty, ABS(l.qty) FROM onchain o
                     JOIN journal j ON j.ref = o.tx_hash
                     JOIN lines l ON l.je_id = j.je_id AND l.account = 2000
                     WHERE ABS(l.qty) <> o.qty""").fetchall()
for tx, t, cq, lq in rows:
    w(f"- {tx} {t}: on-chain {cq:g}, ledger {lq:g}")
    breaks.append(f"T3: {tx} {t} on-chain quantity {cq:g} vs ledger {lq:g}")
if not rows: w("- none")

w("\n**T4 Aged open items - hedge trades past settlement date and not settled in the ledger**\n")
rows = db.execute("SELECT ref, ticker, side, qty, settle_date FROM trades WHERE status='OPEN' AND settle_date<=?", (rd,)).fetchall()
for ref, t, side, q, sd in rows:
    w(f"- {ref} {side} {q:g} {t} (due {sd}) - custodian has not confirmed")
    breaks.append(f"T4: {ref} {side} {q:g} {t} unsettled past due date {sd}")
if not rows: w("- none")

w("\n**T5 Custodian confirmations with no ledger trade**\n")
rows = db.execute("""SELECT trade_id, ticker, signed_qty FROM custodian_confirms
                     WHERE trade_id NOT IN (SELECT ref FROM trades)""").fetchall()
for ref, t, q in rows:
    w(f"- {ref} {t} {q:g}")
    breaks.append(f"T5: custodian confirm {ref} ({q:g} {t}) not recorded in ledger")
if not rows: w("- none")

# 4. Summary
w("\n## 4. Breaks to investigate\n")
for b in breaks:
    w(f"- {b}")
w("\nNote: netting hides errors. NVDA's net on-chain vs ledger difference is the sum of one missing mint and one "
  "keying error that offset in part; only the transaction-level tests show them separately.")

report = "\n".join(out)
print(report)
with open("recon_report.md", "w") as f:
    f.write(report + "\n")
