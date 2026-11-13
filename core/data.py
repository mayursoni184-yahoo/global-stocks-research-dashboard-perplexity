import numpy as np
import pandas as pd
import yfinance as yf
import streamlit as st
import exchange_calendars as xcals
from core.config import MARKETS
@st.cache_data(ttl=86400, show_spinner=False)
def calendar_sessions(market, start, end):
    cal=xcals.get_calendar(MARKETS[market]["calendar"], start=start, end=end)
    schedule=cal.schedule.loc[start:end]
    return schedule
@st.cache_data(ttl=3600, show_spinner=False)
def history(ticker):
    start=(pd.Timestamp.now(tz="UTC")-pd.DateOffset(years=7)).date()
    d=yf.Ticker(ticker).history(start=str(start), interval="1d",auto_adjust=True,raise_errors=True)
    if d.empty: raise ValueError("No daily price history")
    d=d.rename(columns=str.lower)
    d.index=pd.DatetimeIndex(d.index).tz_localize(None).normalize()
    d=d[~d.index.duplicated(keep="last")].sort_index()
    return d[["open","high","low","close","volume"]].dropna()
def completed(d, market):
    now=pd.Timestamp.now(tz="UTC")
    start=str(d.index.min().date()); end=str((now+pd.Timedelta(days=14)).date())
    sched=calendar_sessions(market,start,end)
    ix=pd.DatetimeIndex(sched.index).tz_localize(None).normalize()
    closes=pd.to_datetime(sched["close"],utc=True)
    valid=ix[(closes<=now).to_numpy()]
    return d.loc[d.index.isin(valid)].copy(), sched
@st.cache_data(ttl=21600, show_spinner=False)
def cap(ticker, market):
    info=yf.Ticker(ticker).get_info()
    if not info: raise ValueError("No fundamentals returned")
    kind=info.get("quoteType")
    if kind and kind!="EQUITY": raise ValueError(f"Unsupported instrument type: {kind}")
    raw=info.get("marketCap")
    if raw is None or not np.isfinite(float(raw)) or float(raw)<=0:
        raise ValueError("Market cap unavailable")
    raw=float(raw); quote=info.get("currency")
    expected=MARKETS[market]["currency"]
    if quote==expected:
        return raw, f"Provider marketCap; quote currency {quote}; current snapshot"
    if market=="UK" and quote in ("GBp","GBX"):
        # Quote unit does NOT establish the unit of the provider's marketCap.
        price=info.get("currentPrice") or info.get("regularMarketPrice")
        shares=info.get("sharesOutstanding")
        if not price or not shares: raise ValueError("GBp quote: need price and shares to validate market-cap scale")
        estimate=float(price)/100*float(shares)
        if estimate<=0: raise ValueError("Invalid shares/price for GBP validation")
        if abs(raw/estimate-1)<0.2:
            return raw,"GBP marketCap scale validated against GBp price × shares / 100 (20% tolerance)"
        if abs((raw/100)/estimate-1)<0.2:
            return raw/100,"Provider marketCap pence scale validated against shares; converted to GBP"
        raise ValueError("Ambiguous marketCap scale: disagrees with GBp price × shares / 100")
    raise ValueError(f"Unsupported or missing quote currency {quote!r}; no automatic FX conversion")
