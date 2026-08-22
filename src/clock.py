"""
Shared clock helper.

CI runners are UTC, but this is an India-market report — every date, month
label and timestamp in the output must be IST or it will be off by 5.5 hours
(and by a whole month when the job runs just after midnight IST on the 1st).
"""

from datetime import datetime
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")


def now_ist() -> datetime:
    """Current time in Asia/Kolkata, regardless of the machine's timezone."""
    return datetime.now(IST)
