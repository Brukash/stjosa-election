-- St. John's College Jos Alumni Election Management System
-- Supabase PostgreSQL schema (SRS v1.1 §11).
-- Apply with: supabase db push   (or paste into the Supabase SQL editor)
--
-- Row Level Security, append-only audit protection and service-role grants live
-- in 0002_security.sql. The FastAPI backend connects with a role that bypasses
-- RLS; browser clients never talk to Postgres directly.

CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE profiles (
	id VARCHAR(36) NOT NULL, 
	email VARCHAR(255) NOT NULL, 
	full_name VARCHAR(255) NOT NULL, 
	password_hash VARCHAR(255) NOT NULL, 
	is_active BOOLEAN NOT NULL, 
	mfa_secret VARCHAR(64), 
	mfa_enabled BOOLEAN NOT NULL, 
	last_login_at TIMESTAMP WITH TIME ZONE, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id)
);

CREATE UNIQUE INDEX ix_profiles_email ON profiles (email);
CREATE TABLE roles (
	id VARCHAR(36) NOT NULL, 
	key VARCHAR(64) NOT NULL, 
	name VARCHAR(128) NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (key)
);

CREATE TABLE elections (
	id VARCHAR(36) NOT NULL, 
	title VARCHAR(255) NOT NULL, 
	description TEXT NOT NULL, 
	reference VARCHAR(64) NOT NULL, 
	year INTEGER NOT NULL, 
	opens_at TIMESTAMP WITH TIME ZONE, 
	closes_at TIMESTAMP WITH TIME ZONE, 
	timezone VARCHAR(64) NOT NULL, 
	status VARCHAR(40) NOT NULL, 
	eligibility_rules TEXT NOT NULL, 
	voting_rules TEXT NOT NULL, 
	ballot_style VARCHAR(40) NOT NULL, 
	created_by VARCHAR(36), 
	approved_by VARCHAR(36), 
	approved_at TIMESTAMP WITH TIME ZONE, 
	configuration_hash VARCHAR(128), 
	locked_at TIMESTAMP WITH TIME ZONE, 
	suspended_at TIMESTAMP WITH TIME ZONE, 
	tally_public_key TEXT, 
	signing_public_key TEXT, 
	credential_public_key TEXT, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(created_by) REFERENCES profiles (id), 
	FOREIGN KEY(approved_by) REFERENCES profiles (id)
);

CREATE UNIQUE INDEX ix_elections_reference ON elections (reference);
CREATE INDEX ix_elections_status ON elections (status);
CREATE TABLE audit_logs (
	id VARCHAR(36) NOT NULL, 
	election_id VARCHAR(36), 
	actor_id VARCHAR(36), 
	actor_role VARCHAR(64), 
	action VARCHAR(120) NOT NULL, 
	entity VARCHAR(120), 
	entity_id VARCHAR(64), 
	outcome VARCHAR(20) NOT NULL, 
	ip_address VARCHAR(64), 
	detail JSON, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(election_id) REFERENCES elections (id), 
	FOREIGN KEY(actor_id) REFERENCES profiles (id)
);

CREATE INDEX ix_audit_logs_action ON audit_logs (action);
CREATE INDEX ix_audit_logs_election_id ON audit_logs (election_id);
CREATE INDEX ix_audit_logs_created_at ON audit_logs (created_at);
CREATE TABLE ballot_receipts (
	id VARCHAR(36) NOT NULL, 
	election_id VARCHAR(36) NOT NULL, 
	receipt_number VARCHAR(40) NOT NULL, 
	receipt_hash VARCHAR(128) NOT NULL, 
	ballot_commitment VARCHAR(128) NOT NULL, 
	receipt_ref_encrypted TEXT NOT NULL, 
	issued_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_receipt_hash UNIQUE (election_id, receipt_hash), 
	CONSTRAINT uq_receipt_commitment UNIQUE (election_id, ballot_commitment), 
	FOREIGN KEY(election_id) REFERENCES elections (id)
);

