SET session_replication_role = replica;
--
-- PostgreSQL database dump
--

\restrict UVXxtXaQlAJfZapskxZfZboeDWXESBEy163oCBkBzCL7LH2c7YFImJpPFUfTR6x

-- Dumped from database version 16.11
-- Dumped by pg_dump version 16.13 (Debian 16.13-1.pgdg12+1)

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Data for Name: menu; Type: TABLE DATA; Schema: public; Owner: -
--

INSERT INTO public.menu (menu_id, create_date, create_user, menu_descr, menu_icon, menu_label, menu_name, menu_type, parent_id, seq, state, update_date, update_user, url) VALUES ('230918229474674353', '2026-02-26 15:53:56.082332', 'chengkai', NULL, 'IconDashboard', '统计报表', 'statistics', 'DIRECTORY', NULL, 60, 'ENABLED', '2026-02-26 16:37:56.667201', 'chengkai', NULL);
INSERT INTO public.menu (menu_id, create_date, create_user, menu_descr, menu_icon, menu_label, menu_name, menu_type, parent_id, seq, state, update_date, update_user, url) VALUES ('179018961361305638', '2026-01-22 14:33:17.029504', 'chengkai', NULL, 'IconFile', '文件管理', 'file-manager', 'MENU', '76320933194760192', 1, 'ENABLED', NULL, NULL, 'file-manager');
INSERT INTO public.menu (menu_id, create_date, create_user, menu_descr, menu_icon, menu_label, menu_name, menu_type, parent_id, seq, state, update_date, update_user, url) VALUES ('187981596035383344', '2026-01-28 15:28:45.750581', 'chengkai', NULL, 'IconCompass', '密钥管理', 'password', 'MENU', '76320933194760192', 1, 'ENABLED', NULL, NULL, 'password');
INSERT INTO public.menu (menu_id, create_date, create_user, menu_descr, menu_icon, menu_label, menu_name, menu_type, parent_id, seq, state, update_date, update_user, url) VALUES ('95606916901765188', '2025-11-27 10:02:19.716799', 'admin', NULL, 'IconCheckCircle', '文件识别', 'filedetector', 'MENU', '76320933194760192', 11, 'ENABLED', NULL, NULL, 'filedetector');
INSERT INTO public.menu (menu_id, create_date, create_user, menu_descr, menu_icon, menu_label, menu_name, menu_type, parent_id, seq, state, update_date, update_user, url) VALUES ('134691737770655774', '2025-12-23 17:50:09.447569', 'admin', NULL, 'IconList', '系统参数', 'systemparam', 'MENU', '192168089637359389', 1, 'ENABLED', '2026-01-31 16:21:41.482418', 'admin', 'systemparam');
INSERT INTO public.menu (menu_id, create_date, create_user, menu_descr, menu_icon, menu_label, menu_name, menu_type, parent_id, seq, state, update_date, update_user, url) VALUES ('26219916348620800', '2025-10-11 15:57:13.568892', 'admin', NULL, 'IconTrophy', '知识管理', 'knowledge_mgr', 'DIRECTORY', NULL, 20, 'ENABLED', '2026-02-26 16:35:59.276875', 'chengkai', NULL);
INSERT INTO public.menu (menu_id, create_date, create_user, menu_descr, menu_icon, menu_label, menu_name, menu_type, parent_id, seq, state, update_date, update_user, url) VALUES ('user_mgr', '2026-01-15 10:03:53.987555', NULL, NULL, NULL, '用户管理', 'user_mgr', 'MENU', '192168089637359577', 1, 'ENABLED', '2026-01-31 16:24:35.912272', 'admin', 'user');
INSERT INTO public.menu (menu_id, create_date, create_user, menu_descr, menu_icon, menu_label, menu_name, menu_type, parent_id, seq, state, update_date, update_user, url) VALUES ('116674882539880455', '2025-12-11 14:30:49.582598', 'admin', NULL, 'IconSearch', 'MD解析', 'mdresolve', 'MENU', '76320933194760192', 1, 'ENABLED', NULL, NULL, 'mdresolve');
INSERT INTO public.menu (menu_id, create_date, create_user, menu_descr, menu_icon, menu_label, menu_name, menu_type, parent_id, seq, state, update_date, update_user, url) VALUES ('role_mgr', '2026-01-15 10:03:53.958729', NULL, NULL, NULL, '角色管理', 'role_mgr', 'MENU', '192168089637359577', 2, 'ENABLED', '2026-01-31 16:24:47.693376', 'admin', 'role');
INSERT INTO public.menu (menu_id, create_date, create_user, menu_descr, menu_icon, menu_label, menu_name, menu_type, parent_id, seq, state, update_date, update_user, url) VALUES ('136067432975434904', '2025-12-24 17:40:40.182517', 'admin', NULL, 'IconEmail', '系统消息', 'systemmessage', 'MENU', '192168089637359328', 1, 'ENABLED', '2026-01-31 16:25:36.266083', 'admin', 'systemmessage');
INSERT INTO public.menu (menu_id, create_date, create_user, menu_descr, menu_icon, menu_label, menu_name, menu_type, parent_id, seq, state, update_date, update_user, url) VALUES ('menu_mgr', '2026-01-15 10:03:53.934009', NULL, NULL, NULL, '菜单管理', 'menu_mgr', 'MENU', '192168089637359577', 3, 'ENABLED', '2026-01-31 16:25:53.732164', 'admin', 'menu');
INSERT INTO public.menu (menu_id, create_date, create_user, menu_descr, menu_icon, menu_label, menu_name, menu_type, parent_id, seq, state, update_date, update_user, url) VALUES ('183524124356771948', '2026-01-25 15:29:16.875486', 'admin', NULL, 'IconApps', '分组管理', 'group', 'MENU', '192168089637359389', 2, 'ENABLED', '2026-01-31 16:27:24.000994', 'admin', 'group');
INSERT INTO public.menu (menu_id, create_date, create_user, menu_descr, menu_icon, menu_label, menu_name, menu_type, parent_id, seq, state, update_date, update_user, url) VALUES ('97505309626466326', '2025-11-28 16:36:12.275314', 'admin', NULL, 'IconWechat', '微信小程序', 'wxapp', 'MENU', '192168089637359389', 4, 'ENABLED', '2026-01-31 16:34:17.623113', 'admin', 'wxapp');
INSERT INTO public.menu (menu_id, create_date, create_user, menu_descr, menu_icon, menu_label, menu_name, menu_type, parent_id, seq, state, update_date, update_user, url) VALUES ('78189209608781860', '2025-11-15 16:19:30.844064', 'admin', NULL, 'IconClockCircle', '定时任务', 'cron_task_mgr', 'MENU', '192168089637359389', 7, 'ENABLED', '2026-01-31 16:35:14.506062', 'admin', 'cron');
INSERT INTO public.menu (menu_id, create_date, create_user, menu_descr, menu_icon, menu_label, menu_name, menu_type, parent_id, seq, state, update_date, update_user, url) VALUES ('76398070807396352', '2025-11-14 11:27:16.25965', 'admin', NULL, 'IconSelectAll', '作业监控', 'job_mgr', 'MENU', '192168089637359328', 3, 'ENABLED', '2026-01-31 16:36:41.120604', 'admin', 'job');
INSERT INTO public.menu (menu_id, create_date, create_user, menu_descr, menu_icon, menu_label, menu_name, menu_type, parent_id, seq, state, update_date, update_user, url) VALUES ('192168089637359328', '2026-01-31 16:12:09.964975', 'chengkai', NULL, 'IconDashboard', '系统监控', 'sys_monitor', 'DIRECTORY', NULL, 80, 'ENABLED', '2026-02-26 16:38:30.731017', 'chengkai', NULL);
INSERT INTO public.menu (menu_id, create_date, create_user, menu_descr, menu_icon, menu_label, menu_name, menu_type, parent_id, seq, state, update_date, update_user, url) VALUES ('144982908908601370', '2025-12-30 16:14:02.748609', 'admin', NULL, 'IconMindMapping', '流程图', 'mermaid-mgr', 'MENU', '26219916348620800', 2, 'ENABLED', '2026-01-31 16:44:16.674058', 'admin', 'mermaid-mgr');
INSERT INTO public.menu (menu_id, create_date, create_user, menu_descr, menu_icon, menu_label, menu_name, menu_type, parent_id, seq, state, update_date, update_user, url) VALUES ('50050233152831502', '2025-10-27 17:23:15.898588', 'admin', NULL, 'IconMindMapping', '思维导图', 'mindmap', 'MENU', '26219916348620800', 1, 'ENABLED', '2026-01-31 16:44:39.131777', 'admin', 'mindmap');
INSERT INTO public.menu (menu_id, create_date, create_user, menu_descr, menu_icon, menu_label, menu_name, menu_type, parent_id, seq, state, update_date, update_user, url) VALUES ('249494272267520435', '2026-03-11 11:48:25.484799', 'chengkai', NULL, NULL, '代码评审', 'code-review', 'MENU', '231081781829304476', 1, 'ENABLED', NULL, NULL, 'code-review');
INSERT INTO public.menu (menu_id, create_date, create_user, menu_descr, menu_icon, menu_label, menu_name, menu_type, parent_id, seq, state, update_date, update_user, url) VALUES ('26266405074632715', '2025-10-11 17:45:40.047878', 'admin', NULL, 'IconBulb', '知识点管理', 'knowledge_point_mgr', 'MENU', '26219916348620800', 5, 'ENABLED', '2026-01-31 16:45:30.722389', 'admin', 'knowledge');
INSERT INTO public.menu (menu_id, create_date, create_user, menu_descr, menu_icon, menu_label, menu_name, menu_type, parent_id, seq, state, update_date, update_user, url) VALUES ('192168089637359577', '2026-01-31 16:24:09.990576', 'admin', NULL, 'IconSafe', '系统权限', 'sys_priv', 'DIRECTORY', NULL, 90, 'ENABLED', '2026-02-26 16:38:51.092536', 'chengkai', NULL);
INSERT INTO public.menu (menu_id, create_date, create_user, menu_descr, menu_icon, menu_label, menu_name, menu_type, parent_id, seq, state, update_date, update_user, url) VALUES ('26266405074632728', '2025-10-11 17:50:57.895956', 'admin', NULL, 'IconStar', '题库管理', 'question_mgr', 'MENU', '192168089637360097', 1, 'ENABLED', '2026-01-31 16:48:34.000613', 'admin', 'question');
INSERT INTO public.menu (menu_id, create_date, create_user, menu_descr, menu_icon, menu_label, menu_name, menu_type, parent_id, seq, state, update_date, update_user, url) VALUES ('26266405074632743', '2025-10-11 18:38:59.576273', 'admin', NULL, 'IconCheckCircle', '试题管理', 'exam_mgr', 'MENU', '192168089637360097', 2, 'ENABLED', '2026-01-31 16:48:50.844338', 'admin', 'exam');
INSERT INTO public.menu (menu_id, create_date, create_user, menu_descr, menu_icon, menu_label, menu_name, menu_type, parent_id, seq, state, update_date, update_user, url) VALUES ('42365316889575424', '2025-10-22 13:17:33.872891', 'admin', NULL, NULL, '历史答卷', 'history', 'MENU', '192168089637360097', 3, 'ENABLED', '2026-01-31 16:49:09.142567', 'admin', 'history');
INSERT INTO public.menu (menu_id, create_date, create_user, menu_descr, menu_icon, menu_label, menu_name, menu_type, parent_id, seq, state, update_date, update_user, url) VALUES ('204073687442261831', '2026-02-08 14:04:07.74672', 'chengkai', NULL, 'IconTag', '标签管理', 'tag', 'MENU', '192168089637359389', 1, 'ENABLED', NULL, NULL, 'tag');
INSERT INTO public.menu (menu_id, create_date, create_user, menu_descr, menu_icon, menu_label, menu_name, menu_type, parent_id, seq, state, update_date, update_user, url) VALUES ('204073687442262076', '2026-02-08 14:11:00.976474', 'chengkai', NULL, 'IconStar', 'Token统计', 'token-usage', 'MENU', '192168089637359328', 1, 'ENABLED', NULL, NULL, 'token-usage');
INSERT INTO public.menu (menu_id, create_date, create_user, menu_descr, menu_icon, menu_label, menu_name, menu_type, parent_id, seq, state, update_date, update_user, url) VALUES ('118741569263112860', '2025-12-15 10:32:05.437321', 'admin', NULL, 'IconSchedule', '日程管理', 'schedule', 'MENU', '230918229474674260', 1, 'ENABLED', '2026-02-26 15:50:19.257239', 'chengkai', 'schedule');
INSERT INTO public.menu (menu_id, create_date, create_user, menu_descr, menu_icon, menu_label, menu_name, menu_type, parent_id, seq, state, update_date, update_user, url) VALUES ('32015218800328704', '2025-10-15 13:46:51.152678', 'admin', NULL, 'IconList', '待办管理', 'todo', 'MENU', '230918229474674260', 2, 'ENABLED', '2026-02-26 15:50:40.733078', 'chengkai', 'todo');
INSERT INTO public.menu (menu_id, create_date, create_user, menu_descr, menu_icon, menu_label, menu_name, menu_type, parent_id, seq, state, update_date, update_user, url) VALUES ('133133918772658432', '2025-12-22 16:58:19.89401', 'admin', NULL, 'IconSend', '消息测试', 'notification', 'MENU', '231016189088760729', 1, 'ENABLED', '2026-02-26 16:17:03.175302', 'chengkai', 'notification');
INSERT INTO public.menu (menu_id, create_date, create_user, menu_descr, menu_icon, menu_label, menu_name, menu_type, parent_id, seq, state, update_date, update_user, url) VALUES ('200511080789709743', '2026-02-06 08:56:53.11937', 'chengkai', NULL, NULL, 'Jwt生成器', 'jwt-generator', 'MENU', '231016189088760729', 1, 'ENABLED', '2026-02-26 16:18:03.12509', 'chengkai', 'jwt-generator');
INSERT INTO public.menu (menu_id, create_date, create_user, menu_descr, menu_icon, menu_label, menu_name, menu_type, parent_id, seq, state, update_date, update_user, url) VALUES ('227758868711604253', '2026-02-24 10:36:48.59366', 'admin', NULL, NULL, '单词本', 'vocabulary', 'MENU', '26219916348620800', 1, 'ENABLED', '2026-02-26 16:19:03.551691', 'chengkai', 'vocabulary');
INSERT INTO public.menu (menu_id, create_date, create_user, menu_descr, menu_icon, menu_label, menu_name, menu_type, parent_id, seq, state, update_date, update_user, url) VALUES ('176068731145814769', '2026-01-20 15:50:51.269739', 'chengkai', NULL, 'IconCustomerService', 'AI聊天', 'chat', 'MENU', '231081781829304476', 1, 'ENABLED', '2026-02-26 16:25:17.222513', 'chengkai', 'chat');
INSERT INTO public.menu (menu_id, create_date, create_user, menu_descr, menu_icon, menu_label, menu_name, menu_type, parent_id, seq, state, update_date, update_user, url) VALUES ('221032245551432906', '2026-02-19 23:26:05.346579', 'chengkai', NULL, 'IconRobot', '智能体管理', 'agent', 'MENU', '231081781829304476', 1, 'ENABLED', '2026-02-26 16:25:39.55366', 'chengkai', 'agent');
INSERT INTO public.menu (menu_id, create_date, create_user, menu_descr, menu_icon, menu_label, menu_name, menu_type, parent_id, seq, state, update_date, update_user, url) VALUES ('215028070250185143', '2026-02-15 21:04:38.284379', 'chengkai', NULL, NULL, '需求管理', 'requirement', 'MENU', '231081781829304476', 1, 'ENABLED', '2026-02-26 16:33:19.391789', 'chengkai', 'requirement');
INSERT INTO public.menu (menu_id, create_date, create_user, menu_descr, menu_icon, menu_label, menu_name, menu_type, parent_id, seq, state, update_date, update_user, url) VALUES ('192168089637360097', '2026-01-31 16:47:46.618712', 'admin', NULL, 'IconCheckCircle', '考试与练习', 'exam_system', 'DIRECTORY', NULL, 30, 'ENABLED', '2026-02-26 16:36:12.113632', 'chengkai', NULL);
INSERT INTO public.menu (menu_id, create_date, create_user, menu_descr, menu_icon, menu_label, menu_name, menu_type, parent_id, seq, state, update_date, update_user, url) VALUES ('231081781829304476', '2026-02-26 16:24:46.688317', 'chengkai', NULL, NULL, 'AI应用', 'ai_app', 'DIRECTORY', NULL, 40, 'ENABLED', '2026-02-26 16:36:28.836651', 'chengkai', NULL);
INSERT INTO public.menu (menu_id, create_date, create_user, menu_descr, menu_icon, menu_label, menu_name, menu_type, parent_id, seq, state, update_date, update_user, url) VALUES ('76320933194760192', '2025-11-14 10:04:08.405597', 'admin', NULL, 'IconTool', '实用工具', 'tools', 'DIRECTORY', NULL, 50, 'ENABLED', '2026-02-26 16:36:45.8529', 'chengkai', NULL);
INSERT INTO public.menu (menu_id, create_date, create_user, menu_descr, menu_icon, menu_label, menu_name, menu_type, parent_id, seq, state, update_date, update_user, url) VALUES ('115181144453940054', '2025-12-10 16:42:47.47134', 'admin', NULL, 'IconScan', '文字提取', 'ocr', 'MENU', '231081781829304476', 1, 'ENABLED', '2026-02-26 16:43:13.471066', 'chengkai', 'ocr');
INSERT INTO public.menu (menu_id, create_date, create_user, menu_descr, menu_icon, menu_label, menu_name, menu_type, parent_id, seq, state, update_date, update_user, url) VALUES ('40875083496948222', '2025-10-21 14:11:08.428707', 'admin', NULL, 'IconBulb', '模型管理', 'llmmodel', 'MENU', '231081781829304476', 9, 'ENABLED', '2026-02-28 14:17:15.92645', 'chengkai', 'llmmodel');
INSERT INTO public.menu (menu_id, create_date, create_user, menu_descr, menu_icon, menu_label, menu_name, menu_type, parent_id, seq, state, update_date, update_user, url) VALUES ('235407982127480885', '2026-03-01 14:19:24.42814', 'chengkai', NULL, NULL, '诗词本', 'poetry', 'MENU', '26219916348620800', 1, 'ENABLED', NULL, NULL, 'poetry');
INSERT INTO public.menu (menu_id, create_date, create_user, menu_descr, menu_icon, menu_label, menu_name, menu_type, parent_id, seq, state, update_date, update_user, url) VALUES ('241356649271395924', '2026-03-05 15:48:38.663647', 'chengkai', NULL, 'IconGift', 'Git管理', 'git-desktop', 'MENU', '192168089637359328', 1, 'ENABLED', NULL, NULL, 'git-desktop');
INSERT INTO public.menu (menu_id, create_date, create_user, menu_descr, menu_icon, menu_label, menu_name, menu_type, parent_id, seq, state, update_date, update_user, url) VALUES ('242998048332972498', '2026-03-06 17:24:25.086527', 'chengkai', NULL, NULL, '家庭作业', 'homework', 'MENU', '230918229474674260', 1, 'ENABLED', NULL, NULL, 'homework');
INSERT INTO public.menu (menu_id, create_date, create_user, menu_descr, menu_icon, menu_label, menu_name, menu_type, parent_id, seq, state, update_date, update_user, url) VALUES ('251393455266203758', '2026-03-12 10:38:17.612288', 'chengkai', NULL, NULL, '生字本', 'character', 'MENU', '26219916348620800', 1, 'ENABLED', NULL, NULL, 'character');
INSERT INTO public.menu (menu_id, create_date, create_user, menu_descr, menu_icon, menu_label, menu_name, menu_type, parent_id, seq, state, update_date, update_user, url) VALUES ('271759640428027720', '2026-03-26 09:18:56.160639', 'chengkai', NULL, 'IconImage', '题库统计', 'question-bank', 'MENU', '230918229474674353', 1, 'ENABLED', NULL, NULL, 'question-bank');
INSERT INTO public.menu (menu_id, create_date, create_user, menu_descr, menu_icon, menu_label, menu_name, menu_type, parent_id, seq, state, update_date, update_user, url) VALUES ('273737129270444755', '2026-03-27 10:19:21.074543', 'chengkai', NULL, 'IconSearch', '热搜', 'hot-search', 'MENU', '231081781829304476', 11, 'ENABLED', NULL, NULL, 'hot-search');
INSERT INTO public.menu (menu_id, create_date, create_user, menu_descr, menu_icon, menu_label, menu_name, menu_type, parent_id, seq, state, update_date, update_user, url) VALUES ('75127602301370369', '2025-11-13 15:12:00.121176', 'admin', NULL, 'IconSave', '数据源管理', 'datasource_mgr', 'MENU', '76320933194760192', 1111, 'ENABLED', '2025-11-14 10:06:31.161425', 'admin', 'datasource');
INSERT INTO public.menu (menu_id, create_date, create_user, menu_descr, menu_icon, menu_label, menu_name, menu_type, parent_id, seq, state, update_date, update_user, url) VALUES ('192168089637359149', '2026-01-31 16:05:36.933194', 'chengkai', NULL, 'IconLink', '编排管理', 'orchestration', 'MENU', '76320933194760192', 1, 'ENABLED', NULL, NULL, 'orchestration');
INSERT INTO public.menu (menu_id, create_date, create_user, menu_descr, menu_icon, menu_label, menu_name, menu_type, parent_id, seq, state, update_date, update_user, url) VALUES ('183524124356772084', '2026-01-25 15:35:07.437284', 'admin', NULL, 'IconApps', '系统日志', 'syslog', 'MENU', '192168089637359328', 1, 'ENABLED', '2026-01-31 16:14:17.471439', 'chengkai', 'syslog');
INSERT INTO public.menu (menu_id, create_date, create_user, menu_descr, menu_icon, menu_label, menu_name, menu_type, parent_id, seq, state, update_date, update_user, url) VALUES ('74848154549223424', '2025-11-13 10:28:36.831638', 'admin', NULL, 'IconShareAlt', '队列管理', 'queue_mgr', 'MENU', '192168089637359389', 5, 'ENABLED', '2026-01-31 16:34:46.203097', 'admin', 'jobqueue');
INSERT INTO public.menu (menu_id, create_date, create_user, menu_descr, menu_icon, menu_label, menu_name, menu_type, parent_id, seq, state, update_date, update_user, url) VALUES ('74869474766880770', '2025-11-13 11:50:26.348322', 'admin', NULL, 'IconPlayArrow', '脚本管理', 'script_mgr', 'MENU', '192168089637359389', 10, 'ENABLED', '2026-01-31 16:41:21.041328', 'admin', 'script');
INSERT INTO public.menu (menu_id, create_date, create_user, menu_descr, menu_icon, menu_label, menu_name, menu_type, parent_id, seq, state, update_date, update_user, url) VALUES ('204073687442261970', '2026-02-08 14:08:27.000012', 'chengkai', NULL, 'IconQuestionCircle', '数据查询', 'data-query', 'MENU', '76320933194760192', 1, 'ENABLED', NULL, NULL, 'data-query');
INSERT INTO public.menu (menu_id, create_date, create_user, menu_descr, menu_icon, menu_label, menu_name, menu_type, parent_id, seq, state, update_date, update_user, url) VALUES ('201550926731804808', '2026-02-06 18:59:23.144593', 'chengkai', NULL, 'IconInteraction', 'API测试', 'api-tester', 'MENU', '231016189088760729', 1, 'ENABLED', '2026-02-26 16:14:52.100482', 'chengkai', 'api-tester');
INSERT INTO public.menu (menu_id, create_date, create_user, menu_descr, menu_icon, menu_label, menu_name, menu_type, parent_id, seq, state, update_date, update_user, url) VALUES ('192168089637359745', '2026-01-31 16:32:46.666995', 'admin', NULL, 'IconRobot', 'MCP管理', 'mcp_server', 'MENU', '231081781829304476', 3, 'ENABLED', '2026-02-26 16:25:59.7117', 'chengkai', 'mcp-server');
INSERT INTO public.menu (menu_id, create_date, create_user, menu_descr, menu_icon, menu_label, menu_name, menu_type, parent_id, seq, state, update_date, update_user, url) VALUES ('55546519981391872', '2025-10-31 10:22:36.058816', 'admin', NULL, NULL, '提示词管理', 'prompts', 'MENU', '231081781829304476', 9, 'ENABLED', '2026-02-26 16:26:14.053438', 'chengkai', 'prompt');
INSERT INTO public.menu (menu_id, create_date, create_user, menu_descr, menu_icon, menu_label, menu_name, menu_type, parent_id, seq, state, update_date, update_user, url) VALUES ('177378541552273669', '2026-01-21 15:12:14.268523', 'admin', NULL, 'IconFolder', '知识集管理', 'knowledge-set', 'MENU', '231081781829304476', 8, 'ENABLED', '2026-02-26 16:28:34.395919', 'chengkai', 'knowledge-set');
INSERT INTO public.menu (menu_id, create_date, create_user, menu_descr, menu_icon, menu_label, menu_name, menu_type, parent_id, seq, state, update_date, update_user, url) VALUES ('230918229474674260', '2026-02-26 15:49:31.64858', 'chengkai', NULL, 'IconPushpin', '工作规划', 'job_mgr', 'DIRECTORY', NULL, 10, 'ENABLED', '2026-02-26 16:35:42.920446', 'chengkai', NULL);
INSERT INTO public.menu (menu_id, create_date, create_user, menu_descr, menu_icon, menu_label, menu_name, menu_type, parent_id, seq, state, update_date, update_user, url) VALUES ('231016189088760729', '2026-02-26 16:14:24.219579', 'chengkai', NULL, NULL, '系统测试', 'sys_test', 'DIRECTORY', NULL, 70, 'ENABLED', '2026-02-26 16:37:46.283743', 'chengkai', NULL);
INSERT INTO public.menu (menu_id, create_date, create_user, menu_descr, menu_icon, menu_label, menu_name, menu_type, parent_id, seq, state, update_date, update_user, url) VALUES ('192168089637359389', '2026-01-31 16:15:22.139961', 'chengkai', NULL, 'IconSettings', '系统配置', 'sys_config', 'DIRECTORY', NULL, 100, 'ENABLED', '2026-02-26 16:39:27.778358', 'chengkai', NULL);
INSERT INTO public.menu (menu_id, create_date, create_user, menu_descr, menu_icon, menu_label, menu_name, menu_type, parent_id, seq, state, update_date, update_user, url) VALUES ('251744800770885062', '2026-03-12 15:42:33.78257', 'chengkai', NULL, NULL, '上帝视角', 'diary', 'MENU', '76320933194760192', 1, 'ENABLED', NULL, NULL, 'diary');
INSERT INTO public.menu (menu_id, create_date, create_user, menu_descr, menu_icon, menu_label, menu_name, menu_type, parent_id, seq, state, update_date, update_user, url) VALUES ('271759640428027732', '2026-03-26 09:19:21.159872', 'chengkai', NULL, NULL, '单词统计', 'vocabulary-proficiency', 'MENU', '230918229474674353', 2, 'ENABLED', NULL, NULL, 'vocabulary-proficiency');
INSERT INTO public.menu (menu_id, create_date, create_user, menu_descr, menu_icon, menu_label, menu_name, menu_type, parent_id, seq, state, update_date, update_user, url) VALUES ('273737129270444155', '2026-03-27 10:02:53.876381', 'chengkai', NULL, NULL, '知识统计', 'knowledge-mastery', 'MENU', '230918229474674353', 3, 'ENABLED', NULL, NULL, 'knowledge-mastery');
INSERT INTO public.menu (menu_id, create_date, create_user, menu_descr, menu_icon, menu_label, menu_name, menu_type, parent_id, seq, state, update_date, update_user, url) VALUES ('286379760643211503', '2026-04-04 22:31:32.026957', 'chengkai', NULL, 'IconEar', '价格监控', 'price-monitor', 'MENU', '76320933194760192', 1, 'ENABLED', NULL, NULL, 'price-monitor');
INSERT INTO public.menu (menu_id, create_date, create_user, menu_descr, menu_icon, menu_label, menu_name, menu_type, parent_id, seq, state, update_date, update_user, url) VALUES ('baidu_pan', '2026-04-05 11:00:13.944224', NULL, '百度网盘接入壳页面', 'storage', '百度网盘', 'baidu_pan', 'MENU', NULL, 31, 'ENABLED', '2026-04-05 11:00:13.94232', NULL, 'baidu-pan');
INSERT INTO public.menu (menu_id, create_date, create_user, menu_descr, menu_icon, menu_label, menu_name, menu_type, parent_id, seq, state, update_date, update_user, url) VALUES ('294962874827145649', '2026-04-10 17:34:21.483515', 'chengkai', NULL, 'IconClockCircle', '生命倒计时', 'life-countdown', 'MENU', NULL, 0, 'ENABLED', NULL, NULL, 'life-countdown');


