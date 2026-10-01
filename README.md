# WasseLead

**Website (live demo):** https://fsix7115-arch.github.io/wasselead/

**Chhote clinic, gym ya dukan ke liye WhatsApp lead follow-up.**
Leads ko priority deta hai, message aapke tone me likhta hai, aur aapko
copy-paste-ready plan deta hai. Kuch bhi automatically send nahi hota.

---

## Ye kya karta hai

Aapke paas is hafte ke leads hain — WhatsApp pe aaye, kisi ne reply nahi kiya.
Aap busy ho, wo thande ho rahe hain.

WasseLead:
1. har lead ko **urgency** deta hai (kisi ne sawal pucha? koi interested hai? reply nahi aaya?)
2. batata hai **kab follow-up karna chahiye** (2 ghante, 1 din, 2 din)
3. **message likh deta hai** — aapke apne tone me, aapka naam, aapki dukaan ka naam
4. sabse pehle kiska reply karna hai wo **order me** deta hai
5. jinhe message nahi karna chahiye (opt-out, duplicate, booking) unhe **hatata** hai

## Ye kya NAHI karta (bhoolke bhi nahi)

- ❌ Auto-send nahi karta. Aap khud paste karte ho WhatsApp me.
- ❌ WhatsApp API use nahi karta — bulk automation se aapka number **ban** hota hai
- ❌ Opt-out wale ko kabhi message nahi karta — flag ke saath message ke text dono check hote hain
  (`stop`, `unsubscribe`, `remove me`, `not interested`, `do not contact`, …). Jab doubt ho,
  lead skip ho jaati hai. Galat skip se ek follow-up chala jaata hai; galat message se
  client ka number khatam hota hai.
- ❌ Same number do baar message nahi karta

Auto-send na karna limitation nahi hai — **yehi reason hai ye tool aapka number
bachata hai.** Client ka number ban ho jaye to ₹10k ka nuksaan, tool ka price
₹5k se kam.

## Install

Kuch nahi. Sirf Python chahiye (3.10+). Koi dependency nahi.

```bash
git clone https://github.com/fsix7115-arch/wasselead.git
cd wasselead
python3 src/wasselead.py examples/leads.json --business examples/business.json
```

---

## Asli output

```
$ python3 src/wasselead.py examples/leads.json --business examples/business.json --now 2026-10-01T10:00:00+00:00

Lead follow-up — Apollo Physiotherapy & Fitness
============================================================
Skipped 3:
  - Meena Iyer: opted out
  - P. Sharma: duplicate of Priya Sharma
  - Fatima Sheikh: no digits found in phone ''

[ HOT] Suresh Kumar  LATE (due 2026-09-25T12:00)
        919876543213  — they replied and have had no answer
        "Hi Suresh, sorry for the delay in replying — thank you for your message. This is Dr. Meera from Apollo Physiotherapy & Fitness. How can I help?"

[ HOT] Priya Sharma  LATE (due 2026-10-01T07:00)
        919876543210  — asked a question and got no answer
        "Hi Priya, this is Dr. Meera from Apollo Physiotherapy & Fitness. Thanks for asking — Physio sessions are ₹600 each (₹4,500 for 8 sessions). Personal training is ₹3,000/month. Want me to book you in?"

[ HOT] Rohit Gupta       (due 2026-10-01T11:00)
        919876543216  — asked a question and got no answer
        "Hi Rohit, this is Dr. Meera from Apollo Physiotherapy & Fitness. Thanks for asking — Physio sessions are ₹600 each (₹4,500 for 8 sessions). Personal training is ₹3,000/month. Want me to book you in?"

[WARM] Rahul Verma  LATE (due 2026-10-01T08:00)
        919876543211  — showed interest but no reply
        "Hi Rahul, this is Dr. Meera from Apollo Physiotherapy & Fitness. Saw your message. First physio assessment is free this month. Shall I share timings?"

[COLD] Anita Desai  LATE (due 2026-09-30T10:00)
        919876543212  — initial message, no reply yet
        "Hi Anita, this is Dr. Meera from Apollo Physiotherapy & Fitness. Saw your message. First physio assessment is free this month. Shall I share timings?"

[COLD] Vikram Singh       (due 2026-10-02T10:00)
        919876543215  — booked — send a confirmation, not a sales message
        "Hi Vikram, this is Dr. Meera from Apollo Physiotherapy & Fitness. Just confirming your appointment — reply YES to confirm or RESCHEDULE if you need a different time."

============================================================
Counts: cold=2, hot=3, warm=1
Copy each message into WhatsApp yourself. Nothing is sent automatically.
```

---

## Apna data kaise banayein

`leads.json` ya `leads.csv`. CSV columns:

| column | zaruri? | example |
|---|---|---|
| `name` | haan | `Priya Sharma` |
| `phone` | haan | `+91 98765 43210` |
| `message` | haan | `do you have slots?` |
| `received_at` | haan | `2026-10-01T05:00:00+00:00` |
| `replied` | nahi | `true` |
| `opted_out` | nahi | `true` |
| `booked` | nahi | `true` |

Phone formats — sab ek hi insaan: `+91 98765 43210`, `098765 43210`,
`9876543210`, `919876543210`, `00919876543210`. **Same number, ek message.**

`business.json` — apna tone:

```json
{
  "name": "Apollo Physiotherapy",
  "owner_name": "Dr. Meera",
  "slots": {
    "price": "₹600 per session.",
    "offer": "First assessment free this month."
  }
}
```

`price` slot bharne se tool seedha price bata deta hai — client ko dobara
sawal nahi karna padta.

---

## Urgency kaise decide hoti hai

| Situation | Priority | Kab tak |
|---|---|---|
| Reply kiya, humne nahi kiya | **HOT** | 2 ghante |
| Sawaal pucha (price/timing/slots) | **HOT** | 2 ghante |
| Interest bataya | **WARM** | 1 din |
| Sirf initial message | **COLD** | 2 din |
| Opt-out / unsubscribe | — | kabhi nahi |
| Booking ho chuki | — | sirf confirm |

## Tests

```bash
python3 -m unittest discover -s tests -v     # 39 tests
```

Sab stdlib par — koi install nahi. Tests wo cases cover karte hain jinke
galat hote hi client ka nuksaan hota hai: duplicate number, opt-out, booking
par sales pitch, aur double punctuation.

## Honest limitations

- Aapka **business WhatsApp number se manually paste** karte ho — isme time lagta hai (30 second/lead). Auto-send karna jaan-boojh kar nahi kiya.
- English me likhta hai. Hindi/Hinglish support nahi hai abhi.
- WhatsApp Business API ka paid plan use nahi karta, isliye **free** hai.
- Message bhejne ke baad status update karna aapka kaam hai — tool ko feedback nahi milta.
- CRM nahi hai. Lead history nahi rakhta.

## License

MIT