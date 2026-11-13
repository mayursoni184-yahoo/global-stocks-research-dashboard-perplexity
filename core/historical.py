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
    sessions=pd.DatetimeIndex(schedule.index).tz_localize(None).normalize()
    last=pd.Series(sessions,index=sessions).groupby(sessions.to_period("W-FRI")).max()
    w["release"]=last.reindex(w.index.to_period("W-FRI")).to_numpy()
    w["weekly_sma_20"]=w.close.rolling(20).mean()
    w["weekly_rsi_14"]=calculate_rsi(w.close,14)
    features=w[["release","close","weekly_sma_20","weekly_rsi_14"]].rename(columns={"close":"weekly_close"}).dropna(subset=["release"])
    joined=pd.merge_asof(pd.DataFrame({"date":d.index}),features.sort_values("release"),left_on="date",right_on="release",direction="backward").set_index("date")
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

def calculate_window_metrics_vectorized(data, entry_indexes, window_days, include_minimum):
    max_returns = []
    min_returns = []
    hit_10pct = []
    high_values = data["high"].to_numpy(dtype=float)
    low_values = data["low"].to_numpy(dtype=float)
    close_values = data["close"].to_numpy(dtype=float)
    total_rows = len(data)
    for entry_index in entry_indexes:
        final_index = entry_index + window_days
        if final_index >= total_rows:
            max_returns.append(np.nan)
            min_returns.append(np.nan)
            hit_10pct.append(pd.NA)
            continue
        entry_price = close_values[entry_index]
        future_highs = high_values[entry_index + 1:final_index + 1]
        max_return = (np.max(future_highs) / entry_price - 1) * 100
        max_returns.append(max_return)
        hit_10pct.append(bool(max_return >= 10))
        if include_minimum:
            future_lows = low_values[entry_index + 1:final_index + 1]
            min_return = (np.min(future_lows) / entry_price - 1) * 100
            min_returns.append(min_return)
        else:
            min_returns.append(np.nan)
    return max_returns, min_returns, hit_10pct

def records(d, stock, market_cap):
    cutoff=pd.Timestamp.now(tz="UTC").tz_localize(None).normalize()-pd.DateOffset(years=5)
    signal_indexes=np.flatnonzero((d.all_filters_pass & (d.index>=cutoff)).to_numpy())
    rows=[]
    for i in signal_indexes:
        entry=i+1; pending=entry>=len(d)
        row={"ticker":stock.ticker,"name":stock["name"],"group":stock.group,
             "signal_date":d.index[i],"signal_day_price":d.close.iloc[i],
             "entry_status":"Pending Next Trading Day" if pending else "Completed Historical Entry",
             "entry_date":pd.NaT if pending else d.index[entry],
             "entry_price":np.nan if pending else d.close.iloc[entry],
             "current_market_cap":market_cap,
             "daily_candle_return_pct":d.daily_candle_return_pct.iloc[i],
             "volume_ratio_vs_5d_sma":d.volume.iloc[i]/d.volume_sma_5.iloc[i],
             "daily_rsi_14":d.daily_rsi_14.iloc[i],
             "weekly_rsi_14":d.weekly_rsi_14.iloc[i],
             "atr_14_pct_of_close":d.atr_pct.iloc[i]}
        rows.append(row)
    result=pd.DataFrame(rows)
    if result.empty: return result
    entries=signal_indexes+1
    valid=entries<len(d)
    positions=np.flatnonzero(valid)
    for label,n in WINDOWS.items():
        include_min=label in ["30d","60d","90d","6m","12m"]
        maxima,minima,hits=calculate_window_metrics_vectorized(d,entries[valid],n,include_min)
        a=np.full(len(result),np.nan); b=a.copy(); terminal=a.copy()
        hit_values=[pd.NA]*len(result)
        for pos,mx,mn,hit in zip(positions,maxima,minima,hits):
            a[pos]=mx; b[pos]=mn; hit_values[pos]=hit
            e=entries[pos]
            if e+n<len(d): terminal[pos]=(d.close.iloc[e+n]/d.close.iloc[e]-1)*100
        result["max_ret_"+label]=a
        result["hit_10pct_"+label]=pd.array(hit_values,dtype="boolean")
        result["ret_"+label]=terminal
        if include_min: result["min_ret_"+label]=b
    return result