CREATE INDEX ix_ballot_receipts_ballot_commitment ON ballot_receipts (ballot_commitment);
CREATE INDEX ix_ballot_receipts_election_id ON ballot_receipts (election_id);
CREATE TABLE challenged_ballots (
	id VARCHAR(36) NOT NULL, 
	election_id VARCHAR(36) NOT NULL, 
	ballot_hash VARCHAR(128) NOT NULL, 
	ciphertext TEXT NOT NULL, 
	encrypted_key TEXT NOT NULL, 
	nonce VARCHAR(64) NOT NULL, 
	revealed_selections JSON NOT NULL, 
	proof JSON NOT NULL, 
	challenged_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	counted BOOLEAN NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(election_id) REFERENCES elections (id)
);

CREATE INDEX ix_challenged_ballots_election_id ON challenged_ballots (election_id);
CREATE TABLE configuration_changes (
	id VARCHAR(36) NOT NULL, 
	election_id VARCHAR(36) NOT NULL, 
	changed_fields JSON NOT NULL, 
	previous_hash VARCHAR(128), 
	new_hash VARCHAR(128), 
	reason TEXT NOT NULL, 
	requested_by VARCHAR(36) NOT NULL, 
	approvals JSON NOT NULL, 
	status VARCHAR(20) NOT NULL, 
	effective_at TIMESTAMP WITH TIME ZONE, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(election_id) REFERENCES elections (id), 
	FOREIGN KEY(requested_by) REFERENCES profiles (id)
);

CREATE INDEX ix_configuration_changes_election_id ON configuration_changes (election_id);
CREATE TABLE election_configuration_approvals (
	id VARCHAR(36) NOT NULL, 
	election_id VARCHAR(36) NOT NULL, 
	settings_hash VARCHAR(128) NOT NULL, 
	approver_id VARCHAR(36) NOT NULL, 
	approver_role VARCHAR(64) NOT NULL, 
	approval_status VARCHAR(40) NOT NULL, 
	note TEXT, 
	approved_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(election_id) REFERENCES elections (id), 
	FOREIGN KEY(approver_id) REFERENCES profiles (id)
);

CREATE INDEX ix_election_configuration_approvals_election_id ON election_configuration_approvals (election_id);
CREATE TABLE election_documents (
	id VARCHAR(36) NOT NULL, 
	election_id VARCHAR(36) NOT NULL, 
	kind VARCHAR(60) NOT NULL, 
	title VARCHAR(255) NOT NULL, 
	content_hash VARCHAR(128) NOT NULL, 
	signature TEXT, 
	payload JSON, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(election_id) REFERENCES elections (id)
);

CREATE INDEX ix_election_documents_election_id ON election_documents (election_id);
CREATE TABLE election_events (
	id VARCHAR(36) NOT NULL, 
	election_id VARCHAR(36) NOT NULL, 
	event_type VARCHAR(80) NOT NULL, 
	message TEXT NOT NULL, 
	actor_id VARCHAR(36), 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(election_id) REFERENCES elections (id), 
	FOREIGN KEY(actor_id) REFERENCES profiles (id)
);

CREATE INDEX ix_election_events_election_id ON election_events (election_id);
CREATE TABLE election_positions (
	id VARCHAR(36) NOT NULL, 
	election_id VARCHAR(36) NOT NULL, 
	title VARCHAR(160) NOT NULL, 
	description TEXT NOT NULL, 
	seats INTEGER NOT NULL, 
	order_index INTEGER NOT NULL, 
	approved BOOLEAN NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_position_title UNIQUE (election_id, title), 
	FOREIGN KEY(election_id) REFERENCES elections (id)
);

