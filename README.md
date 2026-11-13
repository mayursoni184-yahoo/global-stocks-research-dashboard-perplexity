# Global Historical Filter Study — research prototype

## Deploy separately from India
1. Create a NEW GitHub repository. Do not overwrite the Indian project.
2. Upload this folder's CONTENTS (app.py and requirements.txt at repository root; core/ alongside).
3. In Streamlit Community Cloud choose New app, select that repository and app.py.
4. Python 3.11 or 3.12 is recommended. Install requirements.txt.
5. Load the US universe, validate the counts/source timestamps, run 20 stocks, then repeat for UK.
6. Only after inspecting diagnostics select All. Full sequential scans may be slow or hit provider limits.

Local: `pip install -r requirements.txt` then `streamlit run app.py`.

## Scope
US: Nasdaq-100 + Dow. UK: FTSE100 + FTSE250 + FTSE AIM All-Share.
This is NOT all Nasdaq listings, all NYSE stocks, or the entire LSE Main Market/AIM.
Strict current cap > USD500m or GBP300m. No bypass for missing cap.
Seven years of input support warm-up; last five years of signal dates are shown.
Current membership/capitalisation creates selection and survivorship bias; not point-in-time research.
Adjusted prices are used. Currency conversion other than validated GBP/pence scaling is not implemented.
No historical cap series or former/delisted members are included.

## Universe sourcing
Automatic HTML tables: Slickcharts Nasdaq100/Dow and Barclays Research Centre FTSE100/250/AIM All-Share.
These are third-party sources; membership correctness and completeness are NOT guaranteed.
Every required group must load; minimum-count checks reject obvious partial tables but cannot prove completeness.
No embedded stale/sample constituent list or silent fallback is supplied.
If blocked/paginated or changed, use a verified CSV containing ALL members of all required groups.
Required columns: symbol,name,group. Optional yahoo_symbol resolves ticker aliases.
Group values must be EXACT: Nasdaq-100, Dow (US); FTSE 100, FTSE 250, FTSE AIM All-Share (UK).
Repeat a row with a different group for shared members; duplicates collapse for scanning.
UK symbols receive .L automatically; override via yahoo_symbol where necessary.
CSV completeness is the uploader's responsibility; the app checks group presence, not index membership.
Public data access, redistribution terms and Yahoo terms must be reviewed for your intended use.

## Correctness notes
Original calculate_rsi and calculate_atr_series are reused from supplied app-1.py.
Volume SMA includes the signal day; candle change means close/open, not prior close.
Weekly values release only after the final scheduled weekly exchange session.
Incomplete daily bars are excluded using exchange_calendars; US uses XNYS sessions as a Nasdaq/Dow cash-equity calendar proxy.
Entry is the next observed completed daily adjusted CLOSE. A latest-row signal stays pending.
Horizon N means N trading observations AFTER entry; no incomplete-horizon values are fabricated.
Maximum returns are closing-price maxima, not intraday highs. No execution costs or portfolio simulation.
Unavailable market caps/currencies are diagnostic exclusions. Never infer cap units from price units alone.
For UK GBp quotes, shares times price validates raw vs divided-by-100 cap (20% tolerance); failures are excluded.
Financial reporting currency is NOT used as proof of market-cap currency.

## Validation status
Python compilation and offline synthetic checks performed during generation (see validation.json).
No live downloads, live universe parsing, deployment, or end-to-end Streamlit execution were possible in the build environment.
Test counts, symbols, cap eligibility and several signal dates manually before using output.
