--
-- PostgreSQL database dump
--

\restrict 1UzMyLSKnGVDcWexiEnQBaw1f6zZstc2ds4ODbxoyOPa80nRUeE3vdjY4VHg75Q

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

SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: menu; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.menu (
    menu_id character varying(32) NOT NULL,
    create_date timestamp(6) without time zone,
    create_user character varying(64),
    menu_descr character varying(512),
    menu_icon character varying(128),
    menu_label character varying(128),
    menu_name character varying(128) NOT NULL,
    menu_type character varying(32) NOT NULL,
    parent_id character varying(32),
    seq integer,
    state character varying(16) NOT NULL,
    update_date timestamp(6) without time zone,
    update_user character varying(64),
    url character varying(256),
    CONSTRAINT menu_menu_type_check CHECK (((menu_type)::text = ANY ((ARRAY['MENU'::character varying, 'DIRECTORY'::character varying, 'BUTTON'::character varying])::text[]))),
    CONSTRAINT menu_state_check CHECK (((state)::text = ANY ((ARRAY['ENABLED'::character varying, 'DISABLED'::character varying])::text[])))
);


--
-- Name: role_menu_rela; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.role_menu_rela (
    rela_id character varying(32) NOT NULL,
    menu_id character varying(32) NOT NULL,
    role_id character varying(32) NOT NULL
);


--
-- Name: user_role; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.user_role (
    id character varying(32) NOT NULL,
    create_date timestamp(6) without time zone,
    create_user character varying(64),
    update_date timestamp(6) without time zone,
    update_user character varying(64),
    descr character varying(128),
    name character varying(64) NOT NULL,
    state character varying(255) NOT NULL,
    CONSTRAINT user_role_state_check CHECK (((state)::text = ANY ((ARRAY['ENABLED'::character varying, 'DISABLED'::character varying])::text[])))
);


--
-- Name: TABLE user_role; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.user_role IS '角色表';


--
-- Name: COLUMN user_role.id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.user_role.id IS '主题ID';


--
-- Name: COLUMN user_role.create_date; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.user_role.create_date IS '创建日期';


--
-- Name: COLUMN user_role.create_user; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.user_role.create_user IS '创建用户';


--
-- Name: COLUMN user_role.update_date; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.user_role.update_date IS '更新日期';


--
-- Name: COLUMN user_role.update_user; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.user_role.update_user IS '更新用户';


--
-- Name: COLUMN user_role.descr; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.user_role.descr IS '角色描述';


--
-- Name: COLUMN user_role.name; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.user_role.name IS '角色名称';


--
-- Name: COLUMN user_role.state; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.user_role.state IS '角色状态';


--
-- Name: users; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.users (
    user_id character varying(32) NOT NULL,
    create_date timestamp(6) without time zone,
    create_user character varying(64),
    email character varying(128),
    logo character varying(256),
    password character varying(256) NOT NULL,
    phone character varying(20),
    state character varying(10),
    update_date timestamp(6) without time zone,
    update_user character varying(64),
    user_name character varying(128) NOT NULL,
    CONSTRAINT users_state_check CHECK (((state)::text = ANY ((ARRAY['ENABLED'::character varying, 'DISABLED'::character varying])::text[])))
);


--
-- Name: menu menu_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.menu
    ADD CONSTRAINT menu_pkey PRIMARY KEY (menu_id);


--
-- Name: role_menu_rela role_menu_rela_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.role_menu_rela
    ADD CONSTRAINT role_menu_rela_pkey PRIMARY KEY (rela_id);


--
-- Name: role_menu_rela uk19n296uj1nw1eh5t1yp2fvjfb; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.role_menu_rela
    ADD CONSTRAINT uk19n296uj1nw1eh5t1yp2fvjfb UNIQUE (role_id, menu_id);


--
-- Name: user_role user_role_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_role
    ADD CONSTRAINT user_role_pkey PRIMARY KEY (id);


--
-- Name: users users_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_pkey PRIMARY KEY (user_id);


--
-- Name: idx_menu_name; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_menu_name ON public.menu USING btree (menu_name);


--
-- Name: idx_menu_parent_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_menu_parent_id ON public.menu USING btree (parent_id);


--
-- Name: idx_role_create_date; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_role_create_date ON public.user_role USING btree (create_date);


--
-- Name: idx_role_menu_rela_menu; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_role_menu_rela_menu ON public.role_menu_rela USING btree (menu_id);


--
-- Name: idx_role_menu_rela_role; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_role_menu_rela_role ON public.role_menu_rela USING btree (role_id);


--
-- Name: idx_role_name; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_role_name ON public.user_role USING btree (name);


--
-- Name: idx_role_state; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_role_state ON public.user_role USING btree (state);


--
-- Name: idx_user_email; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_user_email ON public.users USING btree (email);


--
-- Name: idx_user_phone; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_user_phone ON public.users USING btree (phone);


--
-- Name: idx_user_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_user_user_id ON public.users USING btree (user_id);


--
-- Name: role_menu_rela fk1ggyo9lya9u1l2r3qln7xgv92; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.role_menu_rela
    ADD CONSTRAINT fk1ggyo9lya9u1l2r3qln7xgv92 FOREIGN KEY (menu_id) REFERENCES public.menu(menu_id);


--
-- Name: role_menu_rela fk2yh7guxui8d64bm1l9am275yy; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.role_menu_rela
    ADD CONSTRAINT fk2yh7guxui8d64bm1l9am275yy FOREIGN KEY (role_id) REFERENCES public.user_role(id);


--
-- Name: menu fkgeupubdqncc1lpgf2cn4fqwbc; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.menu
    ADD CONSTRAINT fkgeupubdqncc1lpgf2cn4fqwbc FOREIGN KEY (parent_id) REFERENCES public.menu(menu_id);


--
-- PostgreSQL database dump complete
--

\unrestrict 1UzMyLSKnGVDcWexiEnQBaw1f6zZstc2ds4ODbxoyOPa80nRUeE3vdjY4VHg75Q

