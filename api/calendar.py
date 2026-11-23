from datetime import date, datetime
from zoneinfo import ZoneInfo
import nepali_datetime as nd
from fastapi import HTTPException


def today():
    return datetime.now(ZoneInfo("Asia/Kathmandu")).date()


def fiscal_year(day: date):
    bs = nd.date.from_datetime_date(day)
    start = bs.year if bs.month >= 4 else bs.year - 1
    return f"{start}/{str(start + 1)[-2:]}"


def calendar_info(value: str, calendar: str = "ad"):
    try:
        if calendar not in {"ad", "bs"}:
            raise ValueError("Choose ad or bs")
        parts = [int(x) for x in value.split("-")]
        ad = nd.date(*parts).to_datetime_date() if calendar == "bs" else date(*parts)
        bs = nd.date.from_datetime_date(ad)
        return {"ad": ad.isoformat(), "bs": bs.isoformat(), "fiscal_year": fiscal_year(ad), "timezone": "Asia/Kathmandu"}
    except (ValueError, OverflowError, TypeError):
        raise HTTPException(422, "Date is invalid or outside the supported BS calendar range (1975–2100 BS)")
