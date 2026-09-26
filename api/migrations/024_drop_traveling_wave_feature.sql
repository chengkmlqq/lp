-- Remove the traveling-wave (行波分析) feature entirely:
--    1) drop the job table (and its indexes)
--    2) drop permission rows traveling_wave.read / traveling_wave.manage
--       (role_permissions links clear via ON DELETE CASCADE)
--    3) drop the admin menu entry (role_menus links clear via ON DELETE CASCADE)
-- Safe on fresh installs / already-clean DBs: IF EXISTS + targeted deletes.

DROP TABLE IF EXISTS traveling_wave_job;

DELETE FROM permissions
WHERE code IN ('traveling_wave.read', 'traveling_wave.manage');

DELETE FROM menus
WHERE code = 'admin.traveling_wave' OR path = '/admin/traveling-wave';