--
-- Data for Name: user_role; Type: TABLE DATA; Schema: public; Owner: -
--

INSERT INTO public.user_role (id, create_date, create_user, update_date, update_user, descr, name, state) VALUES ('guest', '2025-12-13 20:41:54.44313', 'admin', NULL, NULL, '游客', '游客', 'ENABLED');
INSERT INTO public.user_role (id, create_date, create_user, update_date, update_user, descr, name, state) VALUES ('user', '2025-10-07 13:10:32.13403', 'admin', NULL, NULL, '普通用户', '普通用户', 'ENABLED');
INSERT INTO public.user_role (id, create_date, create_user, update_date, update_user, descr, name, state) VALUES ('sys_mgr', '2026-01-15 09:53:23.219713', 'admin', '2026-01-15 09:53:23.219713', 'admin', '系统管理员', '系统管理员', 'ENABLED');
INSERT INTO public.user_role (id, create_date, create_user, update_date, update_user, descr, name, state) VALUES ('242072637499512767', '2026-03-06 14:41:52.934739', 'chengkai', '2026-03-06 14:41:52.934739', 'chengkai', NULL, '安雾', 'ENABLED');
INSERT INTO public.user_role (id, create_date, create_user, update_date, update_user, descr, name, state) VALUES ('242072637499512780', '2026-03-06 14:42:00.658826', 'chengkai', '2026-03-06 14:42:00.658826', 'chengkai', NULL, '程煜涵', 'ENABLED');
INSERT INTO public.user_role (id, create_date, create_user, update_date, update_user, descr, name, state) VALUES ('249494272267520323', '2026-03-11 11:43:28.686114', 'chengkai', '2026-04-04 14:13:29.253765', 'chengkai', NULL, 'openclaw', 'ENABLED');


