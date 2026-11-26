"""Prompt templates for the audio judge.

Every yes/no question comes as a counterfactual pair: a POSITIVE phrasing (YES means the
property holds) and a NEGATED phrasing (YES means it does not). Asking both and averaging
cancels most of the audio-LLM "yes bias", and a large disagreement between the two
naturally lands the stem in the UNCERTAIN band. This mirrors the 제외형(counterfactual)
question idea from the team's paper 2.

Prompts are in English because Qwen3-Omni follows English instructions most reliably; the
target description may be in any language.
"""

from __future__ import annotations

ANSWER_FORMAT = (
    "Reply in exactly two lines.\n"
    "Line 1: YES or NO (one word, uppercase).\n"
    "Line 2: one short sentence of evidence (what you heard and when)."
)

SYSTEM = (
    "You are a meticulous audio quality inspector for a source-separation pipeline. "
    "Listen carefully to every audio you are given, including very quiet passages, and "
    "answer strictly from what is audible. Do not guess from the description alone."
)

# ---------------------------------------------------------------- presence (존재성)
PRESENCE_POS = (
    'Target sound: "{target}".\n'
    "Is the target sound audible anywhere in this audio, even if it is very quiet or very brief?\n"
    "YES = the target sound is present. NO = it is not present at all.\n"
)
PRESENCE_NEG = (
    'Target sound: "{target}".\n'
    "Is this audio completely free of the target sound? Treat even a very quiet or very brief "
    "occurrence as present.\n"
    "YES = the target sound is absent. NO = it occurs somewhere.\n"
)

# ---------------------------------------------------------------- purity (순수성)
_PURITY_RULE = (
    "Rules: the target's own natural reverb/echo/decay counts as the target. ANYTHING else counts "
    "as another sound: other sound events, speech, music, crowd or room ambience, wind, "
    "background noise, hiss, hum, clicks, or bleed of other sources — no matter how faint or "
    "short.\n"
)
PURITY_POS = (
    'This audio is supposed to contain ONLY the target sound: "{target}".\n'
    + _PURITY_RULE
    + "Apart from the target sound, can you hear ANY other sound at all, even very faintly?\n"
    "YES = some other sound is audible. NO = only the target sound is audible.\n"
)
PURITY_NEG = (
    'This audio is supposed to contain ONLY the target sound: "{target}".\n'
    + _PURITY_RULE
    + "Is this audio perfectly clean, i.e. it contains nothing except the target sound?\n"
    "YES = perfectly clean, only the target. NO = something else is audible.\n"
)
PURITY_ENUMERATE = (
    "List every distinct sound source you can hear in this audio, including very faint "
    "background sounds and noise. Output only a JSON array of short English labels, e.g. "
    '["sword clash", "crowd murmur", "low hiss"].'
)

# ---------------------------------------------------------------- completeness (완전성)
COMPLETENESS_POS = (
    "Audio 1 is the ORIGINAL mixture. Audio 2 is a STEM extracted from it that must contain "
    'every occurrence of the target sound: "{target}".\n'
    "{span}"
    "Compare the two over time. Is any occurrence (or any part of an occurrence) of the target "
    "that is audible in Audio 1 missing, cut off, or strongly attenuated in Audio 2?\n"
    "If the target does not occur in Audio 1 at all, answer NO.\n"
    "YES = something of the target is missing in the stem. NO = the stem keeps all of it.\n"
)
COMPLETENESS_NEG = (
    "Audio 1 is the ORIGINAL mixture. Audio 2 is a STEM extracted from it that must contain "
    'every occurrence of the target sound: "{target}".\n'
    "{span}"
    "Compare the two over time. Is every occurrence of the target that is audible in Audio 1 "
    "also fully present in Audio 2, with no missing, cut-off or strongly attenuated parts?\n"
    "If the target does not occur in Audio 1 at all, answer YES.\n"
    "YES = the stem keeps all of the target. NO = something is missing.\n"
)
SPAN_NOTE = "Both excerpts cover {start:.2f}s–{end:.2f}s of the full clip.\n"

