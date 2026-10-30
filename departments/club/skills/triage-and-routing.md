# Triage and routing of member reports

Run `tools/triage.py report.txt` first, then read the report yourself; the tool's
class is the starting point, not the verdict.

## Classes and where they go
| class | examples | goes to | club-1 does |
|---|---|---|---|
| incident | site down for many; hacked; data exposed; account takeover; judge fails mid-contest | CEO, immediately | tells the CEO, nothing else |
| site-bug | page error; Run does nothing; 404 | Engineering (opencode-1, [build] intake) | hand-off with repro steps; acknowledgement draft |
| account | cannot log in; no OTP; locked out | Engineering if database or admin access is needed | reply draft; never asks for a password or OTP |
| content | typo; wrong date on the site; add photos | club-1 drafts, CEO approves, Engineering applies | old text, new text, page URL |
| other | general questions | club-1, or the CEO | answer draft or one exact question |

## Incidents
triage.py exits 3 and prints INCIDENT on stderr. That is deliberate: an incident is
never queued behind other work. Steps: note the time the report arrived, tell the CEO in
one message (what is broken, since when, who reported it by role, how many affected),
and stop. Do not reply to the reporter with a promise, do not touch any service, do not
retry anything. If the tool misses a plain incident, treat it as one anyway.

## Hand-off to Engineering
Create a child issue (ROUTING handoff mechanics), distinct title, assigned to the
owner in DIRECTORY.md:
- Title: `Handoff from club-1: site bug - <one-line summary>`
- Body: what the member saw, the page URL on https://codescriet.dev, device, browser,
  time, repro steps, what club-1 did ("classified; no reply sent; site not touched"),
  and what "fixed" looks like.
- End the turn with `RESULT: HANDED-OFF to opencode-1`.
At most three hops per chain; never hand back to the agent that sent it.

## Acknowledgement draft for the reporter
Two or three lines, DRAFT FOR CEO REVIEW: thanks, what we understood, that it is with
the people who maintain the site. No fix date, no blame, no internal names.

## What club-1 never does
Edit the site or its repository, run commands against production, ask for credentials,
or close a report as "fixed" without Engineering's confirmation on the issue.
