"""Build a 16:9 presentation for the St. John's College Jos Alumni Election System."""
from __future__ import annotations

from pathlib import Path

from PIL import Image
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_CONNECTOR, MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.util import Inches, Pt

ROOT = Path(__file__).resolve().parent
SHOTS = ROOT / "screenshots"
ASSETS = ROOT / "assets"
ASSETS.mkdir(exist_ok=True)
DECK = ROOT / "SJC_Election_System_Presentation.pptx"
CREST = ROOT.parent / "frontend" / "public" / "Josa.png"

# ── palette ─────────────────────────────────────────────────────────────────
CREAM = RGBColor(0xFA, 0xF8, 0xEC)
PAPER = RGBColor(0xFF, 0xFF, 0xFF)
INK = RGBColor(0x0B, 0x3D, 0x24)
INK_SOFT = RGBColor(0x2A, 0x4A, 0x39)
MUTED = RGBColor(0x63, 0x70, 0x68)
GREEN = RGBColor(0x1F, 0x6B, 0x45)
GREEN_LIGHT = RGBColor(0xE1, 0xEE, 0xE5)
GOLD = RGBColor(0xC8, 0xA8, 0x4B)
GOLD_LIGHT = RGBColor(0xF3, 0xE8, 0xC9)
LINE = RGBColor(0xD9, 0xD6, 0xC6)
DARK = RGBColor(0x07, 0x2E, 0x1B)

DISPLAY = "Georgia"
BODY = "Segoe UI"
SW, SH = 13.333, 7.5


def px(value: float) -> Inches:
    return Inches(value)


def add_text(
    slide,
    left,
    top,
    width,
    height,
    text,
    *,
    size=16,
    color=INK,
    bold=False,
    font=BODY,
    align=PP_ALIGN.LEFT,
    anchor=MSO_ANCHOR.TOP,
    spacing=1.05,
    margin=0,
):
    box = slide.shapes.add_textbox(px(left), px(top), px(width), px(height))
    tf = box.text_frame
    tf.clear()
    tf.word_wrap = True
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = px(margin)
    tf.vertical_anchor = anchor
    p = tf.paragraphs[0]
    p.alignment = align
    p.line_spacing = spacing
    run = p.add_run()
    run.text = text
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.name = font
    run.font.color.rgb = color
    return box


def add_rich_text(slide, left, top, width, height, lines, *, size=15, color=INK, spacing=1.1, margin=0):
    """Each line is (text, bold, color, size) or a single string."""
    box = slide.shapes.add_textbox(px(left), px(top), px(width), px(height))
    tf = box.text_frame
    tf.clear()
    tf.word_wrap = True
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = px(margin)
    for index, line in enumerate(lines):
        p = tf.paragraphs[0] if index == 0 else tf.add_paragraph()
        p.space_after = Pt(7)
        p.line_spacing = spacing
        if isinstance(line, str):
            line = (line, False, color, size)
        text, bold, line_color, line_size = line
        run = p.add_run()
        run.text = text
        run.font.size = Pt(line_size)
        run.font.bold = bold
        run.font.name = BODY
        run.font.color.rgb = line_color
    return box


def add_rect(slide, left, top, width, height, *, fill=PAPER, line=None, radius=False, line_width=0.8):
    shape_type = MSO_SHAPE.ROUNDED_RECTANGLE if radius else MSO_SHAPE.RECTANGLE
    shape = slide.shapes.add_shape(shape_type, px(left), px(top), px(width), px(height))
    shape.fill.solid()
    shape.fill.fore_color.rgb = fill
    if line is None:
        shape.line.fill.background()
    else:
        shape.line.color.rgb = line
        shape.line.width = Pt(line_width)
    if radius:
        try:
            shape.adjustments[0] = 0.06
        except Exception:
            pass
    return shape


