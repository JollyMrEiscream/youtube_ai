from __future__ import annotations

from pathlib import Path

from news_youtube_bot.media import ass_font_name
from news_youtube_bot.textutil import ass_escape
from news_youtube_bot.tts_render import WordTiming
from news_youtube_bot.variety import Profile


def ass_timestamp(seconds: float) -> str:
    ticks = max(0, int(round(seconds * 100)))
    hours, ticks = divmod(ticks, 360_000)
    minutes, ticks = divmod(ticks, 6_000)
    secs, centis = divmod(ticks, 100)
    return f"{hours}:{minutes:02d}:{secs:02d}.{centis:02d}"


def _groups(words: list[WordTiming], max_chars: int = 28) -> list[list[WordTiming]]:
    groups: list[list[WordTiming]] = []
    current: list[WordTiming] = []
    for word in words:
        trial = " ".join(item.text for item in current + [word])
        if current and len(trial) > max_chars:
            groups.append(current)
            current = [word]
        else:
            current.append(word)
    if current:
        groups.append(current)
    return groups


def _line(group: list[WordTiming], active: int, highlight: str) -> str:
    parts: list[str] = []
    for index, word in enumerate(group):
        token = ass_escape(word.text)
        if index == active:
            parts.append(r"{\c" + highlight + r"}" + token + r"{\c&HFFFFFF&}")
        else:
            parts.append(token)
    return " ".join(parts)


def build_ass(
    words: list[WordTiming],
    profile: Profile,
    font_path: Path,
    hook_text: str,
    *,
    width: int = 1080,
    height: int = 1920,
    caption_start: float = 1.25,
    hook_seconds: float = 2.1,
) -> str:
    font = ass_font_name(font_path)
    border = 3 if profile.caption_box else 1
    outline = 8 if profile.caption_box else 5
    back = "&H78000000" if profile.caption_box else "&H64000000"
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Caption,{font},76,&H00FFFFFF,&H00FFFFFF,&H00000000,{back},-1,0,0,0,100,100,0,0,{border},{outline},0,5,86,86,0,1
Style: Hook,{font},82,&H00FFFFFF,&H00FFFFFF,&H00000000,&H96000000,-1,0,0,0,100,100,0,0,1,8,0,8,80,80,260,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    events: list[str] = []
    hook = hook_text.upper() if profile.hook_upper else hook_text
    if hook and hook_seconds > 0.3:
        events.append(
            f"Dialogue: 1,{ass_timestamp(0)},{ass_timestamp(hook_seconds)},Hook,,0,0,0,,{{\\fad(60,180)}}{ass_escape(hook)}"
        )

    spoken = [word for word in words if word.end > caption_start and word.text.strip()]
    for group in _groups(spoken):
        for index, word in enumerate(group):
            start = max(word.start, caption_start)
            if index + 1 < len(group):
                end = max(group[index + 1].start, start + 0.08)
            else:
                end = max(word.end, start + 0.12)
            if end <= start:
                continue
            text = _line(group, index, profile.highlight_bgr)
            events.append(
                f"Dialogue: 0,{ass_timestamp(start)},{ass_timestamp(end)},Caption,,0,0,0,,{text}"
            )
    return header + "\n".join(events) + "\n"


def write_ass(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