CREATE INDEX ix_election_positions_election_id ON election_positions (election_id);
CREATE TABLE election_verification_settings (
	id VARCHAR(36) NOT NULL, 
	election_id VARCHAR(36) NOT NULL, 
	ballot_inclusion_enabled BOOLEAN NOT NULL, 
	private_selection_enabled BOOLEAN NOT NULL, 
	public_commitment_list_enabled BOOLEAN NOT NULL, 
	pdf_receipt_enabled BOOLEAN NOT NULL, 
	configured_by VARCHAR(36), 
	approved_by VARCHAR(36), 
	approved_at TIMESTAMP WITH TIME ZONE, 
	locked_at TIMESTAMP WITH TIME ZONE, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (election_id), 
	FOREIGN KEY(election_id) REFERENCES elections (id), 
	FOREIGN KEY(configured_by) REFERENCES profiles (id), 
	FOREIGN KEY(approved_by) REFERENCES profiles (id)
);

CREATE TABLE published_commitment_batches (
	id VARCHAR(36) NOT NULL, 
	election_id VARCHAR(36) NOT NULL, 
	batch_reference VARCHAR(64) NOT NULL, 
	commitment_count INTEGER NOT NULL, 
	merkle_root VARCHAR(128) NOT NULL, 
	digital_signature TEXT NOT NULL, 
	signed_payload JSON NOT NULL, 
	published_at TIMESTAMP WITH TIME ZONE, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_batch_reference UNIQUE (election_id, batch_reference), 
	FOREIGN KEY(election_id) REFERENCES elections (id)
);

CREATE INDEX ix_published_commitment_batches_election_id ON published_commitment_batches (election_id);
CREATE TABLE spent_credentials (
	id VARCHAR(36) NOT NULL, 
	election_id VARCHAR(36) NOT NULL, 
	token_hash VARCHAR(128) NOT NULL, 
	spent_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_spent_token UNIQUE (election_id, token_hash), 
	FOREIGN KEY(election_id) REFERENCES elections (id)
);

CREATE INDEX ix_spent_credentials_token_hash ON spent_credentials (token_hash);
CREATE INDEX ix_spent_credentials_election_id ON spent_credentials (election_id);
CREATE TABLE tally_authorisations (
	id VARCHAR(36) NOT NULL, 
	election_id VARCHAR(36) NOT NULL, 
	profile_id VARCHAR(36) NOT NULL, 
	role_key VARCHAR(64) NOT NULL, 
	authorised_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_tally_authoriser UNIQUE (election_id, profile_id), 
	FOREIGN KEY(election_id) REFERENCES elections (id), 
	FOREIGN KEY(profile_id) REFERENCES profiles (id)
);

CREATE INDEX ix_tally_authorisations_election_id ON tally_authorisations (election_id);
CREATE TABLE tally_runs (
	id VARCHAR(36) NOT NULL, 
	election_id VARCHAR(36) NOT NULL, 
	status VARCHAR(20) NOT NULL, 
	started_by VARCHAR(36), 
	started_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	finished_at TIMESTAMP WITH TIME ZONE, 
	accepted_ballots INTEGER NOT NULL, 
	challenged_ballots INTEGER NOT NULL, 
	valid_ballots INTEGER NOT NULL, 
	invalid_ballots INTEGER NOT NULL, 
	evidence_hash VARCHAR(128), 
	signature TEXT, 
	reconciliation JSON, 
	PRIMARY KEY (id), 
	FOREIGN KEY(election_id) REFERENCES elections (id), 
	FOREIGN KEY(started_by) REFERENCES profiles (id)
);

CREATE INDEX ix_tally_runs_election_id ON tally_runs (election_id);
CREATE TABLE user_roles (
	id VARCHAR(36) NOT NULL, 
	profile_id VARCHAR(36) NOT NULL, 
	role_id VARCHAR(36) NOT NULL, 
	election_id VARCHAR(36), 
	PRIMARY KEY (id), 
	CONSTRAINT uq_user_role UNIQUE (profile_id, role_id), 
	FOREIGN KEY(profile_id) REFERENCES profiles (id), 
	FOREIGN KEY(role_id) REFERENCES roles (id), 
	FOREIGN KEY(election_id) REFERENCES elections (id)
);