def add_line(slide, x1, y1, x2, y2, *, color=GOLD, width=1.2):
    line = slide.shapes.add_connector(MSO_CONNECTOR.STRAIGHT, px(x1), px(y1), px(x2), px(y2))
    line.line.color.rgb = color
    line.line.width = Pt(width)
    return line


def add_header(slide, eyebrow, title, *, dark=False):
    eyebrow_color = GOLD if dark else GREEN
    title_color = CREAM if dark else INK
    add_text(slide, 0.72, 0.46, 9.7, 0.24, eyebrow.upper(), size=10.5, color=eyebrow_color, bold=True)
    add_text(slide, 0.70, 0.70, 11.9, 0.62, title, size=29, color=title_color, font=DISPLAY)
    add_line(slide, 0.74, 1.43, 1.92, 1.43, color=GOLD, width=1.8)


def add_footer(slide, number, *, dark=False):
    color = RGBColor(0xC9, 0xD6, 0xCC) if dark else MUTED
    add_text(slide, 0.74, 7.12, 8.9, 0.20, "St. John's College Jos Alumni Association · Electoral Committee", size=8.5, color=color)
    add_text(slide, 12.05, 7.12, 0.55, 0.20, f"{number:02d}", size=8.5, color=color, align=PP_ALIGN.RIGHT)


def add_crest(slide, left, top, height=0.78):
    slide.shapes.add_picture(str(CREST), px(left), px(top), height=px(height))


def add_picture_fit(slide, path, left, top, width, height, *, border=True):
    with Image.open(path) as image:
        image_w, image_h = image.size
    scale = min(width / image_w, height / image_h)
    draw_w, draw_h = image_w * scale, image_h * scale
    x = left + (width - draw_w) / 2
    y = top + (height - draw_h) / 2
    pic = slide.shapes.add_picture(str(path), px(x), px(y), width=px(draw_w), height=px(draw_h))
    if border:
        pic.line.color.rgb = LINE
        pic.line.width = Pt(0.9)
    return pic


def add_stat(slide, left, top, value, label, *, width=2.2, dark=False):
    add_text(slide, left, top, width, 0.42, value, size=24, color=GOLD if dark else GREEN, bold=True, font=DISPLAY)
    add_text(slide, left, top + 0.44, width, 0.56, label.upper(), size=8.5, color=RGBColor(0xD0, 0xDC, 0xD3) if dark else MUTED, bold=True)


def add_callout(slide, number, heading, body, left, top, width, *, dark=False):
    circle = slide.shapes.add_shape(MSO_SHAPE.OVAL, px(left), px(top + 0.02), px(0.34), px(0.34))
    circle.fill.solid()
    circle.fill.fore_color.rgb = GOLD if dark else GREEN
    circle.line.fill.background()
    add_text(slide, left, top + 0.075, 0.34, 0.18, str(number), size=9.5, color=DARK if dark else PAPER, bold=True, align=PP_ALIGN.CENTER)
    add_text(slide, left + 0.50, top, width - 0.50, 0.28, heading, size=12.5, color=CREAM if dark else INK, bold=True)
    add_text(slide, left + 0.50, top + 0.30, width - 0.50, 0.60, body, size=10.2, color=RGBColor(0xD0, 0xDC, 0xD3) if dark else MUTED, spacing=1.08)


