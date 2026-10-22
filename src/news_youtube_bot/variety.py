from __future__ import annotations

import random
from dataclasses import dataclass


@dataclass(frozen=True)
class Profile:
    """One distinct edit of the same news format.

    YouTube's inauthentic-content rule allows a recurring shape when the
    substance changes. These profiles change the hook, the spoken shape,
    the voice, the pacing, the caption look, and the music so five videos
    in a day are not the same template with the nouns swapped.
    """

    id: str
    hook_style: str
    structure: str
    cta: str
    edge_voice: str
    openai_voice: str
    rate: str
    music_style: str
    bpm: int
    bg: str
    accent: str
    highlight_bgr: str
    caption_box: bool
    hook_upper: bool
    tts_instructions: str
    openers: tuple[str, ...]
    signoffs: tuple[str, ...]


PROFILES: tuple[Profile, ...] = (
    Profile(
        id="question",
        hook_style="Open with a short question a viewer can answer in their head. No greeting.",
        structure="Question, then the headline as a spoken sentence, then two concrete details from the source, then why that detail is the one to remember, then the sign-off.",
        cta="Point people to the source link. Do not beg for a like.",
        edge_voice="en-US-AndrewMultilingualNeural",
        openai_voice="nova",
        rate="+6%",
        music_style="pulse",
        bpm=104,
        bg="0x101828",
        accent="0x3DFFB0",
        highlight_bgr="&H0000F0FF&",
        caption_box=False,
        hook_upper=False,
        tts_instructions="Talk like a curious friend who reads tech news, not a presenter. Short sentences. Natural contractions. Slight lift on the question, then settle.",
        openers=("Seen this yet?", "Did this hit your feed too?", "Quick question, then the details."),
        signoffs=(
            "That's the reporting from {outlet}, not an extra scoop from me.",
            "I'm sticking to what {outlet} published. The link is below.",
        ),
    ),
    Profile(
        id="bold_claim",
        hook_style="State the claim in the first sentence, flat and specific. Then immediately say it is a report, not your own test.",
        structure="Claim, attribution, two supporting details, one limit on what we do not know, sign-off.",
        cta="Invite a disagreement in one line, then send them to the source.",
        edge_voice="en-US-JennyNeural",
        openai_voice="shimmer",
        rate="+12%",
        music_style="drive",
        bpm=122,
        bg="0x1A0E14",
        accent="0xFF5A36",
        highlight_bgr="&H00365AFF&",
        caption_box=True,
        hook_upper=True,
        tts_instructions="Confident and quick, like a creator who has opinions but will not fake certainty. Punch the first sentence, then ease off.",
        openers=("Here's the claim.", "This is the line people will argue about.", "Say it plain."),
        signoffs=(
            "{outlet} has the full piece. I wouldn't add to it.",
            "If you've got a different read, the source is the place to check it.",
        ),
    ),
    Profile(
        id="story",
        hook_style="Start in the middle of the reported event, present tense, then rewind one sentence for context.",
        structure="Mid-action detail, context sentence, what changed, the payoff, sign-off.",
        cta="A calm 'link's in the description' with the outlet name.",
        edge_voice="en-US-GuyNeural",
        openai_voice="onyx",
        rate="+0%",
        music_style="ambient",
        bpm=92,
        bg="0x0E1C24",
        accent="0x7AD0FF",
        highlight_bgr="&H00FFD07A&",
        caption_box=False,
        hook_upper=False,
        tts_instructions="Storyteller pace. Warm, unhurried, still tight. No announcer voice. Leave a little air between sentences.",
        openers=("Start in the middle.", "Here's the moment.", "Picture the scene the article describes."),
        signoffs=(
            "That's the version {outlet} wrote. The link is in the description.",
            "I'm summarizing {outlet}, not stretching it.",
        ),
    ),
    Profile(
        id="stakes",
        hook_style="Open on who is affected in ordinary life, then the news. Do not invent a personal impact that is not in the source.",
        structure="Who it touches, what happened, the concrete change, what is still unknown, sign-off.",
        cta="Tell viewers to read the source before they repeat it.",
        edge_voice="en-US-AriaNeural",
        openai_voice="nova",
        rate="+8%",
        music_style="pulse",
        bpm=112,
        bg="0x141018",
        accent="0xC9A4FF",
        highlight_bgr="&H00FFA4C9&",
        caption_box=False,
        hook_upper=False,
        tts_instructions="Direct and practical. Sound like someone explaining a change to a smart friend. No hype words.",
        openers=(
            "This one leaves the press release and hits products.",
            "Here's why a normal user would notice.",
            "Skip the branding. Here's the change.",
        ),
        signoffs=(
            "That's as far as {outlet} goes. Worth reading before you repeat it.",
            "The link below is {outlet}. I'm not adding claims on top.",
        ),
    ),
    Profile(
        id="myth",
        hook_style="Tell the viewer the headline is doing too much work, then give the narrower fact from the summary.",
        structure="Caution about the headline, the narrower fact, a second detail, what is not confirmed, sign-off.",
        cta="Ask them to check the source, not to smash subscribe.",
        edge_voice="en-US-BrianNeural",
        openai_voice="echo",
        rate="+14%",
        music_style="drive",
        bpm=128,
        bg="0x181208",
        accent="0xFFC857",
        highlight_bgr="&H0057C8FF&",
        caption_box=True,
        hook_upper=False,
        tts_instructions="Skeptical but not cynical. Faster pace. Stress the correction, not the outrage.",
        openers=(
            "Read past the headline on this one.",
            "The headline is doing a lot of work.",
            "Ignore the adjective. Keep the fact.",
        ),
        signoffs=(
            "What I just said is {outlet}'s account, trimmed. Full piece below.",
            "If the headline and the article disagree, trust the article. Link's below.",
        ),
    ),
    Profile(
        id="newsroom",
        hook_style="A two-word briefing open, then the headline, then facts in a clean order. No slang.",
        structure="Briefing line, headline, what happened, the number or name that matters, what happens next only if the source says so, sign-off.",
        cta="Offer the source as the briefing packet.",
        edge_voice="en-GB-SoniaNeural",
        openai_voice="fable",
        rate="-4%",
        music_style="ambient",
        bpm=96,
        bg="0x121416",
        accent="0xE8EEF2",
        highlight_bgr="&H00F2EEE8&",
        caption_box=True,
        hook_upper=False,
        tts_instructions="Calm British briefing voice. Clear consonants. Not posh-cartoon, not sleepy. Measured pace.",
        openers=("Quick briefing.", "Here's the desk version.", "Short version."),
        signoffs=(
            "That's the briefing from {outlet} as of today.",
            "{outlet} has the rest. I kept this to the part that fits a minute.",
        ),
    ),
    Profile(
        id="one_number",
        hook_style="If the headline has a number, lead with that number. If it does not, say so and lead with the concrete noun.",
        structure="Number or noun, what it measures, the surrounding fact, the limit of the reporting, sign-off.",
        cta="Send them to the source for the table or the quote.",
        edge_voice="en-US-EmmaNeural",
        openai_voice="alloy",
        rate="+10%",
        music_style="pulse",
        bpm=118,
        bg="0x08141C",
        accent="0x5CE1FF",
        highlight_bgr="&H00FFE15C&",
        caption_box=False,
        hook_upper=True,
        tts_instructions="Crisp and bright. Hit numbers cleanly. Do not sound like an ad.",
        openers=(
            "The number is the story.",
            "No giant number. The noun matters.",
            "Hold onto one figure.",
        ),
        signoffs=(
            "The figure comes from {outlet}'s piece, which is linked below.",
            "I'm not rounding this into a bigger claim. {outlet} has the context.",
        ),
    ),
    Profile(
        id="so_what",
        hook_style="Open with 'so what does this change', then answer only with what the source supports.",
        structure="So-what question, the change, one example from the source, the open question, sign-off.",
        cta="Ask what they think it means, and point at the source.",
        edge_voice="en-AU-WilliamNeural",
        openai_voice="onyx",
        rate="+5%",
        music_style="drive",
        bpm=108,
        bg="0x101610",
        accent="0xB6F25C",
        highlight_bgr="&H005CF2B6&",
        caption_box=False,
        hook_upper=False,
        tts_instructions="Australian conversational. Relaxed, sharp, a little dry. No corporate warmth.",
        openers=(
            "So what does this actually change?",
            "Here's the part that matters after the headline.",
            "Forget the launch adjectives.",
        ),
        signoffs=(
            "That's my read of {outlet}, and the link is there if you want to check me.",
            "Curious what you take from it. The {outlet} piece is below.",
        ),
    ),
)


def assign_profiles(count: int, seed: str) -> list[Profile]:
    """Stable for a given day, different across videos, never the same profile twice in a row."""
    if count <= 0:
        return []
    rng = random.Random(seed)
    order = list(PROFILES)
    rng.shuffle(order)
    picked: list[Profile] = []
    while len(picked) < count:
        batch = order[:]
        rng.shuffle(batch)
        if picked and batch[0].id == picked[-1].id:
            batch.append(batch.pop(0))
        picked.extend(batch)
    return picked[:count]


def profile_by_id(profile_id: str) -> Profile:
    for profile in PROFILES:
        if profile.id == profile_id:
            return profile
    return PROFILES[0]
