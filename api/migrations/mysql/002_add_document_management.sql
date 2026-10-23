-- Migration: Add document management tables
-- Date: 2026-06-20
-- Description: Create tables for managing operational documents organized by chapters

-- Step 1: Create document_chapters table
CREATE TABLE IF NOT EXISTS document_chapters (
    id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(128) NOT NULL,
    description VARCHAR(512),
    parent_id INTEGER REFERENCES document_chapters(id) ON DELETE CASCADE,
    sort_order INTEGER DEFAULT 0 NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL
);

-- Create indexes for document_chapters
CREATE INDEX idx_document_chapters_name ON document_chapters(name);
CREATE INDEX idx_document_chapters_parent_id ON document_chapters(parent_id);
CREATE INDEX idx_document_chapters_sort_order ON document_chapters(sort_order);

-- Step 2: Create documents table
CREATE TABLE IF NOT EXISTS documents (
    id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    title VARCHAR(256) NOT NULL,
    content TEXT NOT NULL,
    chapter_id INTEGER REFERENCES document_chapters(id) ON DELETE CASCADE,
    sort_order INTEGER DEFAULT 0 NOT NULL,
    status VARCHAR(16) DEFAULT 'draft' NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL
);

-- Create indexes for documents
CREATE INDEX idx_documents_title ON documents(title);
CREATE INDEX idx_documents_chapter_id ON documents(chapter_id);
CREATE INDEX idx_documents_sort_order ON documents(sort_order);
CREATE INDEX idx_documents_status ON documents(status);

-- Step 3: Create trigger to update updated_at on document_chapters
-- [mysql] PG plpgsql 触发器 → MySQL 触发器
CREATE TRIGGER trigger_update_document_chapters_updated_at
    BEFORE UPDATE ON document_chapters
    FOR EACH ROW
    SET NEW.updated_at = CURRENT_TIMESTAMP;


-- Step 4: Create trigger to update updated_at on documents
CREATE TRIGGER trigger_update_documents_updated_at
    BEFORE UPDATE ON documents
    FOR EACH ROW
    SET NEW.updated_at = CURRENT_TIMESTAMP;

