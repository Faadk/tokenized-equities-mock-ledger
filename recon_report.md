# Tokenised equities mock ledger - reconciliation report as at 2026-10-09

All data is synthetic. Accounting policy is an illustrative assumption: tokens are financial liabilities and the backing shares financial assets, both at FVTPL.

## 1. Trial balance

| Account | Name | Debit | Credit |
|---|---|---:|---:|
| 1000 | Cash | 19,476.15 | |
| 1100 | Investments in underlying shares (FVTPL) | 83,510.00 | |
| 1200 | Due from broker (unsettled sales) | 4,280.00 | |
| 2000 | Token liability (FVTPL) | | 94,850.00 |
| 2100 | Due to broker (unsettled purchases) | | 11,750.00 |
| 4000 | Fee income | | 576.15 |
| 4100 | FV gain/loss - underlying investments | | 3,470.00 |
| 4200 | FV gain/loss - token liability | 3,380.00 | |

Trial balance check (debits - credits): **0.00**

Net fair-value result (should be ~0 when the token book and the hedge book match): **90.00**

## 2. Unit reconciliation (on-chain vs ledger vs custodian)

| Ticker | On-chain supply | Ledger tokens | Ledger shares | Custodian settled | Custodian pending | Custodian trade-date | R1 chain-ledger | R2 ledger shares-custodian | R3 backing gap | R4 tokens-shares |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| AAPL | 140 | 140 | 140 | 120 | -20 | 100 | 0 | 40 | 40 | 0 |
| NVDA | 625 | 515 | 425 | 600 | 25 | 625 | 110 | -200 | 0 | 90 |

The 'pending' column is a legitimate timing difference (T+1 settlement). Differences in R1-R4 are not.

## 3. Transaction-level tests

**T1 Completeness - on-chain events with no ledger entry**

- 0xT05 | MINT | NVDA | 200.0

**T2 Existence - ledger entries with no on-chain event**

- none

**T3 Accuracy - token quantity in ledger vs on-chain**

- 0xT06 NVDA: on-chain 100, ledger 10

**T4 Aged open items - hedge trades past settlement date and not settled in the ledger**

- HEDGE-0xT07 BUY 40 AAPL (due 2026-10-09) - custodian has not confirmed

**T5 Custodian confirmations with no ledger trade**

- HEDGE-0xT05 NVDA 200

## 4. Breaks to investigate

- AAPL: ledger share holdings differ from custodian trade-date position by 40
- AAPL: tokens in circulation exceed custodian-held shares by 40 (backing shortfall)
- NVDA: on-chain supply differs from ledger token units by 110
- NVDA: ledger share holdings differ from custodian trade-date position by -200
- NVDA: ledger token units differ from ledger share units by 90
- T1: on-chain MINT 200 NVDA (0xT05) has no journal entry
- T3: 0xT06 NVDA on-chain quantity 100 vs ledger 10
- T4: HEDGE-0xT07 BUY 40 AAPL unsettled past due date 2026-10-09
- T5: custodian confirm HEDGE-0xT05 (200 NVDA) not recorded in ledger

Note: netting hides errors. NVDA's net on-chain vs ledger difference is the sum of one missing mint and one keying error that offset in part; only the transaction-level tests show them separately.
