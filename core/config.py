MARKETS = {
    "US": dict(currency="USD", threshold=500_000_000, calendar="XNYS",
               groups=["Nasdaq-100", "Dow"]),
    "UK": dict(currency="GBP", threshold=300_000_000, calendar="XLON",
               groups=["FTSE 100", "FTSE 250", "FTSE AIM All-Share"]),
}
WINDOWS = {"5d":5,"10d":10,"20d":20,"30d":30,"60d":60,"90d":90,
           "6m":126,"9m":189,"12m":252}