CREATE INDEX ix_user_roles_role_id ON user_roles (role_id);
CREATE INDEX ix_user_roles_profile_id ON user_roles (profile_id);
CREATE TABLE voters (
	id VARCHAR(36) NOT NULL, 
	election_id VARCHAR(36) NOT NULL, 
	voter_id VARCHAR(64) NOT NULL, 
	full_name VARCHAR(200) NOT NULL, 
	email VARCHAR(255), 
	phone VARCHAR(40), 
	alumni_set VARCHAR(64) NOT NULL, 
	graduation_year INTEGER, 
	is_eligible BOOLEAN NOT NULL, 
	register_status VARCHAR(20) NOT NULL, 
	imported_by VARCHAR(36), 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_voter_per_election UNIQUE (election_id, voter_id), 
	FOREIGN KEY(election_id) REFERENCES elections (id), 
	FOREIGN KEY(imported_by) REFERENCES profiles (id)
);

CREATE INDEX ix_voters_voter_id ON voters (voter_id);
CREATE INDEX ix_voters_election_id ON voters (election_id);
CREATE TABLE accreditation_records (
	id VARCHAR(36) NOT NULL, 
	election_id VARCHAR(36) NOT NULL, 
	voter_row_id VARCHAR(36) NOT NULL, 
	accredited_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	ip_address VARCHAR(64), 
	method VARCHAR(40) NOT NULL, 
	note TEXT, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_accreditation UNIQUE (election_id, voter_row_id), 
	FOREIGN KEY(election_id) REFERENCES elections (id), 
	FOREIGN KEY(voter_row_id) REFERENCES voters (id)
);

CREATE INDEX ix_accreditation_records_election_id ON accreditation_records (election_id);
CREATE INDEX ix_accreditation_records_voter_row_id ON accreditation_records (voter_row_id);
CREATE TABLE accreditation_sessions (
	id VARCHAR(36) NOT NULL, 
	election_id VARCHAR(36) NOT NULL, 
	voter_row_id VARCHAR(36) NOT NULL, 
	token_hash VARCHAR(128) NOT NULL, 
	expires_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	consumed_at TIMESTAMP WITH TIME ZONE, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(election_id) REFERENCES elections (id), 
	FOREIGN KEY(voter_row_id) REFERENCES voters (id), 
	UNIQUE (token_hash)
);

CREATE INDEX ix_accreditation_sessions_election_id ON accreditation_sessions (election_id);
CREATE TABLE ballot_commitments (
	id VARCHAR(36) NOT NULL, 
	election_id VARCHAR(36) NOT NULL, 
	ballot_commitment VARCHAR(128) NOT NULL, 
	ballot_proof JSON, 
	commitment_status VARCHAR(20) NOT NULL, 
	batch_id VARCHAR(36), 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_commitment UNIQUE (election_id, ballot_commitment), 
	FOREIGN KEY(election_id) REFERENCES elections (id), 
	FOREIGN KEY(batch_id) REFERENCES published_commitment_batches (id)
);

CREATE INDEX ix_ballot_commitments_batch_id ON ballot_commitments (batch_id);
CREATE INDEX ix_ballot_commitments_election_id ON ballot_commitments (election_id);
CREATE TABLE ballots (
	id VARCHAR(36) NOT NULL, 
	election_id VARCHAR(36) NOT NULL, 
	ciphertext TEXT NOT NULL, 
	encrypted_key TEXT NOT NULL, 
	nonce VARCHAR(64) NOT NULL, 
	ballot_commitment VARCHAR(128) NOT NULL, 
	selection_count INTEGER NOT NULL, 
	accepted BOOLEAN NOT NULL, 
	cast_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	batch_id VARCHAR(36), 
	PRIMARY KEY (id), 
	FOREIGN KEY(election_id) REFERENCES elections (id), 
	FOREIGN KEY(batch_id) REFERENCES published_commitment_batches (id)
);

