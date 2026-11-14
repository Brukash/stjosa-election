# Voter Guide

## Before you start

You need:

- Your **Voter ID** from the Electoral Committee register (for example `SJC/AL/2004/001`).
- Access to the email address or phone number registered with the Alumni Association.
- About five minutes.

## 1. Accredit

1. Open the election website and choose **Accredit and vote**.
2. Enter your Voter ID exactly as printed on the register.
3. A one-time password (OTP) is sent to your registered contact. It expires in five minutes.
4. Enter the OTP. If it expires or you run out of attempts, request a new one.

One credential is issued per Voter ID. If you lose it, contact the Accreditation Officer — the
replacement is controlled and recorded.

## 2. Create your anonymous credential

Your browser creates a secret voting token and blinds it before asking the system to sign it. The
system never sees the unblinded token, so it cannot link your identity to the ballot you later cast.
The credential is kept only in your current browser tab.

Do not close the tab until you have cast your ballot.

## 3. Complete your ballot

1. Choose one candidate for each position. Your selections are summarised on the review screen.
2. Select **Prepare encrypted ballot**. Your choices are encrypted to the election tally key.
3. Choose one of:
   - **Verify my selections (challenge this ballot)** — the system reveals cryptographic proof and
     your browser re-checks that the encrypted ballot contains exactly your choices. This proves the
     application did not substitute a candidate. **The challenged ballot is destroyed and can never be
     counted.** You then prepare a fresh ballot and cast it.
   - **Cast my ballot** — your credential is spent, the ballot is stored anonymously and a receipt is
     issued.

A cast ballot cannot be edited. Cast only when your review screen is correct.

## 4. Keep your receipt

Your receipt shows:

- Receipt number and verification reference
- Ballot acceptance status and submission time
- Ballot commitment (a cryptographic fingerprint, not your choices)
- A QR code and the verification address

Download the PDF and keep it. The receipt never contains your selections.

## 5. Verify later

1. Open **Verify**.
2. Enter your verification reference or scan the receipt QR code.
3. The portal confirms:
   - the receipt is valid,
   - your ballot was recorded,
   - the commitment appears in the published commitment list,
   - the Merkle proof and digital signature are valid,
   - the ballot was included in the final count (after counting).

It never reveals who you are or how you voted.

## Privacy and coercion

- The receipt proves acceptance only; it is not proof of how you voted, and it cannot be used to
  demonstrate your choices to anyone else.
- Do not share your OTP or credential with anyone. Officials will never ask for them.
- If someone tries to buy or coerce your vote, report it to the Electoral Committee. The system
  deliberately cannot produce a transferable proof of your selections.

## Troubleshooting

| Problem | Action |
| --- | --- |
| OTP not received | Check the registered email/phone; wait for the cool-down, then request again |
| OTP expired | Request a new OTP |
| "Credential already issued" | Contact the Accreditation Officer for a controlled exception |
| "Voting is not open" | Check the election dates shown on the site |
| Credential lost / tab closed | Re-accredit; if blocked, contact the Accreditation Officer |
| Challenge check fails | Do not cast. Report it and prepare a new ballot |
