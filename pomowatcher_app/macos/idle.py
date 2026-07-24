"""macOSの操作なし時間取得。"""

from Quartz import (
    CGEventSourceSecondsSinceLastEventType,
    kCGAnyInputEventType,
    kCGEventSourceStateCombinedSessionState,
)


def get_idle_ms() -> int:
    seconds = CGEventSourceSecondsSinceLastEventType(
        kCGEventSourceStateCombinedSessionState,
        kCGAnyInputEventType,
    )
    return int(seconds * 1000)
