import pandas as pd
import streamlit as st
from core.config import MARKETS
from core.universes import load, normalize
from core.data import cap, history, completed
from core.historical import indicators, records, calculate_historical_study_summary
VERSION="high_low_outcomes_v2"

def render(market):
    cfg=MARKETS[market]
    st.title(f"{market} Historical Filter Study")
    st.caption("Research prototype — not investment advice. Current constituents and current market-cap eligibility; not a point-in-time universe.")
    st.info("Universe: "+" + ".join(cfg["groups"])+f". Strict current market cap > {cfg['threshold']:,.0f} {cfg['currency']}.")
    with st.expander("Strategy and outcome definitions"):
        st.write("Volume > 1.5 × 5-day mean including signal day; close/open return > 2%; close > daily SMA20 and SMA200; completed weekly close > weekly SMA20; ATR14/close > 3%; daily RSI14 55–90 inclusive; weekly RSI14 ≥55; close > previous two daily closes.")
        st.write("Seven years of adjusted prices provide warm-up; only five years of signal dates are retained. Daily/weekly data must be completed. Entry is next available completed daily adjusted CLOSE, not next-day open.")
        st.write("Maximum return uses the highest adjusted DAILY HIGH in the N sessions AFTER entry. Minimum return uses the lowest adjusted DAILY LOW in the same window. Entry-day highs/lows are excluded. A 10% hit means that future high reached at least 10% above entry; it is not an end-of-window return or an executed trade.")
        st.write("Only full future windows count as completed. Minimum returns are shown for 30d, 60d, 90d, 6m and 12m, matching the Indian study. Months use 126/189/252 sessions. Pending entries and incomplete windows stay blank.")
        st.write("Current-constituent selection introduces survivorship bias. Repeated/overlapping signals are not independent trades. No costs, tax or slippage. GBP/pence market-cap scale is validated, not inferred blindly.")
    if st.sidebar.button("Clear data cache"):
        st.cache_data.clear(); st.success("Data cache cleared; run again to replace saved results.")
    upload=st.file_uploader("Optional verified universe CSV (symbol,name,group; optional yahoo_symbol)",type="csv",key=f"upload_{market}")
    if st.button("Load / refresh universe",key=f"load_{market}"):
        try:
            if upload is not None:
                u=normalize(pd.read_csv(upload),market)
                report=pd.DataFrame([{"source":"User CSV — completeness not independently verified"}])
            else: u,report=load(market)
            st.session_state[f"universe_{market}"]=(u,report)
            st.session_state.pop(f"result_{market}",None)
        except Exception as e: st.error(f"Universe load failed: {type(e).__name__}: {e}")
    saved=st.session_state.get(f"universe_{market}")
    if saved is None:
        st.info("Load the universe first."); return
    u,report=saved
    st.write(f"Loaded {len(u):,} unique listings. Validate source counts before running.")
    st.dataframe(report,hide_index=True)
    with st.expander("Universe audit"):
        st.dataframe(u,hide_index=True)
        st.download_button("Download universe CSV",u.to_csv(index=False),f"{market}_universe.csv")
    limit=st.selectbox("Stocks to evaluate",[20,50,100,"All"],key=f"limit_{market}")
    st.caption("Limited scans use alphabetical ticker order, not a representative sample. Select All for the loaded full universe.")
    if st.button("Run five-year study",type="primary",key=f"run_{market}"):
        selected=u.sort_values("ticker") if limit=="All" else u.sort_values("ticker").head(int(limit))
        frames=[]; diagnostic_rows=[]; audits=[]
        bar=st.progress(0); status=st.empty()
        for pos,(_,stock) in enumerate(selected.iterrows(),1):
            detail={"ticker":stock.ticker,"name":stock["name"],"group":stock.group}
            try:
                status.write(f"{pos}/{len(selected)} — {stock.ticker}")
                value,note=cap(stock.ticker,market)
                detail.update(market_cap=value,currency=cfg["currency"],cap_note=note)
                if value<=cfg["threshold"]:
                    detail.update(status="Below or equal to market-cap threshold",signals=0)
                else:
                    d,sched=completed(history(stock.ticker),market)
                    if len(d)<200: raise ValueError(f"Insufficient completed price rows: {len(d)}")
                    d=indicators(d,sched); r=records(d,stock,value)
                    if not r.empty: frames.append(r)
                    detail.update(status="Signals found" if len(r) else "No matching signal",signals=len(r),daily_rows=len(d))
                    a=d.iloc[-1].to_dict(); a.update(ticker=stock.ticker,date=d.index[-1]); audits.append(a)
            except Exception as e:
                detail.update(status="Error / unavailable data",signals=0,reason=f"{type(e).__name__}: {e}")
            diagnostic_rows.append(detail); bar.progress(pos/len(selected))
        bar.empty(); status.empty()
        combined=pd.concat(frames,ignore_index=True).sort_values("signal_date",ascending=False) if frames else pd.DataFrame()
        st.session_state[f"result_{market}"]=(combined,pd.DataFrame(diagnostic_rows),pd.DataFrame(audits),pd.Timestamp.now(tz="UTC").isoformat())
        st.session_state[f"outcome_version_{market}"]=VERSION
    snapshot=st.session_state.get(f"result_{market}")
    if snapshot is None: return
    if st.session_state.get(f"outcome_version_{market}")!=VERSION:
        st.warning("Saved results use the previous closing-price outcome calculation. Click Run five-year study again to generate high/low outcomes. Old results are not relabelled.")
        return
    results,diagnostics,audits,stamp=snapshot
    st.caption(f"Saved {market} scan — {stamp}. Changing controls does not change this snapshot until Run is clicked.")
    if results.empty:
        st.warning("Scan completed without signal records. Review every-stock diagnostics below.")
    else:
        summary=calculate_historical_study_summary(results)
        c1,c2,c3,c4=st.columns(4)
        c1.metric("Signal records",summary["total_signal_records"])
        c2.metric("Unique stocks",summary["unique_stocks"])
        c3.metric("Pending entries",summary["pending_entries"])
        c4.metric("Stocks attempted",len(diagnostics))
        st.subheader("Forward Outcome Summary")
        hs=summary["horizon_summary"]
        fmt={c:"{:.2f}%" for c in hs if c not in ["Horizon","Completed Signals"]}
        st.dataframe(hs.style.format(fmt,na_rep="NA"),hide_index=True)
        st.caption("Completed Signals counts full forward windows, not just completed entries. 10% Hit Rate is based on future highs, not the return at the end of the window.")
        st.download_button("Download forward outcome summary",hs.to_csv(index=False),f"{market}_forward_outcomes.csv")
        st.subheader("Historical Signals by Year")
        ys=summary["year_summary"]
        formats={c:"{:.2f}%" for c in ys if c not in ["signal_year","total_signal_records","unique_stocks"]}
        st.dataframe(ys.style.format(formats,na_rep="NA"),hide_index=True)
        st.caption("Year is the signal year. Total signals includes pending entries; 30/60-day statistics exclude incomplete windows separately.")
        st.download_button("Download historical signals by year",ys.to_csv(index=False),f"{market}_signals_by_year.csv")
        st.subheader("Individual Historical Signal Records")
        st.dataframe(results,hide_index=True)
        st.download_button("Download individual signal records",results.to_csv(index=False),f"{market}_signals.csv")
    st.subheader("Every-stock diagnostics")
    st.dataframe(diagnostics,hide_index=True)
    st.download_button("Download diagnostics",diagnostics.to_csv(index=False),f"{market}_diagnostics.csv")
    st.subheader("Latest completed candle — condition audit")
    st.dataframe(audits,hide_index=True)