# Residual (= original - stem) check, reuses presence wording but asks for CLEAR audibility,
# because residuals normally contain faint separation bleed.
RESIDUAL_POS = (
    'Target sound: "{target}".\n'
    "This audio is what remained after the target was extracted from a mixture. Is the target "
    "sound still CLEARLY audible in it (a recognisable occurrence, not just a faint smear)?\n"
    "YES = clearly audible. NO = not clearly audible.\n"
)
RESIDUAL_NEG = (
    'Target sound: "{target}".\n'
    "This audio is what remained after the target was extracted from a mixture. Is it free of "
    "any recognisable occurrence of the target sound (ignore only a faint smear)?\n"
    "YES = no recognisable occurrence remains. NO = a recognisable occurrence remains.\n"
)

# Localisation of missing parts (used only after a completeness FAIL, for retry hints and
# for comparing with the human "누락된 시점" label).
COMPLETENESS_LOCALIZE = (
    "Audio 1 is the ORIGINAL mixture. Audio 2 is a STEM extracted from it that should contain "
    'every occurrence of the target sound: "{target}". Both audios are {duration:.1f} seconds '
    "long and time-aligned.\n"
    "List the time ranges (in seconds from the start) where the target is audible in Audio 1 "
    "but missing, cut off or strongly attenuated in Audio 2. Output only a JSON array of "
    "[start, end] pairs, e.g. [[2.0, 3.5], [7.1, 8.0]]. Output [] if nothing is missing."
)

# ---------------------------------------------------------------- purity v2: "audible"
# Matches the human S3 criterion ("일반 재생 음량에서 목표 외 소리가 들리면 X"): judged at a
# normal playback level, without counting the low steady noise floor every separated stem has.
_PURITY_AUDIBLE_RULE = (
    "Listen at a normal playback level. The target's own reverb/echo/decay counts as the target. "
    "Do NOT count a very low, steady noise floor that is only noticeable if the volume is turned "
    "far up. DO count any other identifiable sound source: other sound events, speech or "
    "vocalisation, music or instruments, crowd or environmental ambience, or bleed of such "
    "sources, even if it is quieter than the target.\n"
)
PURITY_AUDIBLE_POS = (
    'This audio is a separated stem that should contain only: "{target}".\n'
    + _PURITY_AUDIBLE_RULE
    + "Is any OTHER sound source audible in it?\n"
    "YES = another source is audible. NO = only the target is audible.\n"
)
PURITY_AUDIBLE_NEG = (
    'This audio is a separated stem that should contain only: "{target}".\n'
    + _PURITY_AUDIBLE_RULE
    + "Does it contain only the target, with no other sound source audible?\n"
    "YES = only the target. NO = another source is audible.\n"
)

# ---------------------------------------------------------------- purity v3: "named"
# Counterfactual / exclusion-style probing (paper 2 idea): first name the NON-target sources
# that exist in the ORIGINAL mixture, then ask about each one specifically in the stem.
# Specific named questions are much easier for an audio LLM than "anything else?".
PURITY_NAMED_ENUMERATE = (
    'This is the ORIGINAL mixture. The target sound is: "{target}".\n'
    "List the distinct sound sources audible in it that are NOT the target and NOT part of the "
    "target (exclude the target itself, its parts and its reverb). Output only a JSON array of "
    'short English labels, e.g. ["crowd cheering", "background music"]. Output [] if none.'
)
PURITY_NAMED_POS = (
    'Sound to check: "{source}".\n'
    'This audio is a separated stem meant to contain only "{target}". Is "{source}" audible in '
    "it as a recognisable sound (not just a faint smear of noise)?\n"
    'YES = "{source}" is audible. NO = it is not.\n'
)
PURITY_NAMED_NEG = (
    'Sound to check: "{source}".\n'
    'This audio is a separated stem meant to contain only "{target}". Is it free of any '
    'recognisable "{source}"?\n'
    'YES = no "{source}". NO = "{source}" is audible.\n'
)
