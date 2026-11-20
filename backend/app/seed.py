"""Idempotent demo/bootstrap seed: roles, authorised accounts, one configured election."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from . import crypto
from .config import settings
from .models import (
    AccreditationRecord,
    Candidate,
    Election,
    ElectionConfigurationApproval,
    ElectionEvent,
    ElectionPosition,
    ElectionVerificationSetting,
    Profile,
    Role,
    UserRole,
    Voter,
)
from .security import ROLE_NAMES, hash_password
from .services import configuration_hash

DEMO_ACCOUNTS = [
    ("superadmin@sjcjos-alumni.org", "Amina Danladi", "super_admin"),
    ("chairman@sjcjos-alumni.org", "Hon. Emmanuel Pam", "chairman"),
    ("accreditation@sjcjos-alumni.org", "Mrs. Grace Gyang", "accreditation_officer"),
    ("observer@sjcjos-alumni.org", "Barr. Halima Sani", "observer"),
]

POSITIONS = [
    ("President", "Leads the Alumni Association and represents all alumni."),
    ("Vice President", "Supports the President and coordinates chapter activities."),
    ("Secretary General", "Custodian of records, minutes and correspondence."),
    ("Financial Secretary", "Oversees association finances and accountability."),
    ("Public Relations Officer", "Manages alumni communication and public engagement."),
]

CANDIDATES = {
    "President": [
        ("Barr. Emmanuel Pam", "Called to the Nigerian Bar in 2009; alumni class of 2004.", "A united alumni body that invests in the college and its students. I will establish a chapter support fund and publish quarterly association accounts."),
        ("Dr. Ngozi Okafor", "Consultant physician and class of 2006 representative.", "Stronger alumni welfare, a functioning endowment, and transparent leadership that reports to every chapter."),
        ("Engr. Musa Ibrahim", "Infrastructure engineer, class of 2003.", "Rebuild the old students' network with practical projects: laboratories, scholarships and mentorship for current students."),
    ],
    "Vice President": [
        ("Sarah Gyang", "Education administrator, class of 2008.", "Coordinate chapters effectively and make alumni participation meaningful at every level."),
        ("Olusegun Adeyemi", "Banking professional, class of 2005.", "Bridge the gap between older and younger alumni with structured mentorship."),
    ],
    "Secretary General": [
        ("Blessing Dachung", "Legal practitioner and class of 2010.", "Accurate records, timely communication and a searchable alumni archive."),
        ("Chidi Okonkwo", "Administrator and class of 2007.", "Professional secretariat services and open minutes for every meeting."),
    ],
    "Financial Secretary": [
        ("Amina Bello", "Chartered accountant, class of 2009.", "Transparent dues, published statements and an independent audit each year."),
        ("Godwin Audu", "Finance officer, class of 2004.", "Disciplined budgeting and a clear endowment fund policy."),
    ],
    "Public Relations Officer": [
        ("Joy Danjuma", "Broadcast journalist, class of 2012.", "Tell the alumni story well and keep every chapter informed."),
        ("Sadiq Lawal", "Digital strategist, class of 2013.", "A modern alumni platform, active social channels and a quarterly newsletter."),
    ],
}

VOTERS = [
    ("SJC/AL/2004/001", "Emeka Nwosu", "Jos Chapter", 2004),
    ("SJC/AL/2004/002", "Ruth Pam", "Jos Chapter", 2004),
    ("SJC/AL/2005/003", "Tunde Balogun", "Lagos Chapter", 2005),
    ("SJC/AL/2005/004", "Fatima Sani", "Abuja Chapter", 2005),
    ("SJC/AL/2006/005", "Chiamaka Eze", "Lagos Chapter", 2006),
    ("SJC/AL/2006/006", "Solomon Audu", "Jos Chapter", 2006),
    ("SJC/AL/2007/007", "Kelechi Umeh", "Diaspora", 2007),
    ("SJC/AL/2007/008", "Yetunde Ojo", "Lagos Chapter", 2007),
    ("SJC/AL/2008/009", "Daniel Gyang", "Jos Chapter", 2008),
    ("SJC/AL/2008/010", "Aisha Bello", "Abuja Chapter", 2008),
    ("SJC/AL/2009/011", "Olumide Adebayo", "Lagos Chapter", 2009),
    ("SJC/AL/2009/012", "Maryam Idris", "Abuja Chapter", 2009),
    ("SJC/AL/2010/013", "Ifeanyi Eze", "Diaspora", 2010),
    ("SJC/AL/2010/014", "Bukola Ajayi", "Lagos Chapter", 2010),
    ("SJC/AL/2011/015", "Peter Danjuma", "Jos Chapter", 2011),
    ("SJC/AL/2011/016", "Zainab Lawal", "Abuja Chapter", 2011),
    ("SJC/AL/2012/017", "Chinedu Obi", "Diaspora", 2012),
    ("SJC/AL/2012/018", "Grace Pam", "Jos Chapter", 2012),
    ("SJC/AL/2013/019", "Ibrahim Musa", "Abuja Chapter", 2013),
    ("SJC/AL/2013/020", "Funmilayo Adeyemi", "Lagos Chapter", 2013),
    ("SJC/AL/2014/021", "Samuel Dachung", "Jos Chapter", 2014),
    ("SJC/AL/2014/022", "Halima Yusuf", "Abuja Chapter", 2014),
    ("SJC/AL/2015/023", "Ngozi Okafor", "Lagos Chapter", 2015),
    ("SJC/AL/2015/024", "Adewale Ogunleye", "Diaspora", 2015),
]


def _slug(name: str) -> str:
    cleaned = "".join(c.lower() if c.isalnum() else "." for c in name)
    while ".." in cleaned:
        cleaned = cleaned.replace("..", ".")
    return cleaned.strip(".")


def seed_database(db: Session) -> dict:
    roles = {}
    for key, name in ROLE_NAMES.items():
        role = db.execute(select(Role).where(Role.key == key)).scalar_one_or_none()
        if not role:
            role = Role(key=key, name=name)
            db.add(role)
            db.flush()
        roles[key] = role

    accounts = {}
    for email, full_name, role_key in DEMO_ACCOUNTS:
        profile = db.execute(select(Profile).where(Profile.email == email)).scalar_one_or_none()
        if not profile:
            profile = Profile(
                email=email,
                full_name=full_name,
                password_hash=hash_password(settings.seed_password),
                is_active=True,
            )
            db.add(profile)
            db.flush()
            db.add(UserRole(profile_id=profile.id, role_id=roles[role_key].id))
        accounts[role_key] = profile
    db.commit()

    existing = db.execute(select(Election).order_by(Election.created_at)).scalars().first()
    if existing:
        # Demo voter records are fictional; keep their WhatsApp consent current
        # when an older development database is upgraded.
        demo_voter_ids = [row[0] for row in VOTERS]
        db.execute(
            update(Voter)
            .where(
                Voter.election_id == existing.id,
                Voter.voter_id.in_(demo_voter_ids),
                Voter.whatsapp_consent.is_(False),
            )
            .values(whatsapp_consent=True)
        )
        db.commit()
        return {"seeded_election": False, "election_id": existing.id, "accounts": DEMO_ACCOUNTS}

    now = datetime.now(timezone.utc)
    election = Election(
        title="St. John's College Jos Alumni Association Election 2026",
        description=(
            "Remote electronic election for the executive positions of the St. John's College Jos "
            "Alumni Association. One accredited alumnus, one verifiable ballot."
        ),
        reference="SJCJ-ALUMNI-2026",
        year=2026,
        opens_at=now - timedelta(hours=1),
        closes_at=now + timedelta(days=14),
        timezone="Africa/Lagos",
        status="draft",
        eligibility_rules=(
            "Only alumni whose records appear on the approved electoral register published by the "
            "Electoral Committee may vote. A Voter ID on the approved register is required."
        ),
        voting_rules=(
            "One ballot per accredited voter. One candidate per position. Selections may not be "
            "changed after the ballot is cast. Challenged ballots are excluded from the count."
        ),
        created_by=accounts["chairman"].id,
    )
    db.add(election)
    db.flush()

    settings_row = ElectionVerificationSetting(
        election_id=election.id,
        ballot_inclusion_enabled=True,
        private_selection_enabled=True,
        public_commitment_list_enabled=True,
        pdf_receipt_enabled=True,
        configured_by=accounts["chairman"].id,
        approved_by=accounts["chairman"].id,
        approved_at=now,
    )
    db.add(settings_row)

    for index, (title, description) in enumerate(POSITIONS):
        position = ElectionPosition(
            election_id=election.id, title=title, description=description,
            order_index=index, seats=1, approved=True,
        )
        db.add(position)
        db.flush()
        for c_index, (name, bio, manifesto) in enumerate(CANDIDATES[title]):
            db.add(Candidate(
                election_id=election.id, position_id=position.id, full_name=name,
                bio=bio, manifesto=manifesto, order_index=c_index, approved=True,
            ))

    for voter_id, full_name, alumni_set, year in VOTERS:
        db.add(Voter(
            election_id=election.id,
            voter_id=voter_id,
            full_name=full_name,
            email=f"{_slug(full_name)}@alumni.sjcjos.edu.ng",
            phone="+234803" + f"{abs(hash(voter_id)) % 10_000_000:07d}",
            # Fictional demo alumni are seeded with WhatsApp consent so all three
            # channels can be exercised locally. Real imports must set it explicitly.
            whatsapp_consent=True,
            alumni_set=alumni_set,
            graduation_year=year,
            is_eligible=True,
            register_status="approved",
            imported_by=accounts["chairman"].id,
        ))
    db.flush()

    election.status = "approved"
    election.approved_by = accounts["chairman"].id
    election.approved_at = now
    election.configuration_hash = configuration_hash(db, election)
    keys = crypto.create_election_keys(election.id)
    election.tally_public_key = keys["tally_public_key"]
    election.signing_public_key = keys["signing_public_key"]
    election.key_material = keys["key_material"]
    election.credential_public_key = json.dumps(crypto.credential_public_numbers())

    db.add(ElectionConfigurationApproval(
        election_id=election.id,
        settings_hash=election.configuration_hash,
        approver_id=accounts["chairman"].id,
        approver_role="chairman",
        approval_status="approved",
        note="Bootstrap configuration approval",
    ))
    for state, message in (
        ("configuration.approved", "Configuration approved by the Chairman"),
        ("status.changed", "Election opened for accreditation"),
        ("status.changed", "Voting opened"),
    ):
        db.add(ElectionEvent(election_id=election.id, event_type=state, message=message))
    election.status = "voting_open"
    db.commit()

    return {
        "seeded_election": True,
        "election_id": election.id,
        "reference": election.reference,
        "voters": len(VOTERS),
        "accounts": DEMO_ACCOUNTS,
        "password": settings.seed_password,
    }
