from __future__ import annotations

from dataclasses import dataclass

from news_youtube_bot.tts_render import WordTiming


@dataclass(frozen=True)
class Beat:
    start: float
    end: float
    text: str

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)


def plan_beats(
    words: list[WordTiming],
    duration: float,
    *,
    min_len: float = 2.0,
    max_len: float = 3.0,
) -> list[Beat]:
    """Cut the voice into shots of about 2–3 seconds, on word boundaries."""
    duration = max(float(duration), 0.1)
    if not words:
        return _even_beats(duration, min_len, max_len)

    beats: list[Beat] = []
    start_index = 0
    start_time = max(0.0, words[0].start)
    while start_index < len(words):
        end_index = start_index
        while end_index < len(words) - 1:
            span = words[end_index].end - start_time
            next_span = words[end_index + 1].end - start_time
            if span >= max_len:
                break
            if span >= min_len and next_span > max_len:
                break
            end_index += 1
        end_time = min(duration, max(words[end_index].end, start_time + 0.2))
        text = " ".join(word.text for word in words[start_index : end_index + 1]).strip()
        beats.append(Beat(start_time, end_time, text))
        start_time = end_time
        start_index = end_index + 1
        if start_time >= duration - 0.05:
            break

    if not beats:
        return _even_beats(duration, min_len, max_len)

    last = beats[-1]
    if last.end < duration:
        beats[-1] = Beat(last.start, duration, last.text)
    if len(beats) >= 2 and beats[-1].duration < 1.2:
        prev = beats[-2]
        tail = beats[-1]
        beats = beats[:-2] + [Beat(prev.start, duration, f"{prev.text} {tail.text}".strip())]
    return _split_long([beat for beat in beats if beat.duration >= 0.2], max_len)


def _split_long(beats: list[Beat], max_len: float) -> list[Beat]:
    """A sparse word list can leave one long beat. Split it so each shot stays near 3s."""
    split: list[Beat] = []
    for beat in beats:
        if beat.duration <= max_len + 0.05:
            split.append(beat)
            continue
        cursor = beat.start
        while beat.end - cursor > max_len + 0.05:
            split.append(Beat(cursor, cursor + max_len, beat.text))
            cursor += max_len
        if beat.end - cursor >= 0.2:
            split.append(Beat(cursor, beat.end, beat.text))
    return split


def _even_beats(duration: float, min_len: float, max_len: float) -> list[Beat]:
    target = min(max_len, max(min_len, 2.5))
    beats: list[Beat] = []
    cursor = 0.0
    while cursor < duration - 0.05:
        end = min(duration, cursor + target)
        if duration - end < min_len * 0.6 and end < duration:
            end = duration
        beats.append(Beat(cursor, end, ""))
        cursor = end
    return beats or [Beat(0.0, duration, "")]
