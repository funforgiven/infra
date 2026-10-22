\connect zitadel
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM eventstore.events2 WHERE event_type = 'instance.added') THEN
    RAISE EXCEPTION 'ZITADEL instance events missing';
  END IF;
END $$;
