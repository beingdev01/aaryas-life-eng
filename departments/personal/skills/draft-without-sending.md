# Skill: drafting without sending

This department's failure mode is not bad writing. It is a draft that reads as if the
message had already gone out, or a message that is so generic that Lakshya would be
ashamed to send it.

## The two-line rule

A draft is addressed to Lakshya with the words `DRAFT FOR CEO REVIEW` on line 1, and the
message body is in his voice, not the department's. If the file reads like an agent
writing to a human on his behalf, it is wrong even when the prose is good.

## What a finished draft contains

```
DRAFT FOR CEO REVIEW

To (for you to send): Dad
Occasion: none - 19 days since the last call
Subject / first line: ...
Body: 2-4 sentences
Why now: one line, from the CRM note or the sweep entry
```

Nothing else. No "Here is a draft you can customize!", no options A/B/C unless the CEO
asked for variants, no hashtags, no emoji, no signature block pretending to be his.

## Voice

Write the way he actually writes: short sentences, plain words, no cushioning. Concretely
bad: "I hope this message finds you well. It has been a while since we last connected."
Concretely good: "Hey - did the surgery go okay? Free this Sunday evening?"

- one specific thing that is true about that person, taken from `notes`;
- one ask or offer, phrased so it can be refused without awkwardness;
- no exclamation marks, no "!!!", no "so excited", no "just checking in!" filler.

## Banned sentences

Anything that reports an action that has not happened, in any tense:

- "I've sent it", "already emailed", "shared with the team", "you'll receive it shortly"
- "I have cc'd", "forwarded to", "replied to them"
- instructions to a person: "Send this to Dad", "Post it tonight", "Message her back"

If the file must describe what happens next, it says **what Lakshya could do**: "Ready to
send when you are."

## Length

200 words for a personal message, 120 for a health nudge, 400 for anything with context.
`draft_guard.py --max-words` enforces it. A draft that needs more words needs a decision,
not more words - put the decision in the report instead.

## When not to draft

- the person is not in the CRM: stop, ask;
- the last message is theirs and unanswered: say "waiting on them" in the report, do not
  draft a nudge - that is a relationship judgement;
- the occasion is grief, illness, a break-up, a failure: write the *situation* in the
  report, one line, and leave the words to him. A generated condolence message does more
  harm than no message.
- the sweep found nothing due: no draft exists. That is the correct output.
