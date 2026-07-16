export interface DocumentChapter {
  id: number;
  name: string;
  description: string | null;
  parent_id: number | null;
  sort_order: number;
  created_at: string;
  updated_at: string;
}

export interface DocumentChapterTreeItem extends DocumentChapter {
  children: DocumentChapterTreeItem[];
  documents: Document[];
}

export interface DocumentChapterListResponse {
  items: DocumentChapter[];
  total: number;
}

export interface DocumentChapterCreateRequest {
  name: string;
  description?: string | null;
  parent_id?: number | null;
  sort_order?: number;
}

export interface DocumentChapterUpdateRequest {
  name?: string;
  description?: string | null;
  parent_id?: number | null;
  sort_order?: number;
}

export interface Document {
  id: number;
  title: string;
  content: string;
  chapter_id: number | null;
  sort_order: number;
  status: "draft" | "published";
  created_at: string;
  updated_at: string;
}

export interface DocumentListResponse {
  items: Document[];
  total: number;
}

export interface DocumentCreateRequest {
  title: string;
  content: string;
  chapter_id?: number | null;
  sort_order?: number;
  status?: "draft" | "published";
}

export interface DocumentUpdateRequest {
  title?: string;
  content?: string;
  chapter_id?: number | null;
  sort_order?: number;
  status?: "draft" | "published";
}
