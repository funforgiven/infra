\connect synapse
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM users) OR NOT EXISTS (SELECT 1 FROM events) THEN
    RAISE EXCEPTION 'Synapse accounts or events missing';
  END IF;
END $$;
\connect mas
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM users) OR NOT EXISTS (SELECT 1 FROM upstream_oauth_providers) THEN
    RAISE EXCEPTION 'MAS accounts or identity provider missing';
  END IF;
END $$;
