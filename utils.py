"""Utility functions for PoloSeek bot"""
from datetime import datetime, timezone
from config import CDT

def ensure_cdt_timezone(dt: datetime) -> datetime:
    """Ensure datetime is in CDT timezone"""
    if dt.tzinfo is None:
        # naive datetime - assume it's UTC from SQLite CURRENT_TIMESTAMP and convert to CDT
        return dt.replace(tzinfo=timezone.utc).astimezone(CDT)
    elif dt.tzinfo == timezone.utc:
        # UTC datetime - convert to CDT
        return dt.astimezone(CDT)
    else:
        # aware datetime - convert to CDT
        return dt.astimezone(CDT)

def parse_datetime_input(time_str: str, reference_date: datetime = None) -> datetime:
    """Parse datetime input from user (supports various formats)"""
    if reference_date is None:
        reference_date = datetime.now(CDT)
    
    time_str = time_str.strip().lower()
    
    # accept a bunch of formats
    formats = [
        "%Y-%m-%d %H:%M",
        "%m/%d/%Y %H:%M",
        "%m/%d %H:%M",
        "%H:%M",
        "%I:%M %p",
        "%I%p",
        "%H"
    ]
    
    for fmt in formats:
        try:
            if fmt in ["%H:%M", "%I:%M %p", "%I%p", "%H"]:
                # time only - use reference date
                parsed_time = datetime.strptime(time_str, fmt).time()
                result = datetime.combine(reference_date.date(), parsed_time)
                return CDT.localize(result)
            elif fmt == "%m/%d %H:%M":
                # month/day with current year
                parsed = datetime.strptime(f"{reference_date.year}/{time_str}", "%Y/%m/%d %H:%M")
                return CDT.localize(parsed)
            else:
                parsed = datetime.strptime(time_str, fmt)
                return CDT.localize(parsed)
        except ValueError:
            continue
    
    raise ValueError(f"Could not parse time: {time_str}")
