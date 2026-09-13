# Decisions and deferred choices

Short notes on choices made and choices parked, so nobody re-litigates them by accident.

## Parked: business-email-only sign-up

The sign-up form can reject free-mail addresses (Gmail, Outlook, Yahoo and the like) with
"please enter a valid business email address", the way AlphaSense does. The check is built and
tested, and it is **switched off by default** (`SIGNUP_BUSINESS_EMAIL_ONLY=false`) because the
owner's own address is Gmail and is needed for testing.

**Revisit once the domain name is purchased.** Then set `SIGNUP_BUSINESS_EMAIL_ONLY=true` in the
API's environment on Render (the `filings-hub-lake` environment group, or the API service's own
variables) and the form starts refusing free-mail domains. The list of free-mail domains lives in
`filings_hub/accounts.py` (`FREE_MAIL_DOMAINS`).

## Also waiting on the domain and an email relay

- Sign-up and sign-in emails need an SMTP relay (`SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`,
  `SMTP_PASSWORD`) and `SITE_URL` pointing at the public site; until then the pages say email is
  not configured and visitors keep their choices in the browser.
- Accounts on the free Render layout need the read-write R2 token on the API (the read-only one
  cannot store users).

## Product name: Disclosure (2026-09-13)

The product is called **Disclosure**. Everything a person sees says so: the site, page titles, sign-in and digest emails, the workbook's creator field. The Python package (`filings_hub`), the `filings-hub` command, the lake prefix and the Render service names stay as they are: renaming them would move live URLs and secrets for no user-visible gain. Revisit when the domain is bought and the services are recreated under it.

## Ownership: three flows, never mixed (2026-09-13)

Ownership data is three different things and the product keeps them apart everywhere: separate tables in the lake, separate sections on the company page, separate alerts, separate API responses and exports. Nothing ever lists a director's Form 4 next to a fund's 13F.

1. **Insiders.** Forms 3, 4 and 5: officers, directors, 10 % holders. The unit is the transaction (who, bought or sold, how many, at what price, open-market or exercise or gift). Daily.
2. **Outside holders.** Form 13F: managers above $100M, quarterly, 45 days late. The unit is the change since the previous quarter (new, added, trimmed, exited). Only the large managers are ever visible; the page says "reported holders", never "owners".
3. **Activists and blocks.** Schedule 13D (13G for passive). The unit is the event, with the letter to the board attached and readable. Rare, high value.

Order of work: the live flow in the current XML formats first (each new filing parsed the day it arrives and shown on the company page and in the morning view); presentation second, once real data flows; backfill last and only as far back as it helps show a change. The information value is movement going forward, not the level at first record.

Europe is per-country and comes later, after a separate brief.

### Insider rows say who the person is and how big the move was

A name alone is not information: someone looking at a company for the first time cannot tell whether John McGovern matters. Every insider row carries, from the Form 4 itself: the role (officer title, director, 10 % holder); the direction and kind of transaction (open-market buy or sale, option exercise, grant, gift, tax withholding: a grant is not a buy and an exercise-and-sell is not conviction); the size relative to the person's holding, from the "owned after" field; whether it was a pre-arranged 10b5-1 plan; and the company context (how many insiders moved the same way in the period, so a cluster of directors buying stands out). The row reads as a sentence: "John McGovern, Chief Financial Officer, sold 40,000 shares (12 % of his holding) at $52.10 under a pre-arranged plan."
