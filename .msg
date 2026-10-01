feat: add a landing page with a live, interactive demo

The repo had no website, which made it hard to show anyone what the tool
actually does. This adds a single-page site at the repo root so GitHub Pages
serves it.

The demo is the real ranking logic running in the browser, not a screenshot or
a video. You paste leads, press a button, and the queue changes. It is a
faithful port of the urgency, dedupe, opt-out and reply-window logic from
src/wasselead.py, so what a visitor sees is what a client gets.

Building the site surfaced a real bug in the tool itself, which the tests had
missed. clean() stripped the trailing full stop from the owner's slot text and
the template never put one back, so every offer-based message read "...this
month Shall I share timings?" instead of "...this month. Shall I share
timings?". My first fix went the wrong way: I made clean() remove the
duplicate stop, which was not the symptom anyone would see. The real fix is to
normalise to exactly one full stop in clean() and let the template append
nothing, in both the Python and the JavaScript.

Two regression tests now cover every combination of trailing punctuation in a
slot value, since the bug only appears when the owner's own wording happens to
end a certain way.

Verified: 40 tests pass; the demo runs interactively in a browser; the fixed
messages match between the Python tool and the JavaScript demo.

GitHub Pages is enabled and serves the site from the repo root. No custom
domain is set, because an unverified CNAME would break the Pages build.