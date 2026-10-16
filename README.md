# Tokenised Equities Mock Ledger

Built by Fahad K V, ACCA finalist and ex-KPMG audit senior (5 years of external audit, 4 at KPMG UK audit), as a hands-on exercise in the accounting and controls for tokenised assets. All data is synthetic and the accounting policy is an illustrative assumption, not any real company's model.

A small model of the accounting and reconciliation for an issuer of tokens backed 1:1 by listed shares, in Excel and in Python.

## Start here
1. Open `tokenized_equities_ledger.xlsx` and read the README tab, then Recon and Tests, where the three breaks show up in red.
2. Compare with `tokenized_equities_ledger_corrected.xlsx`, where every check clears apart from normal T+1 timing items.
3. The Python version and `recon_report.md` show the same logic as code.

## Result: before and after

<img width="1089" height="318" alt="recon-before" src="https://github.com/user-attachments/assets/276f3af9-f4e5-4eff-803f-06e18ca88021" />

*Before: three breaks flagged on the Recon tab.*


<img width="1067" height="291" alt="recon-after" src="https://github.com/user-attachments/assets/e3c18b86-febf-41cd-ad1e-04f98ff78944" />

*After: corrections posted, every check clears apart from normal T+1 timing.*

## How the tests catch each break

<img width="1174" height="551" alt="tests-before png" src="https://github.com/user-attachments/assets/36823acf-bb1a-4f78-8fb8-d91e11177aca" />

*Each break is caught by a different test: completeness, accuracy and custodian confirmation.*


## Files
| File | What it is |
|---|---|
| `tokenized_equities_ledger.xlsx` | Excel model with live formulas and **three injected breaks** for the controls to find. Start at the README tab. |
| `tokenized_equities_ledger_corrected.xlsx` | The same model after the breaks are corrected (answer key): every reconciliation and test clears, apart from normal T+1 timing items. |
| `tokenized_equities_ledger.py` | The same logic as Python (standard library, SQLite). Run `python3 tokenized_equities_ledger.py`. |
| `recon_report.md` | Output of the Python run: trial balance, three-way reconciliation, transaction-level tests. |

## What it models
- **Issuance:** customer pays cash, tokens are minted on-chain, shares are bought to back them (T+1 settlement), fee income recognised.
- **Redemption:** tokens burned, shares sold, cash returned net of fee.
- **Remeasurement:** shares and token liability both carried at fair value (FVTPL) and remeasured daily.
- **Controls:** every journal must balance; three-way unit reconciliation (on-chain supply vs ledger vs custodian); transaction-level completeness, existence, accuracy, aged-item and custodian-confirmation tests.

## Policy assumptions (illustrative, open to challenge)
- Tokens are financial liabilities at FVTPL; the underlying shares are financial assets at FVTPL (IFRS 9 / IAS 32 judgements).
- The issuer acts as principal and holds the shares on its own balance sheet. If shares are held in trust or as client assets, the entries change materially.
- Fees are recognised at the point of issue and redemption. Synthetic prices, 0.5% fee, T+1 settlement.
- Not modelled: dividends and withholding tax, stock splits and token rebasing, FX (AED/USD), custody fees, bank reconciliation, gas costs.

## Injected breaks (what the controls find)
1. `0xT05`: NVDA mint on-chain and at the custodian, but never posted in the ledger (completeness).
2. `0xT06`: NVDA redemption keyed as 10 tokens instead of 100 (accuracy); this also leaks into the P&L through the fair value remeasurement.
3. `0xT07`: AAPL tokens minted and booked, but the custodian never executed the hedge buy (tokens not fully backed).

## How the breaks are corrected
- `0xT05`: post the missing issuance, hedge and settlement entries.
- `0xT06`: post a correcting entry for the missing 90 tokens under the same reference, keeping the audit trail.
- `0xT07`: find out why the order failed, re-execute the buy, escalate because the tokens were unbacked meanwhile, and book hedges only on custodian confirmation.

## Natural next steps
Add dividends and splits, a rebase event, an FX layer and a bank reconciliation, then write the accounting policy memo that explains each judgement above.

## About
Fahad K V | linkedin.com/in/kvfahad