def calculate_historical_study_summary(results):
    results = results.rename(columns={"ticker": "stock_symbol"}) if "stock_symbol" not in results.columns else results
    if results is None or results.empty:
        return {
            "total_signal_records": 0,
            "unique_stocks": 0,
            "unique_stock_months": 0,
            "unique_stock_quarters": 0,
            "consecutive_signal_records": 0,
            "pending_entries": 0,
            "latest_signal_date": None,
            "horizon_summary": pd.DataFrame(),
            "year_summary": pd.DataFrame(),
        }
    working = results.copy()
    working["signal_date"] = pd.to_datetime(working["signal_date"])
    working["signal_year"] = working["signal_date"].dt.year
    working["signal_month"] = working["signal_date"].dt.to_period("M").astype(str)
    working["signal_quarter"] = working["signal_date"].dt.to_period("Q").astype(str)
    pending_entries = working[working["entry_status"] == "Pending Next Trading Day"].shape[0]
    latest_signal_date = working["signal_date"].max() if not working.empty else None
    unique_stock_months = working[["stock_symbol", "signal_month"]].drop_duplicates().shape[0]
    unique_stock_quarters = working[["stock_symbol", "signal_quarter"]].drop_duplicates().shape[0]
    consecutive_records = 0
    for _, group in working.groupby("stock_symbol"):
        dates = group.sort_values("signal_date")["signal_date"].tolist()
        for index in range(1, len(dates)):
            if (dates[index] - dates[index - 1]).days <= 4:
                consecutive_records += 1
    horizon_config = [
        ("5 Trading Days", "max_ret_5d", None, "hit_10pct_5d"),
        ("10 Trading Days", "max_ret_10d", None, "hit_10pct_10d"),
        ("20 Trading Days", "max_ret_20d", None, "hit_10pct_20d"),
        ("30 Trading Days", "max_ret_30d", "min_ret_30d", "hit_10pct_30d"),
        ("60 Trading Days", "max_ret_60d", "min_ret_60d", "hit_10pct_60d"),
        ("90 Trading Days", "max_ret_90d", "min_ret_90d", "hit_10pct_90d"),
        ("6 Months", "max_ret_6m", "min_ret_6m", "hit_10pct_6m"),
        ("9 Months", "max_ret_9m", None, "hit_10pct_9m"),
        ("12 Months", "max_ret_12m", "min_ret_12m", "hit_10pct_12m"),
    ]
    horizon_rows = []
    for label, max_column, min_column, hit_column in horizon_config:
        max_values = working[max_column].dropna()
        hit_values = working[hit_column].dropna()
        if min_column is not None:
            min_values = working[min_column].dropna()
            average_min = min_values.mean() if not min_values.empty else None
            median_min = min_values.median() if not min_values.empty else None
        else:
            average_min = None
            median_min = None
        horizon_rows.append({
            "Horizon": label,
            "Completed Signals": len(max_values),
            "Average Max Return %": max_values.mean() if not max_values.empty else None,
            "Median Max Return %": max_values.median() if not max_values.empty else None,
            "Average Min Return %": average_min,
            "Median Min Return %": median_min,
            "10% Hit Rate %": hit_values.mean() * 100 if not hit_values.empty else None,
        })
    horizon_summary = pd.DataFrame(horizon_rows)
    year_summary = (
        working
        .groupby("signal_year")
        .agg(
            total_signal_records=("stock_symbol", "count"),
            unique_stocks=("stock_symbol", "nunique"),
            average_max_ret_30d=("max_ret_30d", "mean"),
            median_max_ret_30d=("max_ret_30d", "median"),
            hit_10pct_30d_rate=("hit_10pct_30d", "mean"),
            average_max_ret_60d=("max_ret_60d", "mean"),
            median_max_ret_60d=("max_ret_60d", "median"),
            hit_10pct_60d_rate=("hit_10pct_60d", "mean"),
        )
        .reset_index()
    )
    if not year_summary.empty:
        year_summary["hit_10pct_30d_rate"] = year_summary["hit_10pct_30d_rate"] * 100
        year_summary["hit_10pct_60d_rate"] = year_summary["hit_10pct_60d_rate"] * 100
    return {
        "total_signal_records": len(working),
        "unique_stocks": working["stock_symbol"].nunique(),
        "unique_stock_months": unique_stock_months,
        "unique_stock_quarters": unique_stock_quarters,
        "consecutive_signal_records": consecutive_records,
        "pending_entries": pending_entries,
        "latest_signal_date": latest_signal_date,
        "horizon_summary": horizon_summary,
        "year_summary": year_summary,
    }
