"""慣性設定: how much the wheel's scrolling and zooming glide, and the glide after a middle-button drag. One amount
for everything (全局) or one for each kind of motion (分開設定). An amount is a percent: 100 is as the program was made
(a notch settles in about 0.2 s, the half-life BASE_MS), 0 is no glide (the motion is made at once), more is longer.
Saved in the program's settings (load / save); the views ask `percent(channel)` each time they move."""

BASE_MS = 55.0
MAX_PERCENT = 400
DEFAULT = 100

CHANNELS = (("scroll", "一般捲動（面板、清單）"), ("timeline_scroll", "時間線捲動"), ("timeline_zoom", "時間線縮放"),
            ("preview_zoom", "預覽縮放"), ("node_zoom", "節點編輯器縮放"), ("drag", "拖曳放開後的慣性（中鍵）"))

state = {"separate": False, "all": DEFAULT, **{key: DEFAULT for key, _name in CHANNELS}}


def percent(channel):
    return state[channel] if state["separate"] else state["all"]


def half_life_ms(channel):
    """The half-life of the glide, 0 when there is none."""
    return BASE_MS * percent(channel) / 100.0


def load(settings):
    def number(key, default):
        try:
            return max(0, min(MAX_PERCENT, int(settings.value("inertia_" + key, default))))
        except (TypeError, ValueError):
            return default
    state["separate"] = str(settings.value("inertia_separate", False)).lower() in ("true", "1")
    state["all"] = number("all", DEFAULT)
    for key, _name in CHANNELS:
        state[key] = number(key, state["all"])


def save(settings):
    settings.setValue("inertia_separate", state["separate"])
    settings.setValue("inertia_all", state["all"])
    for key, _name in CHANNELS:
        settings.setValue("inertia_" + key, state[key])
