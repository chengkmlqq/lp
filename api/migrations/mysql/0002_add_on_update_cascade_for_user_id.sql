-- Migration: Add ON UPDATE CASCADE to all FK constraints referencing users(user_id)
-- Reason: Allows changing user IDs via the user management UI (LP-138)
-- Applied: 2026-07-26

ALTER TABLE user_roles DROP FOREIGN KEY user_roles_user_id_fkey,
  ADD CONSTRAINT user_roles_user_id_fkey FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE ON UPDATE CASCADE;

ALTER TABLE auth_sessions DROP FOREIGN KEY auth_sessions_user_id_fkey,
  ADD CONSTRAINT auth_sessions_user_id_fkey FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE ON UPDATE CASCADE;

ALTER TABLE ai_chat_conversations DROP FOREIGN KEY ai_chat_conversations_user_id_fkey,
  ADD CONSTRAINT ai_chat_conversations_user_id_fkey FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE ON UPDATE CASCADE;

ALTER TABLE audit_logs DROP FOREIGN KEY audit_logs_user_id_fkey,
  ADD CONSTRAINT audit_logs_user_id_fkey FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE SET NULL ON UPDATE CASCADE;

ALTER TABLE scheduled_tasks DROP FOREIGN KEY scheduled_tasks_create_user_fkey,
  ADD CONSTRAINT scheduled_tasks_create_user_fkey FOREIGN KEY (create_user) REFERENCES users(user_id) ON DELETE SET NULL ON UPDATE CASCADE;

ALTER TABLE scheduled_tasks DROP FOREIGN KEY scheduled_tasks_update_user_fkey,
  ADD CONSTRAINT scheduled_tasks_update_user_fkey FOREIGN KEY (update_user) REFERENCES users(user_id) ON DELETE SET NULL ON UPDATE CASCADE;

ALTER TABLE system_params DROP FOREIGN KEY system_params_created_by_user_id_fkey,
  ADD CONSTRAINT system_params_created_by_user_id_fkey FOREIGN KEY (created_by_user_id) REFERENCES users(user_id) ON DELETE SET NULL ON UPDATE CASCADE;

ALTER TABLE system_params DROP FOREIGN KEY system_params_updated_by_user_id_fkey,
  ADD CONSTRAINT system_params_updated_by_user_id_fkey FOREIGN KEY (updated_by_user_id) REFERENCES users(user_id) ON DELETE SET NULL ON UPDATE CASCADE;

ALTER TABLE file_index_entries DROP FOREIGN KEY file_index_entries_last_synced_by_user_id_fkey,
  ADD CONSTRAINT file_index_entries_last_synced_by_user_id_fkey FOREIGN KEY (last_synced_by_user_id) REFERENCES users(user_id) ON DELETE SET NULL ON UPDATE CASCADE;
