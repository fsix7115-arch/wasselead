feat: WasseLead - WhatsApp lead follow-up for small businesses

A clinic, gym or shop gets 20-60 leads a week on WhatsApp and most go cold,
because the owner is too busy doing the actual work to follow up. This takes
that list, ranks who needs a reply first, writes the message in the owner's
own voice, and produces a copy-paste plan.

Deliberately does not auto-send. Bulk WhatsApp automation violates the platform
terms and gets the business number banned, which costs the client far more than
this tool does, and only the owner can tell whether a non-reply means "not
interested" or "busy this week". Not being automatic is the feature.

Zero dependencies, standard library only, so a client can run it with plain
python3 and it can never break on an install.

Verified: 39 tests pass; the tool runs on the example data; JSON output parses.
Three bugs found and fixed while building:
- due_at was annotated as a string but assigned a datetime, then sliced like a
  string in the renderer. Now a datetime throughout.
- a slot value ending in a full stop produced ".." in the composed message.
  Trimmed before punctuation is added.
- a lead with an empty phone number crashed the whole run. It is now skipped
  with a reason, alongside duplicates and opt-outs.

Not built, and said so in the README: Hindi/Hinglish, feedback after sending,
lead history, and any CRM. The tool is one pass over a list, nothing more.