--
-- Data for Name: role_menu_rela; Type: TABLE DATA; Schema: public; Owner: -
--

INSERT INTO public.role_menu_rela (rela_id, menu_id, role_id) VALUES ('263431458322908465', '249494272267520435', '249494272267520323');
INSERT INTO public.role_menu_rela (rela_id, menu_id, role_id) VALUES ('242072637499512951', '230918229474674260', '242072637499512767');
INSERT INTO public.role_menu_rela (rela_id, menu_id, role_id) VALUES ('242072637499512952', '118741569263112860', '242072637499512767');
INSERT INTO public.role_menu_rela (rela_id, menu_id, role_id) VALUES ('242072637499512953', '32015218800328704', '242072637499512767');
INSERT INTO public.role_menu_rela (rela_id, menu_id, role_id) VALUES ('242072637499512954', '50050233152831502', '242072637499512767');
INSERT INTO public.role_menu_rela (rela_id, menu_id, role_id) VALUES ('242072637499512955', '144982908908601370', '242072637499512767');
INSERT INTO public.role_menu_rela (rela_id, menu_id, role_id) VALUES ('242072637499512956', '26266405074632715', '242072637499512767');
INSERT INTO public.role_menu_rela (rela_id, menu_id, role_id) VALUES ('242072637499512957', '192168089637360097', '242072637499512767');
INSERT INTO public.role_menu_rela (rela_id, menu_id, role_id) VALUES ('242072637499512958', '26266405074632728', '242072637499512767');
INSERT INTO public.role_menu_rela (rela_id, menu_id, role_id) VALUES ('242072637499512959', '26266405074632743', '242072637499512767');
INSERT INTO public.role_menu_rela (rela_id, menu_id, role_id) VALUES ('242072637499512960', '42365316889575424', '242072637499512767');
INSERT INTO public.role_menu_rela (rela_id, menu_id, role_id) VALUES ('242072637499512961', '115181144453940054', '242072637499512767');
INSERT INTO public.role_menu_rela (rela_id, menu_id, role_id) VALUES ('242072637499512962', '176068731145814769', '242072637499512767');
INSERT INTO public.role_menu_rela (rela_id, menu_id, role_id) VALUES ('242072637499512963', '179018961361305638', '242072637499512767');
INSERT INTO public.role_menu_rela (rela_id, menu_id, role_id) VALUES ('242072637499512964', '187981596035383344', '242072637499512767');
INSERT INTO public.role_menu_rela (rela_id, menu_id, role_id) VALUES ('242072637499512965', '78189209608781860', '242072637499512767');
INSERT INTO public.role_menu_rela (rela_id, menu_id, role_id) VALUES ('263431458322908466', '215028070250185143', '249494272267520323');
INSERT INTO public.role_menu_rela (rela_id, menu_id, role_id) VALUES ('263431458322908467', '177378541552273669', '249494272267520323');
INSERT INTO public.role_menu_rela (rela_id, menu_id, role_id) VALUES ('192168089637359203', '144982908908601370', 'user');
INSERT INTO public.role_menu_rela (rela_id, menu_id, role_id) VALUES ('192168089637359204', '118741569263112860', 'user');
INSERT INTO public.role_menu_rela (rela_id, menu_id, role_id) VALUES ('192168089637359205', '32015218800328704', 'user');
INSERT INTO public.role_menu_rela (rela_id, menu_id, role_id) VALUES ('192168089637359206', '50050233152831502', 'user');
INSERT INTO public.role_menu_rela (rela_id, menu_id, role_id) VALUES ('192168089637359207', '26266405074632728', 'user');
INSERT INTO public.role_menu_rela (rela_id, menu_id, role_id) VALUES ('192168089637359208', '26266405074632743', 'user');
INSERT INTO public.role_menu_rela (rela_id, menu_id, role_id) VALUES ('192168089637359209', '42365316889575424', 'user');
INSERT INTO public.role_menu_rela (rela_id, menu_id, role_id) VALUES ('192168089637359210', '26219916348620800', 'user');
INSERT INTO public.role_menu_rela (rela_id, menu_id, role_id) VALUES ('192168089637359213', '26266405074632715', 'user');
INSERT INTO public.role_menu_rela (rela_id, menu_id, role_id) VALUES ('192168089637359214', '134691737770655774', 'user');
INSERT INTO public.role_menu_rela (rela_id, menu_id, role_id) VALUES ('192168089637359215', 'user_mgr', 'user');
INSERT INTO public.role_menu_rela (rela_id, menu_id, role_id) VALUES ('192168089637359216', '136067432975434904', 'user');
INSERT INTO public.role_menu_rela (rela_id, menu_id, role_id) VALUES ('192168089637359217', 'role_mgr', 'user');
INSERT INTO public.role_menu_rela (rela_id, menu_id, role_id) VALUES ('192168089637359218', 'menu_mgr', 'user');
INSERT INTO public.role_menu_rela (rela_id, menu_id, role_id) VALUES ('192168089637359219', '115181144453940054', 'user');
INSERT INTO public.role_menu_rela (rela_id, menu_id, role_id) VALUES ('192168089637359220', '116674882539880455', 'user');
INSERT INTO public.role_menu_rela (rela_id, menu_id, role_id) VALUES ('192168089637359221', '187981596035383344', 'user');
INSERT INTO public.role_menu_rela (rela_id, menu_id, role_id) VALUES ('192168089637359222', '133133918772658432', 'user');
INSERT INTO public.role_menu_rela (rela_id, menu_id, role_id) VALUES ('192168089637359223', '179018961361305638', 'user');
INSERT INTO public.role_menu_rela (rela_id, menu_id, role_id) VALUES ('192168089637359224', '176068731145814769', 'user');
INSERT INTO public.role_menu_rela (rela_id, menu_id, role_id) VALUES ('192168089637359225', '95606916901765188', 'user');
INSERT INTO public.role_menu_rela (rela_id, menu_id, role_id) VALUES ('192168089637359226', '75127602301370369', 'user');
INSERT INTO public.role_menu_rela (rela_id, menu_id, role_id) VALUES ('192168089637359227', '177378541552273669', 'user');
INSERT INTO public.role_menu_rela (rela_id, menu_id, role_id) VALUES ('192168089637359228', '40875083496948222', 'user');
INSERT INTO public.role_menu_rela (rela_id, menu_id, role_id) VALUES ('192168089637359229', '55546519981391872', 'user');
INSERT INTO public.role_menu_rela (rela_id, menu_id, role_id) VALUES ('192168089637359230', '192168089637359149', 'user');
INSERT INTO public.role_menu_rela (rela_id, menu_id, role_id) VALUES ('192168089637359231', '76320933194760192', 'user');
INSERT INTO public.role_menu_rela (rela_id, menu_id, role_id) VALUES ('294962874827145683', '230918229474674260', 'sys_mgr');
INSERT INTO public.role_menu_rela (rela_id, menu_id, role_id) VALUES ('294962874827145684', '242998048332972498', 'sys_mgr');
INSERT INTO public.role_menu_rela (rela_id, menu_id, role_id) VALUES ('294962874827145685', '118741569263112860', 'sys_mgr');
INSERT INTO public.role_menu_rela (rela_id, menu_id, role_id) VALUES ('294962874827145686', '32015218800328704', 'sys_mgr');
INSERT INTO public.role_menu_rela (rela_id, menu_id, role_id) VALUES ('294962874827145687', '26219916348620800', 'sys_mgr');
INSERT INTO public.role_menu_rela (rela_id, menu_id, role_id) VALUES ('294962874827145688', '50050233152831502', 'sys_mgr');
INSERT INTO public.role_menu_rela (rela_id, menu_id, role_id) VALUES ('294962874827145689', '251393455266203758', 'sys_mgr');
INSERT INTO public.role_menu_rela (rela_id, menu_id, role_id) VALUES ('294962874827145690', '227758868711604253', 'sys_mgr');
INSERT INTO public.role_menu_rela (rela_id, menu_id, role_id) VALUES ('294962874827145691', '235407982127480885', 'sys_mgr');
INSERT INTO public.role_menu_rela (rela_id, menu_id, role_id) VALUES ('294962874827145692', '144982908908601370', 'sys_mgr');
INSERT INTO public.role_menu_rela (rela_id, menu_id, role_id) VALUES ('294962874827145693', '26266405074632715', 'sys_mgr');
INSERT INTO public.role_menu_rela (rela_id, menu_id, role_id) VALUES ('294962874827145694', '192168089637360097', 'sys_mgr');
INSERT INTO public.role_menu_rela (rela_id, menu_id, role_id) VALUES ('294962874827145695', '26266405074632728', 'sys_mgr');
INSERT INTO public.role_menu_rela (rela_id, menu_id, role_id) VALUES ('294962874827145696', '26266405074632743', 'sys_mgr');
INSERT INTO public.role_menu_rela (rela_id, menu_id, role_id) VALUES ('294962874827145697', '42365316889575424', 'sys_mgr');
INSERT INTO public.role_menu_rela (rela_id, menu_id, role_id) VALUES ('294962874827145698', 'baidu_pan', 'sys_mgr');
INSERT INTO public.role_menu_rela (rela_id, menu_id, role_id) VALUES ('294962874827145699', '231081781829304476', 'sys_mgr');
INSERT INTO public.role_menu_rela (rela_id, menu_id, role_id) VALUES ('294962874827145700', '176068731145814769', 'sys_mgr');
INSERT INTO public.role_menu_rela (rela_id, menu_id, role_id) VALUES ('294962874827145701', '215028070250185143', 'sys_mgr');
INSERT INTO public.role_menu_rela (rela_id, menu_id, role_id) VALUES ('294962874827145702', '115181144453940054', 'sys_mgr');
INSERT INTO public.role_menu_rela (rela_id, menu_id, role_id) VALUES ('271759640428027844', '230918229474674260', '242072637499512780');
INSERT INTO public.role_menu_rela (rela_id, menu_id, role_id) VALUES ('271759640428027845', '242998048332972498', '242072637499512780');
INSERT INTO public.role_menu_rela (rela_id, menu_id, role_id) VALUES ('271759640428027846', '118741569263112860', '242072637499512780');
INSERT INTO public.role_menu_rela (rela_id, menu_id, role_id) VALUES ('271759640428027847', '32015218800328704', '242072637499512780');
INSERT INTO public.role_menu_rela (rela_id, menu_id, role_id) VALUES ('271759640428027848', '50050233152831502', '242072637499512780');
INSERT INTO public.role_menu_rela (rela_id, menu_id, role_id) VALUES ('271759640428027849', '251393455266203758', '242072637499512780');
INSERT INTO public.role_menu_rela (rela_id, menu_id, role_id) VALUES ('271759640428027850', '235407982127480885', '242072637499512780');
INSERT INTO public.role_menu_rela (rela_id, menu_id, role_id) VALUES ('271759640428027851', '227758868711604253', '242072637499512780');
INSERT INTO public.role_menu_rela (rela_id, menu_id, role_id) VALUES ('271759640428027852', '26266405074632715', '242072637499512780');
INSERT INTO public.role_menu_rela (rela_id, menu_id, role_id) VALUES ('271759640428027853', '192168089637360097', '242072637499512780');
INSERT INTO public.role_menu_rela (rela_id, menu_id, role_id) VALUES ('271759640428027854', '26266405074632728', '242072637499512780');
INSERT INTO public.role_menu_rela (rela_id, menu_id, role_id) VALUES ('271759640428027855', '26266405074632743', '242072637499512780');
INSERT INTO public.role_menu_rela (rela_id, menu_id, role_id) VALUES ('271759640428027856', '42365316889575424', '242072637499512780');
INSERT INTO public.role_menu_rela (rela_id, menu_id, role_id) VALUES ('271759640428027857', '271759640428027732', '242072637499512780');
INSERT INTO public.role_menu_rela (rela_id, menu_id, role_id) VALUES ('294962874827145703', '221032245551432906', 'sys_mgr');
INSERT INTO public.role_menu_rela (rela_id, menu_id, role_id) VALUES ('294962874827145704', '249494272267520435', 'sys_mgr');
INSERT INTO public.role_menu_rela (rela_id, menu_id, role_id) VALUES ('294962874827145705', '192168089637359745', 'sys_mgr');
INSERT INTO public.role_menu_rela (rela_id, menu_id, role_id) VALUES ('294962874827145706', '177378541552273669', 'sys_mgr');
INSERT INTO public.role_menu_rela (rela_id, menu_id, role_id) VALUES ('294962874827145707', '55546519981391872', 'sys_mgr');
INSERT INTO public.role_menu_rela (rela_id, menu_id, role_id) VALUES ('294962874827145708', '40875083496948222', 'sys_mgr');
INSERT INTO public.role_menu_rela (rela_id, menu_id, role_id) VALUES ('294962874827145709', '273737129270444755', 'sys_mgr');
INSERT INTO public.role_menu_rela (rela_id, menu_id, role_id) VALUES ('294962874827145710', '76320933194760192', 'sys_mgr');
INSERT INTO public.role_menu_rela (rela_id, menu_id, role_id) VALUES ('294962874827145711', '116674882539880455', 'sys_mgr');
INSERT INTO public.role_menu_rela (rela_id, menu_id, role_id) VALUES ('294962874827145712', '187981596035383344', 'sys_mgr');
INSERT INTO public.role_menu_rela (rela_id, menu_id, role_id) VALUES ('294962874827145713', '286379760643211503', 'sys_mgr');
INSERT INTO public.role_menu_rela (rela_id, menu_id, role_id) VALUES ('294962874827145714', '179018961361305638', 'sys_mgr');
INSERT INTO public.role_menu_rela (rela_id, menu_id, role_id) VALUES ('294962874827145715', '204073687442261970', 'sys_mgr');
INSERT INTO public.role_menu_rela (rela_id, menu_id, role_id) VALUES ('294962874827145716', '192168089637359149', 'sys_mgr');
INSERT INTO public.role_menu_rela (rela_id, menu_id, role_id) VALUES ('294962874827145717', '251744800770885062', 'sys_mgr');
INSERT INTO public.role_menu_rela (rela_id, menu_id, role_id) VALUES ('294962874827145718', '95606916901765188', 'sys_mgr');
INSERT INTO public.role_menu_rela (rela_id, menu_id, role_id) VALUES ('294962874827145719', '75127602301370369', 'sys_mgr');
INSERT INTO public.role_menu_rela (rela_id, menu_id, role_id) VALUES ('294962874827145720', '230918229474674353', 'sys_mgr');
INSERT INTO public.role_menu_rela (rela_id, menu_id, role_id) VALUES ('294962874827145721', '271759640428027720', 'sys_mgr');
INSERT INTO public.role_menu_rela (rela_id, menu_id, role_id) VALUES ('294962874827145722', '271759640428027732', 'sys_mgr');
INSERT INTO public.role_menu_rela (rela_id, menu_id, role_id) VALUES ('294962874827145723', '273737129270444155', 'sys_mgr');
INSERT INTO public.role_menu_rela (rela_id, menu_id, role_id) VALUES ('294962874827145724', '231016189088760729', 'sys_mgr');
INSERT INTO public.role_menu_rela (rela_id, menu_id, role_id) VALUES ('294962874827145725', '133133918772658432', 'sys_mgr');
INSERT INTO public.role_menu_rela (rela_id, menu_id, role_id) VALUES ('294962874827145726', '201550926731804808', 'sys_mgr');
INSERT INTO public.role_menu_rela (rela_id, menu_id, role_id) VALUES ('294962874827145727', '200511080789709743', 'sys_mgr');
INSERT INTO public.role_menu_rela (rela_id, menu_id, role_id) VALUES ('294962874827145728', '192168089637359328', 'sys_mgr');
INSERT INTO public.role_menu_rela (rela_id, menu_id, role_id) VALUES ('294962874827145729', '241356649271395924', 'sys_mgr');
INSERT INTO public.role_menu_rela (rela_id, menu_id, role_id) VALUES ('294962874827145730', '204073687442262076', 'sys_mgr');
INSERT INTO public.role_menu_rela (rela_id, menu_id, role_id) VALUES ('294962874827145731', '183524124356772084', 'sys_mgr');
INSERT INTO public.role_menu_rela (rela_id, menu_id, role_id) VALUES ('294962874827145732', '136067432975434904', 'sys_mgr');
INSERT INTO public.role_menu_rela (rela_id, menu_id, role_id) VALUES ('294962874827145733', '76398070807396352', 'sys_mgr');
INSERT INTO public.role_menu_rela (rela_id, menu_id, role_id) VALUES ('294962874827145734', '192168089637359577', 'sys_mgr');
INSERT INTO public.role_menu_rela (rela_id, menu_id, role_id) VALUES ('294962874827145735', 'user_mgr', 'sys_mgr');
INSERT INTO public.role_menu_rela (rela_id, menu_id, role_id) VALUES ('294962874827145736', 'role_mgr', 'sys_mgr');
INSERT INTO public.role_menu_rela (rela_id, menu_id, role_id) VALUES ('294962874827145737', 'menu_mgr', 'sys_mgr');
INSERT INTO public.role_menu_rela (rela_id, menu_id, role_id) VALUES ('294962874827145738', '192168089637359389', 'sys_mgr');
INSERT INTO public.role_menu_rela (rela_id, menu_id, role_id) VALUES ('294962874827145739', '204073687442261831', 'sys_mgr');
INSERT INTO public.role_menu_rela (rela_id, menu_id, role_id) VALUES ('294962874827145740', '134691737770655774', 'sys_mgr');
INSERT INTO public.role_menu_rela (rela_id, menu_id, role_id) VALUES ('294962874827145741', '183524124356771948', 'sys_mgr');
INSERT INTO public.role_menu_rela (rela_id, menu_id, role_id) VALUES ('294962874827145742', '97505309626466326', 'sys_mgr');
INSERT INTO public.role_menu_rela (rela_id, menu_id, role_id) VALUES ('294962874827145743', '74848154549223424', 'sys_mgr');
INSERT INTO public.role_menu_rela (rela_id, menu_id, role_id) VALUES ('294962874827145744', '78189209608781860', 'sys_mgr');
INSERT INTO public.role_menu_rela (rela_id, menu_id, role_id) VALUES ('294962874827145745', '74869474766880770', 'sys_mgr');
INSERT INTO public.role_menu_rela (rela_id, menu_id, role_id) VALUES ('294962874827145746', '294962874827145649', 'sys_mgr');


