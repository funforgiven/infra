\connect netbird
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM accounts) OR NOT EXISTS (SELECT 1 FROM groups)
     OR NOT EXISTS (SELECT 1 FROM zones) OR NOT EXISTS (SELECT 1 FROM records) THEN
    RAISE EXCEPTION 'NetBird configuration missing';
  END IF;
  -- The built-in all-to-all policy must stay disabled.
  IF (SELECT count(*) <> 1 OR bool_or(enabled) FROM policies WHERE name = 'Default') THEN
    RAISE EXCEPTION 'NetBird default policy is not disabled';
  END IF;
END $$;
\connect netbird_auth
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM connector) OR NOT EXISTS (SELECT 1 FROM keys) THEN
    RAISE EXCEPTION 'NetBird identity connector or signing keys missing';
  END IF;
END $$;
\connect netbird_events
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_tables WHERE schemaname = 'public') THEN
    RAISE EXCEPTION 'NetBird event schema missing';
  END IF;
END $$;