CREATE INDEX ix_ballots_election_id ON ballots (election_id);
CREATE INDEX ix_ballot_election_cast ON ballots (election_id, cast_at);
CREATE TABLE candidates (
	id VARCHAR(36) NOT NULL, 
	election_id VARCHAR(36) NOT NULL, 
	position_id VARCHAR(36) NOT NULL, 
	full_name VARCHAR(200) NOT NULL, 
	photo_url TEXT, 
	bio TEXT NOT NULL, 
	manifesto TEXT NOT NULL, 
	order_index INTEGER NOT NULL, 
	approved BOOLEAN NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(election_id) REFERENCES elections (id), 
	FOREIGN KEY(position_id) REFERENCES election_positions (id)
);

CREATE INDEX ix_candidates_position_id ON candidates (position_id);
CREATE INDEX ix_candidates_election_id ON candidates (election_id);
CREATE TABLE notification_deliveries (
	id VARCHAR(36) NOT NULL, 
	election_id VARCHAR(36) NOT NULL, 
	voter_row_id VARCHAR(36), 
	challenge_id VARCHAR(64), 
	channel VARCHAR(20) NOT NULL, 
	provider VARCHAR(30) NOT NULL, 
	status VARCHAR(20) NOT NULL, 
	recipient_masked VARCHAR(120) NOT NULL, 
	provider_message_id VARCHAR(160), 
	error TEXT, 
	request_ip VARCHAR(64), 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(election_id) REFERENCES elections (id), 
	FOREIGN KEY(voter_row_id) REFERENCES voters (id)
);

CREATE INDEX ix_notification_deliveries_challenge_id ON notification_deliveries (challenge_id);
CREATE INDEX ix_notification_deliveries_created_at ON notification_deliveries (created_at);
CREATE INDEX ix_notification_deliveries_election_id ON notification_deliveries (election_id);
CREATE TABLE otp_challenges (
	id VARCHAR(36) NOT NULL, 
	election_id VARCHAR(36) NOT NULL, 
	voter_row_id VARCHAR(36) NOT NULL, 
	otp_hash VARCHAR(128) NOT NULL, 
	expires_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	attempts INTEGER NOT NULL, 
	max_attempts INTEGER NOT NULL, 
	consumed_at TIMESTAMP WITH TIME ZONE, 
	request_ip VARCHAR(64), 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(election_id) REFERENCES elections (id), 
	FOREIGN KEY(voter_row_id) REFERENCES voters (id)
);

CREATE INDEX ix_otp_challenges_election_id ON otp_challenges (election_id);
CREATE INDEX ix_otp_challenges_voter_row_id ON otp_challenges (voter_row_id);
CREATE TABLE result_approvals (
	id VARCHAR(36) NOT NULL, 
	election_id VARCHAR(36) NOT NULL, 
	tally_run_id VARCHAR(36) NOT NULL, 
	stage VARCHAR(30) NOT NULL, 
	approver_id VARCHAR(36) NOT NULL, 
	approver_role VARCHAR(64) NOT NULL, 
	approval_status VARCHAR(30) NOT NULL, 
	comments TEXT, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(election_id) REFERENCES elections (id), 
	FOREIGN KEY(tally_run_id) REFERENCES tally_runs (id), 
	FOREIGN KEY(approver_id) REFERENCES profiles (id)
);

CREATE INDEX ix_result_approvals_election_id ON result_approvals (election_id);
CREATE TABLE result_declarations (
	id VARCHAR(36) NOT NULL, 
	election_id VARCHAR(36) NOT NULL, 
	tally_run_id VARCHAR(36) NOT NULL, 
	version INTEGER NOT NULL, 
	is_current BOOLEAN NOT NULL, 
	figures JSON NOT NULL, 
	signature TEXT NOT NULL, 
	signed_payload_hash VARCHAR(128) NOT NULL, 
	correction_reason TEXT, 
	declared_by VARCHAR(36) NOT NULL, 
	declared_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(election_id) REFERENCES elections (id), 
	FOREIGN KEY(tally_run_id) REFERENCES tally_runs (id), 
	FOREIGN KEY(declared_by) REFERENCES profiles (id)
);