--
-- Data for Name: users; Type: TABLE DATA; Schema: public; Owner: -
--

INSERT INTO public.users (user_id, create_date, create_user, email, logo, password, phone, state, update_date, update_user, user_name) VALUES ('admin', '2026-01-15 10:03:53.321268', 'admin', 'admin@asiainfo.com', NULL, '$2a$10$Vwc5UwkW2r3BkmtlciHsPeSDAdSktAdd3bfdvUwL/mfn5xjqSjHf.', '12345678901', 'ENABLED', '2026-02-28 16:20:11.418919', 'chengkai', '系统管理员');
INSERT INTO public.users (user_id, create_date, create_user, email, logo, password, phone, state, update_date, update_user, user_name) VALUES ('chengyuhan', '2025-11-05 10:51:23.148236', 'admin', NULL, NULL, '$2a$10$yWdT5zx8r8l.nb/uxOZez.1oAJv8srKQhjeWUUTUPLcYiPBlJl7cy', NULL, 'ENABLED', '2026-03-06 14:22:26.040467', 'chengkai', '程煜涵');
INSERT INTO public.users (user_id, create_date, create_user, email, logo, password, phone, state, update_date, update_user, user_name) VALUES ('anwu', '2025-10-20 12:43:28.086475', 'admin', NULL, NULL, '$2a$10$gTfdItlBNmqOYfaNZYueuuLwVB8i.fMZOsZJDBcBdMVPORlgmCEl2', NULL, 'ENABLED', '2026-03-06 14:44:49.022919', 'chengkai', '安雾');
INSERT INTO public.users (user_id, create_date, create_user, email, logo, password, phone, state, update_date, update_user, user_name) VALUES ('openclaw', '2026-03-09 07:46:20.557368', 'chengkai', 'xiaolongxia@163.com', NULL, '$2a$10$BVGrSOVwAeEJoVV1VaY1BOXAsEBVmpthWni1yhqqUvU3X7QueDVJ2', NULL, 'ENABLED', '2026-03-25 10:17:42.770646', 'chengkai', '小龙虾');
INSERT INTO public.users (user_id, create_date, create_user, email, logo, password, phone, state, update_date, update_user, user_name) VALUES ('chengkai', '2025-10-11 17:25:29.770575', 'admin', 'm18162847837@163.com', NULL, '$2a$10$Nx1uba8.Vi8cOqXcZGnX7ObDkT040j5qAWD5eP4DO7.YmMA8EoLX.', '18162847837', 'ENABLED', '2026-04-23 23:06:56.223182', 'admin', '程凯');


--
-- PostgreSQL database dump complete
--

\unrestrict UVXxtXaQlAJfZapskxZfZboeDWXESBEy163oCBkBzCL7LH2c7YFImJpPFUfTR6x

SET session_replication_role = origin;
