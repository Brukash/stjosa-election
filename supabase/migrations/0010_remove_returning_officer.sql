-- The Returning Officer office is retired.
--
-- The committee asked the Chairman to conduct the election end to end, so no
-- step requires a second office. The application's role catalogue no longer
-- lists returning_officer; this removes the rows an existing database may still
-- hold, and is safe to run more than once.
--
-- An account that held only this office keeps its profile but ends up with no
-- role, and therefore no permission, until the Super Administrator assigns it a
-- real one in Admin -> Team & roles.

DELETE FROM user_roles
WHERE role_id IN (SELECT id FROM roles WHERE key = 'returning_officer');

DELETE FROM roles WHERE key = 'returning_officer';