def clean_crop(source: Path, target: Path, height: int | None = None):
    image = Image.open(source).convert("RGB")
    if height:
        image = image.crop((0, 0, image.width, min(height, image.height)))
    # The local browser injects a small badge in the top-left. Paint it out with
    # the surrounding header colour so the presentation contains only the app.
    bg = image.getpixel((image.width // 2, 6))
    patch = Image.new("RGB", (200, 90), bg)
    image.paste(patch, (0, 0))
    image.save(target, quality=95)
    return target


def notes(slide, text):
    slide.notes_slide.notes_text_frame.text = text


def build_assets():
    return {
        "home": clean_crop(SHOTS / "test_full.png", ASSETS / "home.png", 1606),
        "accredit": clean_crop(SHOTS / "02_accredit_form_full.png", ASSETS / "accredit.png"),
        "otp": clean_crop(SHOTS / "03_otp_channels_full.png", ASSETS / "otp.png", 1606),
        "login": clean_crop(SHOTS / "04_admin_login_full.png", ASSETS / "login.png"),
        "dashboard": clean_crop(SHOTS / "05_chairman_dashboard_full.png", ASSETS / "dashboard.png", 1900),
        "providers": clean_crop(SHOTS / "06_delivery_providers_full.png", ASSETS / "providers.png", 1606),
        "ballot": clean_crop(SHOTS / "07_ballot_full.png", ASSETS / "ballot.png", 2050),
    }


def build():
    assets = build_assets()
    prs = Presentation()
    prs.slide_width = px(SW)
    prs.slide_height = px(SH)
    blank = prs.slide_layouts[6]
    prs.core_properties.title = "St. John's College Jos Alumni Election Management System"
    prs.core_properties.subject = "Secure, independently verifiable remote alumni election"
    prs.core_properties.author = "St. John's College Jos Alumni Association Electoral Committee"

    # ── 1. title ───────────────────────────────────────────────────────────
    slide = prs.slides.add_slide(blank)
    bg = slide.background.fill
    bg.solid()
    bg.fore_color.rgb = DARK
    add_rect(slide, 0, 0, SW, 0.10, fill=GOLD)
    add_rect(slide, 0.72, 1.10, 0.06, 3.10, fill=GOLD)
    add_crest(slide, 0.72, 0.46, 0.74)
    add_text(slide, 1.58, 0.50, 7.4, 0.26, "ST. JOHN'S COLLEGE JOS · ALUMNI ASSOCIATION", size=9.5, color=GOLD, bold=True)
    add_text(slide, 1.56, 0.75, 7.4, 0.25, "ELECTORAL COMMITTEE", size=8.5, color=RGBColor(0xB9, 0xCA, 0xBE), bold=True)
    add_text(slide, 0.98, 1.52, 8.0, 2.60, "One alumnus.\nOne vote.\nIndependently verifiable.", size=43, color=CREAM, font=DISPLAY, spacing=0.95)
    add_text(slide, 0.98, 4.35, 8.2, 0.63, "A secure, end-to-end verifiable remote election platform for the St. John's College Jos Alumni Association.", size=13.3, color=RGBColor(0xC9, 0xD6, 0xCC), spacing=1.18)
    add_line(slide, 0.98, 5.30, 12.60, 5.30, color=RGBColor(0x4C, 0x70, 0x5B), width=1)
    add_text(slide, 0.98, 5.56, 8.0, 0.30, "ELECTORAL COMMITTEE BRIEFING", size=10, color=GOLD, bold=True)
    add_text(slide, 0.98, 5.88, 8.0, 0.38, "2026 Alumni Election · Presentation pack", size=13, color=CREAM)
    add_text(slide, 10.75, 4.55, 1.8, 0.7, "2026", size=34, color=RGBColor(0x2A, 0x57, 0x3F), bold=True, font=DISPLAY, align=PP_ALIGN.RIGHT)
    notes(slide, "Welcome. This pack explains how the system protects the vote, how accreditation and simultaneous OTP delivery work, and what the Chairman and committee can see during the election.")

    # ── 2. at a glance ─────────────────────────────────────────────────────
    slide = prs.slides.add_slide(blank)
    slide.background.fill.solid()
    slide.background.fill.fore_color.rgb = CREAM
    add_header(slide, "The election", "A trusted front door for every eligible alumnus")
    add_picture_fit(slide, assets["home"], 6.55, 1.73, 6.0, 4.80)
    add_text(slide, 0.74, 1.76, 5.35, 0.35, "Built for a clean, observable election day", size=15, color=GREEN, bold=True)
    add_text(slide, 0.74, 2.16, 5.30, 1.36, "Voters accredit once against the approved register, receive an anonymous credential, and can verify that their ballot was recorded and included in the count.", size=12.2, color=MUTED, spacing=1.18)
    add_stat(slide, 0.74, 3.78, "24", "eligible voters")
    add_stat(slide, 2.42, 3.78, "5", "positions")
    add_stat(slide, 4.12, 3.78, "1", "ballot per voter")
    add_line(slide, 0.74, 3.60, 5.58, 3.60, color=LINE, width=0.8)
    add_callout(slide, 1, "One voter roll", "Only approved, eligible alumni receive an OTP.", 0.74, 4.72, 4.65)
    add_callout(slide, 2, "One secret ballot", "Ballots carry no voter identifier and are encrypted to the tally key.", 0.74, 5.38, 4.65)
    add_callout(slide, 3, "One public record", "Signed commitments and receipts let anyone check inclusion.", 0.74, 6.04, 4.65)
    add_footer(slide, 2)
    notes(slide, "This is the public entry point. The election has 24 eligible voters and five positions. The platform combines register-gated accreditation, anonymous encrypted ballots and public verification.")

    # ── 3. voter journey ───────────────────────────────────────────────────
    slide = prs.slides.add_slide(blank)
    slide.background.fill.solid()
    slide.background.fill.fore_color.rgb = CREAM
    add_header(slide, "Voter journey", "One Voter ID. One OTP. One anonymous credential.")
    add_picture_fit(slide, assets["accredit"], 6.28, 1.72, 6.28, 4.84)
    steps = [
        ("01", "Identify", "Enter the Voter ID from the approved register. Contact details cannot be typed or changed."),
        ("02", "Verify", "One six-digit OTP is sent to every available registered channel. Enter it once."),
        ("03", "Credential", "The browser blinds a secret; the service signs it without ever seeing the secret."),
        ("04", "Vote", "Review the ballot, optionally challenge the encryption, cast, and keep a receipt."),
    ]
    y = 1.80
    for number, heading, body in steps:
        add_text(slide, 0.76, y, 0.58, 0.30, number, size=17, color=GOLD, bold=True, font=DISPLAY)
        add_text(slide, 1.30, y, 4.42, 0.26, heading, size=13, color=INK, bold=True)
        add_text(slide, 1.30, y + 0.27, 4.42, 0.58, body, size=10.2, color=MUTED, spacing=1.10)
        if number != "04":
            add_line(slide, 0.87, y + 0.92, 0.87, y + 1.06, color=LINE, width=1.1)
        y += 1.16
    add_text(slide, 0.78, 6.48, 5.15, 0.38, "The voter sees masked destinations and a status for Email, SMS and WhatsApp — never a full contact.", size=9.5, color=GREEN, bold=True)
    add_footer(slide, 3)
    notes(slide, "The voter enters the Voter ID once. The system validates it against the approved register, then sends one OTP to all available registered channels. The voter can use whichever message arrives.")

    # ── 4. simultaneous OTP ────────────────────────────────────────────────
    slide = prs.slides.add_slide(blank)
    slide.background.fill.solid()
    slide.background.fill.fore_color.rgb = CREAM
    add_header(slide, "Accreditation delivery", "One OTP. Three channels. One shared challenge.")
    add_picture_fit(slide, assets["otp"], 5.78, 1.78, 6.80, 4.74)
    add_rect(slide, 0.74, 1.82, 4.55, 0.48, fill=GREEN_LIGHT, radius=True)
    add_text(slide, 0.94, 1.94, 4.15, 0.22, "SAME CODE · SENT CONCURRENTLY", size=10, color=GREEN, bold=True)
    add_text(slide, 0.74, 2.48, 4.62, 1.02, "The backend creates one cryptographically secure six-digit OTP and fans it out to every registered destination.", size=11.8, color=MUTED, spacing=1.18)
    add_callout(slide, 1, "Resend email", "Delivered to the registered email address; server-side API key only.", 0.74, 3.55, 4.65)
    add_callout(slide, 2, "Termii SMS", "Transactional DND route to the registered +234 number.", 0.74, 4.27, 4.65)
    add_callout(slide, 3, "Meta WhatsApp", "Approved authentication template; only with recorded consent.", 0.74, 4.88, 4.65)
    add_line(slide, 0.74, 5.78, 5.35, 5.78, color=LINE, width=0.8)
    add_text(slide, 0.74, 5.96, 4.80, 0.72, "Any channel verifies once. Success consumes the challenge everywhere; five-minute expiry and five attempts.", size=9.8, color=INK_SOFT, spacing=1.10, bold=True)
    add_footer(slide, 4)
    notes(slide, "This is the key change: no channel selection. One OTP is generated and delivered through Resend, Termii and Meta WhatsApp at the same time. A partial provider failure does not cancel the successful channels.")

    # ── 5. chairman dashboard ──────────────────────────────────────────────
    slide = prs.slides.add_slide(blank)
    slide.background.fill.solid()
    slide.background.fill.fore_color.rgb = CREAM
    add_header(slide, "Chairman's view", "The control room sees the election, not the voter's choices")
    add_picture_fit(slide, assets["dashboard"], 5.78, 1.76, 6.80, 4.92)
    add_text(slide, 0.74, 1.80, 4.65, 0.42, "A single operational view", size=17, color=INK, bold=True, font=DISPLAY)
    add_text(slide, 0.74, 2.28, 4.62, 0.75, "Live turnout, delivery health and security signals in one place — with no access to OTPs or ballot selections.", size=11.3, color=MUTED, spacing=1.17)
    add_callout(slide, 1, "Turnout", "Eligible, accredited, cast and yet-to-vote counts.", 0.74, 3.22, 4.65)
    add_callout(slide, 2, "Channel health", "Email, SMS and WhatsApp attempts, delivered and failed.", 0.74, 3.94, 4.65)
    add_callout(slide, 3, "Security signals", "Failed OTP attempts, duplicate attempts and recent alerts.", 0.74, 4.66, 4.65)
    add_callout(slide, 4, "Locked controls", "Verification settings freeze after the first ballot.", 0.74, 5.38, 4.65)
    add_text(slide, 0.74, 6.32, 4.65, 0.34, "Chairman · Electoral Committee", size=10, color=GREEN, bold=True)
    add_footer(slide, 5)
    notes(slide, "This is the Chairman's monitoring dashboard from a seeded election. It shows the approved register count, OTP delivery by channel, live monitoring and locked verification controls. It does not expose OTP values or ballot selections.")

    # ── 6. provider readiness ──────────────────────────────────────────────
    slide = prs.slides.add_slide(blank)
    slide.background.fill.solid()
    slide.background.fill.fore_color.rgb = CREAM
    add_header(slide, "Provider readiness", "Credentials stay server-side; the committee sees readiness")
    add_picture_fit(slide, assets["providers"], 5.84, 1.76, 6.72, 4.88)
    add_text(slide, 0.74, 1.80, 4.72, 0.42, "Configured, not exposed", size=17, color=INK, bold=True, font=DISPLAY)
    add_text(slide, 0.74, 2.28, 4.66, 0.80, "The Super Administrator configures providers in the deployment secret store. The browser only receives a readiness state.", size=11.3, color=MUTED, spacing=1.17)
    add_callout(slide, 1, "Resend", "Verified sender domain; API key never leaves the server.", 0.74, 3.24, 4.70)
    add_callout(slide, 2, "Termii", "Approved sender ID; transactional DND route for OTPs.", 0.74, 3.96, 4.70)
    add_callout(slide, 3, "Meta WhatsApp", "Business number and approved authentication template.", 0.74, 4.68, 4.70)
    add_callout(slide, 4, "Webhook", "HMAC-signed delivery and read status callbacks.", 0.74, 5.40, 4.70)
    add_text(slide, 0.74, 6.42, 4.70, 0.48, "No provider secret is returned by the API, written to delivery records, or stored in the browser.", size=9.5, color=GREEN, bold=True)
    add_footer(slide, 6)
    notes(slide, "This page shows provider readiness. The actual keys live only in server-side environment variables. The committee can confirm that all three channels are configured without seeing any secret.")

    # ── 7. ballot ──────────────────────────────────────────────────────────
    slide = prs.slides.add_slide(blank)
    slide.background.fill.solid()
    slide.background.fill.fore_color.rgb = CREAM
    add_header(slide, "The ballot", "Selections are encrypted before they leave the browser")
    add_picture_fit(slide, assets["ballot"], 5.82, 1.76, 6.74, 4.96)
    add_text(slide, 0.74, 1.80, 4.70, 0.72, "A ballot that cannot be traced back to a voter", size=17, color=INK, bold=True, font=DISPLAY, spacing=1.0)
    add_text(slide, 0.74, 2.60, 4.66, 0.70, "The voter reviews all positions, can challenge the encryption, and then casts a single anonymous ballot.", size=11.2, color=MUTED, spacing=1.15)
    add_callout(slide, 1, "Anonymous", "No voter ID, email address or credential serial is stored with the ballot.", 0.74, 3.42, 4.70)
    add_callout(slide, 2, "Encrypted", "AES-256-GCM data key wrapped with RSA-OAEP to the tally key.", 0.74, 4.18, 4.70)
    add_callout(slide, 3, "Cast-as-intended", "A challenged ballot is permanently excluded; a fresh one can be prepared.", 0.74, 4.94, 4.70)
    add_callout(slide, 4, "Receipt", "A random reference proves inclusion without revealing selections.", 0.74, 5.54, 4.70)
    add_text(slide, 0.74, 6.52, 4.70, 0.28, "Five positions · one choice per position", size=9.5, color=GREEN, bold=True)
    add_footer(slide, 7)
    notes(slide, "The ballot contains all five positions. Selections are encrypted in the browser. The voter can challenge a prepared ballot to verify that the ciphertext matches the choices, then cast a fresh ballot.")

    # ── 8. security & integrity ────────────────────────────────────────────
    slide = prs.slides.add_slide(blank)
    slide.background.fill.solid()
    slide.background.fill.fore_color.rgb = DARK
    add_header(slide, "Security & integrity", "Controls are enforced by the backend, not the interface", dark=True)
    add_picture_fit(slide, assets["login"], 8.62, 1.78, 3.95, 2.23)
    add_text(slide, 0.74, 1.78, 7.55, 0.32, "Defence in depth across identity, ballot secrecy and evidence", size=12.5, color=CREAM, bold=True)
    left_items = [
        ("Blind credentials", "RSA-FDH signatures; the service signs a blinded secret it never sees."),
        ("Ballot secrecy", "Encrypted ballots have no join path to a voter or credential serial."),
        ("Dual control", "Counting requires the Chairman and Returning Officer; results need approval."),
    ]
    right_items = [
        ("Locked configuration", "Verification controls freeze on the first accepted ballot."),
        ("Append-only audit", "Every staff action is recorded; PostgreSQL blocks updates and deletes."),
        ("MFA & RBAC", "Staff sign-in can require an authenticator code; API permissions are role-checked."),
    ]
    for column, items in enumerate((left_items, right_items)):
        y = 2.42
        for heading, body in items:
            add_rect(slide, 0.74 + column * 3.78, y, 3.47, 1.10, fill=RGBColor(0x0D, 0x3A, 0x26), line=RGBColor(0x2A, 0x57, 0x3F), radius=True)
            add_text(slide, 0.94 + column * 3.78, y + 0.14, 3.08, 0.25, heading, size=10.8, color=GOLD, bold=True)
            add_text(slide, 0.94 + column * 3.78, y + 0.41, 3.04, 0.58, body, size=8.8, color=RGBColor(0xD0, 0xDC, 0xD3), spacing=1.05)
            y += 1.24
    add_text(slide, 8.62, 4.22, 3.95, 0.30, "Controlled staff access", size=10.5, color=GOLD, bold=True)
    add_text(slide, 8.62, 4.52, 3.94, 0.66, "Role-based access, audited sign-in and optional multi-factor authentication.", size=9.5, color=RGBColor(0xD0, 0xDC, 0xD3), spacing=1.10)
    add_footer(slide, 8, dark=True)
    notes(slide, "The platform separates identity from the ballot. Administrators cannot see selections, and no single official can count or declare a result alone. All privileged actions are audited.")

    # ── 9. test evidence ───────────────────────────────────────────────────
    slide = prs.slides.add_slide(blank)
    slide.background.fill.solid()
    slide.background.fill.fore_color.rgb = CREAM
    add_header(slide, "Test evidence", "The critical paths were exercised before hand-off")
    add_rect(slide, 0.74, 1.82, 3.65, 1.36, fill=PAPER, line=LINE, radius=True)
    add_rect(slide, 4.62, 1.82, 3.65, 1.36, fill=PAPER, line=LINE, radius=True)
    add_rect(slide, 8.50, 1.82, 4.05, 1.36, fill=PAPER, line=LINE, radius=True)
    add_stat(slide, 0.98, 1.98, "14/14", "simultaneous OTP checks", width=3.1)
    add_stat(slide, 4.86, 1.98, "27/27", "mock election checks", width=3.1)
    add_stat(slide, 8.74, 1.98, "0", "duplicate accreditations", width=3.3)
    add_text(slide, 0.76, 3.48, 5.85, 0.36, "What the delivery suite covers", size=15, color=INK, bold=True, font=DISPLAY)
    checks = [
        "One shared OTP across Resend, Termii and Meta payloads",
        "Verification through the SMS copy completes accreditation",
        "Duplicate verification is rejected; one accreditation remains",
        "Partial email failure does not cancel SMS or WhatsApp",
        "All-provider failure returns 502 with no usable OTP",
        "Expiry, five-attempt lockout and resend cooldown",
        "WhatsApp consent gating, contact privacy and monitoring",
        "Production fails closed without a configured provider",
    ]
    for index, check in enumerate(checks):
        col = index // 4
        row = index % 4
        add_text(slide, 0.80 + col * 6.05, 3.98 + row * 0.55, 0.20, 0.22, "✓", size=11, color=GREEN, bold=True)
        add_text(slide, 1.05 + col * 6.05, 3.96 + row * 0.55, 5.45, 0.30, check, size=10, color=MUTED, spacing=1.0)
    add_rect(slide, 0.74, 6.28, 11.80, 0.55, fill=GOLD_LIGHT, radius=True)
    add_text(slide, 0.94, 6.41, 11.35, 0.26, "Mock providers were used. Live Resend, Termii and Meta delivery must still be verified with the committee's approved sender and template.", size=8.9, color=RGBColor(0x5C, 0x4A, 0x00), bold=True)
    add_footer(slide, 9)
    notes(slide, "The OTP suite passed 14 checks, including simultaneous fan-out, partial provider failure and duplicate accreditation. The full election smoke suite passed 27 checks. Live provider credentials are still required before election day.")

    # ── 10. go-live checklist ──────────────────────────────────────────────
    slide = prs.slides.add_slide(blank)
    slide.background.fill.solid()
    slide.background.fill.fore_color.rgb = CREAM
    add_header(slide, "Readiness", "Before the election opens")
    add_text(slide, 0.74, 1.72, 11.6, 0.36, "A short, explicit checklist keeps configuration and governance in sync.", size=12.5, color=MUTED)
    columns = [
        ("01", "Providers", ["Verify Resend domain (SPF/DKIM/DMARC)", "Approve Termii sender ID", "Approve Meta authentication template", "Record WhatsApp consent"]),
        ("02", "Configuration", ["Set secrets in the server environment", "Run scripts/preflight.py", "Run scripts/check_delivery.py", "Restart the API after changes"]),
        ("03", "Live tests", ["Send to committee devices", "Confirm all three channels", "Test expiry and wrong codes", "Test duplicate accreditation"]),
        ("04", "Governance", ["Independent crypto review", "Committee pilot", "Backup restore drill", "Publish support contacts"]),
    ]
    for index, (number, heading, items) in enumerate(columns):
        x = 0.74 + index * 3.08
        add_rect(slide, x, 2.35, 2.75, 3.78, fill=PAPER, line=LINE, radius=True)
        add_text(slide, x + 0.22, 2.54, 0.50, 0.30, number, size=15, color=GOLD, bold=True, font=DISPLAY)
        add_text(slide, x + 0.22, 2.91, 2.28, 0.32, heading, size=13.5, color=INK, bold=True)
        y = 3.42
        for item in items:
            add_text(slide, x + 0.22, y, 0.18, 0.20, "□", size=11, color=GREEN, bold=True)
            add_text(slide, x + 0.45, y, 2.05, 0.52, item, size=8.7, color=MUTED, spacing=1.02)
            y += 0.55
    add_text(slide, 0.74, 6.38, 11.80, 0.38, "No production credential is included in this deck or in the repository. The system is ready for configured live testing, not live delivery by default.", size=9.3, color=GREEN, bold=True)
    add_footer(slide, 10)
    notes(slide, "This is the practical go-live path: configure all three providers, run preflight and delivery checks, test with committee devices, and complete the independent review and pilot before opening the election.")

    # ── 11. closing ────────────────────────────────────────────────────────
    slide = prs.slides.add_slide(blank)
    slide.background.fill.solid()
    slide.background.fill.fore_color.rgb = DARK
    add_rect(slide, 0, 0, SW, 0.10, fill=GOLD)
    add_crest(slide, 0.78, 0.72, 0.88)
    add_text(slide, 1.82, 0.88, 6.0, 0.28, "ST. JOHN'S COLLEGE JOS · ALUMNI ASSOCIATION", size=9, color=GOLD, bold=True)
    add_text(slide, 1.82, 1.15, 6.0, 0.28, "ELECTORAL COMMITTEE", size=8.5, color=RGBColor(0xB9, 0xCA, 0xBE), bold=True)
    add_text(slide, 0.86, 2.15, 10.8, 1.05, "One alumnus. One vote.\nIndependently verifiable.", size=39, color=CREAM, font=DISPLAY, spacing=0.95)
    add_line(slide, 0.90, 4.25, 12.40, 4.25, color=RGBColor(0x4C, 0x70, 0x5B), width=1)
    add_text(slide, 0.90, 4.55, 8.8, 0.38, "Questions, committee review and live provider testing", size=14, color=GOLD, bold=True)
    add_text(slide, 0.90, 5.02, 9.6, 0.38, "accreditation@sjcjos-alumni.org", size=13, color=CREAM)
    add_text(slide, 0.90, 6.40, 10.0, 0.30, "2026 Alumni Election · Electoral Committee", size=9, color=RGBColor(0xB9, 0xCA, 0xBE))
    notes(slide, "Close with the committee's next steps: approve the provider configuration, complete live tests on committee devices, and schedule the independent review and pilot.")

    prs.save(DECK)
    print(f"Created {DECK}")
    print(f"Slides: {len(prs.slides)}")


if __name__ == "__main__":
    build()
