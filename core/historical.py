import numpy as np
import pandas as pd
from core.indicators import calculate_rsi, calculate_atr_series
from core.config import WINDOWS

def indicators(d, schedule):
    d=d.copy()
    d["volume_sma_5"]=d.volume.rolling(5).mean()
    d["sma_20"]=d.close.rolling(20).mean()
    d["sma_200"]=d.close.rolling(200).mean()
    d["atr_pct"]=calculate_atr_series(d,14)/d.close*100
    d["daily_rsi_14"]=calculate_rsi(d.close,14)
    d["daily_candle_return_pct"]=(d.close/d.open-1)*100
    w=d.resample("W-FRI").agg({"open":"first","high":"max","low":"min","close":"last","volume":"sum"}).dropna()
    # Only release a weekly feature after the week's last scheduled exchange session.
    sessions=pd.DatetimeIndex(schedule.index).tz_localize(None).normalize()
    last=pd.Series(sessions,index=sessions).groupby(sessions.to_period("W-FRI")).max()
    release=last.reindex(w.index.to_period("W-FRI")).to_numpy()
    w["weekly_sma_20"]=w.close.rolling(20).mean()
    w["weekly_rsi_14"]=calculate_rsi(w.close,14)
    w["release"]=release
    features=w[["release","close","weekly_sma_20","weekly_rsi_14"]].rename(columns={"close":"weekly_close"})
    features=features.dropna(subset=["release"])
    # Current incomplete week has a future release date and cannot match today's row.
    joined=pd.merge_asof(pd.DataFrame({"date":d.index}),features.sort_values("release"),
                         left_on="date",right_on="release",direction="backward").set_index("date")
    for c in ["weekly_close","weekly_sma_20","weekly_rsi_14"]: d[c]=joined[c]
    flags=pd.DataFrame({
      "volume_pass":d.volume>d.volume_sma_5*1.5,
      "candle_pass":d.daily_candle_return_pct>2,
      "sma20_pass":d.close>d.sma_20,
      "sma200_pass":d.close>d.sma_200,
      "weekly_sma_pass":d.weekly_close>d.weekly_sma_20,
      "atr_pass":d.atr_pct>3,
      "daily_rsi_pass":d.daily_rsi_14.between(55,90),
      "weekly_rsi_pass":d.weekly_rsi_14>=55,
      "prior_close_pass":d.close>d.close.shift(1),
      "two_day_close_pass":d.close>d.close.shift(2)},index=d.index)
    d=pd.concat([d,flags],axis=1)
    d["all_filters_pass"]=flags.all(axis=1)
    return d

def records(d, stock, market_cap):
    cutoff=pd.Timestamp.now(tz="UTC").tz_localize(None).normalize()-pd.DateOffset(years=5)
    out=[]
    prices=d.close.to_numpy()
    for i in np.flatnonzero((d.all_filters_pass & (d.index>=cutoff)).to_numpy()):
        entry=i+1; pending=entry>=len(d)
        r={"ticker":stock.ticker,"name":stock['name'],"group":stock.group,
           "signal_date":d.index[i],"entry_status":"Pending Next Trading Day" if pending else "Entered",
           "entry_date":pd.NaT if pending else d.index[entry],
           "entry_price":np.nan if pending else prices[entry],"current_market_cap":market_cap}
        for label,n in WINDOWS.items():
            end=entry+n
            r["ret_"+label]=np.nan if pending or end>=len(d) else (prices[end]/prices[entry]-1)*100
            r["max_ret_"+label]=np.nan if pending or end>=len(d) else (prices[entry+1:end+1].max()/prices[entry]-1)*100
        out.append(r)
    return pd.DataFrame(out)
