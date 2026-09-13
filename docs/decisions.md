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
