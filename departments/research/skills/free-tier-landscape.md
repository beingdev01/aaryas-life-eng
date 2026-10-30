# Free-tier and tooling landscape research

This company runs only on free models and free tiers. A memo about any tool, model,
API or host is incomplete until it answers these for every option, each cited and dated:

1. **Exact free limit** and its unit (requests per minute, per day, tokens, credits),
   and whether it applies per key, per account, per project or per IP. Anonymous Kilo
   use is 200 requests per hour per IP, shared by every lane on the VM
   (kilo-multi-model-research.md:128).
2. **Standing or one-time.** A monthly tier can carry a lane; a signup grant cannot.
3. **Behaviour at the limit**: HTTP 429, a pause until the next cycle, silent fallback to
   a paid model, or a hang. On 2026-10-30 five of seven OpenCode Zen free models returned
   "Free usage limit reached" and the CLI hung instead of exiting
   (ENGINE_DESIGN.md:38-40). A hang is the worst case; say so when you find one.
4. **How the free tier is proven.** The engine dispatches a model only if its id ends in
   `:free` or `-free` (ENGINE_DESIGN.md:157). A model that is "free today by offer" is
   refused, so do not recommend it as a lane.
5. **Barrier**: card, phone, real-name ID, Owner sign-in. Anything needing money or an
   Owner account goes in Open questions and the run ends ESCALATED.

6. **Roster drift.** Free rosters shrink without notice (the Kilo free roster shrank to
   10 models by 14 Oct 2026, kilo-multi-model-research.md:350). Give the date you saw
   the model listed, and how to re-check it.

Never recommend a paid tier or a trial that needs a card. If no free option works, the
recommendation says so plainly.
