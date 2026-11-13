import pandas as pd
import streamlit as st
from core.config import MARKETS, WINDOWS
from core.universes import load, normalize
from core.data import cap, history, completed
from core.historical import indicators, records

def render(market):
    cfg=MARKETS[market]
    st.title(f"{market} Historical Filter Study")
    st.caption("Research prototype — not investment advice. Adjusted daily closes; current constituents and current market cap, not a point-in-time historical universe.")
    st.info("Universe: "+" + ".join(cfg["groups"])+f". Strict current market cap > {cfg['threshold']:,.0f} {cfg['currency']}.")
    st.warning("Current-constituent selection creates survivorship/selection bias. Results exclude delisted/former constituents. Yahoo data and public constituent tables require validation.")
    with st.expander("Exact strategy and return definitions"):
        st.write("Volume > 1.5 × 5-day mean (includes signal day); close/open return > 2%; close > daily SMA20 and SMA200; completed weekly close > weekly SMA20; ATR14/close > 3%; daily RSI14 55–90 inclusive; weekly RSI14 ≥55; close > both previous daily closes.")
        st.write("RSI and ATR implementations are retained from the uploaded Indian app. A weekly indicator is only available after the final scheduled session of that week. Seven years are fetched for indicator warm-up; only the latest five years of signals are retained.")
        st.write("Entry is next available completed session adjusted CLOSE, not next-day open. N-day return compares that close with the close N sessions later. Maximum return uses intervening adjusted closes, not intraday highs. Windows without enough future observations stay blank. Costs, tax and slippage are not modelled.")
        st.write("GBP/pence warning: quote currency does not by itself determine market-cap units. GBp market caps are checked against shares × price / 100; ambiguous scales are excluded. This is a sanity check, not a guarantee of provider accuracy.")
    if st.sidebar.button("Clear data cache"):
        st.cache_data.clear(); st.success("Cache cleared. Existing result snapshots remain until you run again.")
    upload=st.file_uploader("Optional verified universe CSV (all required groups; symbol,name,group; optional yahoo_symbol)",type="csv",key=f"upload_{market}")
    st.caption("Automatic retrieval is attempted for every required group. If a source blocks requests or returns an incomplete table, scanning stops—there is no small fallback universe. CSV overrides are user-supplied and are not independently verified.")
    if st.button("Load / refresh universe",key=f"load_{market}"):
        try:
            if upload is not None:
                u=normalize(pd.read_csv(upload),market)
                report=pd.DataFrame([{"source":"User CSV — completeness not independently verified","retrieved_utc":pd.Timestamp.now(tz="UTC").isoformat()}])
            else: u,report=load(market)
            st.session_state[f"universe_{market}"]=(u,report)
            # A changed universe must not retain a misleading previous result snapshot.
            st.session_state.pop(f"result_{market}",None)
        except Exception as e: st.error(f"Universe load failed: {type(e).__name__}: {e}")
    saved=st.session_state.get(f"universe_{market}")
    if saved is None:
        st.info("Load the universe first. See README for source and CSV instructions."); return
    u,report=saved
    st.write(f"Loaded {len(u):,} unique listings. Validate source counts before running.")
    st.dataframe(report,hide_index=True)
    with st.expander("Universe audit"):
        st.dataframe(u,hide_index=True)
        st.download_button("Download universe CSV",u.to_csv(index=False),f"{market}_universe.csv")
    limit=st.selectbox("Stocks to evaluate",[20,50,100,"All"],key=f"limit_{market}")
    st.caption("Test scans use alphabetical ticker order, not a representative sample. Select All for the entire loaded universe.")
    if st.button("Run five-year study",type="primary",key=f"run_{market}"):
        selected=u.sort_values("ticker") if limit=="All" else u.sort_values("ticker").head(int(limit))
        results=[]; diagnostics=[]; audits=[]
        bar=st.progress(0); status=st.empty()
        for pos,(_,stock) in enumerate(selected.iterrows(),1):
            detail={"ticker":stock.ticker,"name":stock['name'],"group":stock.group}
            try:
                status.write(f"{pos}/{len(selected)} — {stock.ticker}")
                value,note=cap(stock.ticker,market)
                detail.update(market_cap=value,currency=cfg["currency"],cap_note=note)
                if value<=cfg["threshold"]:
                    detail.update(status="Below or equal to market-cap threshold",signals=0)
                else:
                    d,sched=completed(history(stock.ticker),market)
                    if len(d)<200: raise ValueError(f"Insufficient completed price rows: {len(d)}")
                    d=indicators(d,sched)
                    r=records(d,stock,value)
                    if not r.empty: results.append(r)
                    detail.update(status="Signals found" if len(r) else "No matching signal",signals=len(r),daily_rows=len(d))
                    a=d.iloc[-1].to_dict(); a.update(ticker=stock.ticker,date=d.index[-1])
                    audits.append(a)
            except Exception as e:
                detail.update(status="Error / unavailable data",signals=0,reason=f"{type(e).__name__}: {e}")
            diagnostics.append(detail); bar.progress(pos/len(selected))
        bar.empty(); status.empty()
        combined=pd.concat(results,ignore_index=True).sort_values("signal_date",ascending=False) if results else pd.DataFrame()
        st.session_state[f"result_{market}"]=(combined,pd.DataFrame(diagnostics),pd.DataFrame(audits),pd.Timestamp.now(tz="UTC").isoformat())
    saved_result=st.session_state.get(f"result_{market}")
    if saved_result is None: return
    results,diagnostics,audits,stamp=saved_result
    st.caption(f"Saved {market} scan snapshot — {stamp}; current controls do not change it until Run is clicked.")
    c1,c2,c3=st.columns(3)
    c1.metric("Attempted",len(diagnostics)); c2.metric("Signal records",len(results))
    c3.metric("Stocks with signals",results.ticker.nunique() if not results.empty else 0)
    st.subheader("Historical signals")
    if results.empty: st.warning("Scan completed without signal records. Review diagnostics below.")
    else:
        st.dataframe(results,hide_index=True)
        st.download_button("Download signal records",results.to_csv(index=False),f"{market}_signals.csv")
        summary=[]
        for label in WINDOWS:
            v=results["ret_"+label].dropna()
            summary.append(dict(horizon=label,completed_records=len(v),mean_return_pct=v.mean(),median_return_pct=v.median(),positive_pct=(v>0).mean()*100 if len(v) else None))
        st.subheader("Forward-return statistics")
        st.caption("Overlapping daily signals are not independent trades; these figures are signal statistics, not a portfolio backtest.")
        st.dataframe(pd.DataFrame(summary),hide_index=True)
    st.subheader("Every-stock diagnostics")
    st.dataframe(diagnostics,hide_index=True)
    st.download_button("Download diagnostics",diagnostics.to_csv(index=False),f"{market}_diagnostics.csv")
    st.subheader("Latest completed candle — condition audit")
    st.caption("Includes technically evaluated market-cap-eligible stocks even when they fail the filter.")
    st.dataframe(audits,hide_index=True)