CREATE INDEX ix_result_declarations_election_id ON result_declarations (election_id);
CREATE TABLE tally_proofs (
	id VARCHAR(36) NOT NULL, 
	tally_run_id VARCHAR(36) NOT NULL, 
	election_id VARCHAR(36) NOT NULL, 
	ballot_commitment VARCHAR(128) NOT NULL, 
	merkle_proof JSON NOT NULL, 
	ballot_hash VARCHAR(128) NOT NULL, 
	chain_hash VARCHAR(128) NOT NULL, 
	counted BOOLEAN NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(tally_run_id) REFERENCES tally_runs (id), 
	FOREIGN KEY(election_id) REFERENCES elections (id)
);

CREATE INDEX ix_tally_proofs_tally_run_id ON tally_proofs (tally_run_id);
CREATE TABLE credential_issuances (
	id VARCHAR(36) NOT NULL, 
	election_id VARCHAR(36) NOT NULL, 
	accreditation_id VARCHAR(36) NOT NULL, 
	blinded_request_hash VARCHAR(128) NOT NULL, 
	issued_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	status VARCHAR(20) NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_blinded_request UNIQUE (election_id, blinded_request_hash), 
	FOREIGN KEY(election_id) REFERENCES elections (id), 
	FOREIGN KEY(accreditation_id) REFERENCES accreditation_records (id)
);

CREATE INDEX ix_credential_issuances_election_id ON credential_issuances (election_id);
CREATE INDEX ix_credential_issuances_accreditation_id ON credential_issuances (accreditation_id);
CREATE TABLE prepared_ballots (
	id VARCHAR(36) NOT NULL, 
	election_id VARCHAR(36) NOT NULL, 
	token_hash VARCHAR(128) NOT NULL, 
	ciphertext TEXT NOT NULL, 
	encrypted_key TEXT NOT NULL, 
	nonce VARCHAR(64) NOT NULL, 
	commitment VARCHAR(128) NOT NULL, 
	selections JSON, 
	data_key VARCHAR(128), 
	key_commitment VARCHAR(128) NOT NULL, 
	status VARCHAR(20) NOT NULL, 
	ballot_id VARCHAR(36), 
	receipt_id VARCHAR(36), 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	expires_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	cleared_at TIMESTAMP WITH TIME ZONE, 
	PRIMARY KEY (id), 
	FOREIGN KEY(election_id) REFERENCES elections (id), 
	FOREIGN KEY(ballot_id) REFERENCES ballots (id), 
	FOREIGN KEY(receipt_id) REFERENCES ballot_receipts (id)
);

CREATE INDEX ix_prepared_ballots_election_id ON prepared_ballots (election_id);
CREATE INDEX ix_prepared_ballots_token_hash ON prepared_ballots (token_hash);
CREATE TABLE tally_results (
	id VARCHAR(36) NOT NULL, 
	tally_run_id VARCHAR(36) NOT NULL, 
	election_id VARCHAR(36) NOT NULL, 
	position_id VARCHAR(36) NOT NULL, 
	candidate_id VARCHAR(36) NOT NULL, 
	votes INTEGER NOT NULL, 
	percentage FLOAT NOT NULL, 
	is_winner BOOLEAN NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(tally_run_id) REFERENCES tally_runs (id), 
	FOREIGN KEY(election_id) REFERENCES elections (id), 
	FOREIGN KEY(position_id) REFERENCES election_positions (id), 
	FOREIGN KEY(candidate_id) REFERENCES candidates (id)
);

CREATE INDEX ix_tally_results_election_id ON tally_results (election_id);
CREATE INDEX ix_tally_results_tally_run_id ON tally_results (tally_run_id);
