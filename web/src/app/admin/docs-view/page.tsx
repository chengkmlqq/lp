"use client";

import { useQuery } from "@tanstack/react-query";
import {
  Card,
  Drawer,
  Empty,
  Input,
  Menu,
  Skeleton,
  Typography,
  Button,
  Image,
  Tooltip,
  type CardProps,
} from "antd";
import {
  FolderOutlined,
  FileTextOutlined,
  MenuOutlined,
  MenuFoldOutlined,
  MenuUnfoldOutlined,
  SearchOutlined,
  CopyOutlined,
  LinkOutlined,
} from "@ant-design/icons";
import {
  useCallback,
  useEffect,
  useState,
  useRef,
  useMemo,
  type ComponentType,
  type RefAttributes,
} from "react";
import type { MenuProps } from "antd";
import ReactMarkdown from "react-markdown";
import rehypeHighlight from "rehype-highlight";
import rehypeSlug from "rehype-slug";

import { useAuth } from "@/components/auth-provider";
import { useMobileDetection } from "@/hooks/use-mobile-detection";
import { readApiError } from "@/lib/api";
import type {
  Document,
  DocumentChapterTreeItem,
} from "@/types/document";

const { Title, Paragraph, Text } = Typography;
const AntCard = Card as unknown as ComponentType<CardProps & RefAttributes<HTMLDivElement>>;

type MenuItem = Required<MenuProps>["items"][number];

function flattenDocuments(chapters: DocumentChapterTreeItem[]): { id: number; title: string; chapterPath: string }[] {
  const result: { id: number; title: string; chapterPath: string }[] = [];
  const walk = (items: DocumentChapterTreeItem[], path: string) => {
    for (const chapter of items) {
      const currentPath = path ? `${path} / ${chapter.name}` : chapter.name;
      for (const doc of chapter.documents?.filter((d) => d.status === "published") ?? []) {
        result.push({ id: doc.id, title: doc.title, chapterPath: currentPath });
      }
      if (chapter.children) walk(chapter.children, currentPath);
    }
  };
  walk(chapters, "");
  return result;
}

export default function DocsViewPage() {
  const { user, fetchWithAuth, hasPermission } = useAuth();
  const isMobile = useMobileDetection();
  const [selectedDocumentId, setSelectedDocumentId] = useState<number | null>(null);
  const [siderCollapsed, setSiderCollapsed] = useState(false);
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [copiedCodeBlockId, setCopiedCodeBlockId] = useState<string | null>(null);
  const contentRef = useRef<HTMLDivElement>(null);

  // 后端 admin_files.py 的权限码是 file.read / file.manage（document.* 是无效码）
  const canRead = hasPermission("file.read") || hasPermission("file.manage");

  const { data: treeData, isLoading: treeLoading } = useQuery({
    queryKey: ["/api/v1/documents/chapters/tree"],
    queryFn: async () => {
      const response = await fetchWithAuth("/api/v1/documents/chapters/tree");
      if (!response.ok) throw new Error(await readApiError(response));
      return response.json() as Promise<DocumentChapterTreeItem[]>;
    },
    enabled: !!user && canRead,
  });

  const { data: selectedDocument, isLoading: documentLoading } = useQuery({
    queryKey: ["/api/v1/documents", selectedDocumentId],
    queryFn: async () => {
      if (!selectedDocumentId) return null;
      const response = await fetchWithAuth(`/api/v1/documents/${selectedDocumentId}`);
      if (!response.ok) throw new Error(await readApiError(response));
      return response.json() as Promise<Document>;
    },
    enabled: !!selectedDocumentId && !!user && canRead,
  });

  const documentIndex = useMemo(() => (treeData ? flattenDocuments(treeData) : []), [treeData]);

  const filteredMenuItems = useMemo(() => {
    if (!treeData) return [];

    const filterTree = (chapters: DocumentChapterTreeItem[]): MenuItem[] => {
      return chapters
        .filter((chapter) => {
          const hasPublishedDocs = chapter.documents?.some((doc) => doc.status === "published");
          const hasPublishedChildren = chapter.children?.some((child) =>
            child.documents?.some((doc) => doc.status === "published"),
          );
          return hasPublishedDocs || hasPublishedChildren;
        })
        .map((chapter) => {
          const publishedDocs = chapter.documents?.filter((doc) => doc.status === "published") || [];

          const matchedDocs = searchQuery
            ? publishedDocs.filter(
                (doc) =>
                  doc.title.toLowerCase().includes(searchQuery.toLowerCase()) ||
                  chapter.name.toLowerCase().includes(searchQuery.toLowerCase()),
              )
            : publishedDocs;

          const childItems = chapter.children ? filterTree(chapter.children) : [];

          if (searchQuery && matchedDocs.length === 0 && childItems.length === 0) {
            return null;
          }

          const docItems: MenuItem[] = matchedDocs.map((doc) => ({
            key: `doc-${doc.id}`,
            icon: <FileTextOutlined />,
            label: (
              <span className="admin-docs-view-menu-doc-title" data-searching={!!searchQuery}>
                {searchQuery ? highlightMatch(doc.title, searchQuery) : doc.title}
              </span>
            ),
          }));

          return {
            key: `chapter-${chapter.id}`,
            icon: <FolderOutlined />,
            label: (
              <span className="admin-docs-view-menu-chapter-name" data-searching={!!searchQuery}>
                {searchQuery ? highlightMatch(chapter.name, searchQuery) : chapter.name}
              </span>
            ),
            children: [...docItems, ...childItems],
          };
        })
        .filter(Boolean) as MenuItem[];
    };

    return filterTree(treeData);
  }, [treeData, searchQuery]);

  function highlightMatch(text: string, query: string): React.ReactNode {
    const lower = text.toLowerCase();
    const q = query.toLowerCase();
    const idx = lower.indexOf(q);
    if (idx === -1) return text;
    return (
      <>
        {text.slice(0, idx)}
        <mark className="admin-docs-view-search-highlight">{text.slice(idx, idx + q.length)}</mark>
        {text.slice(idx + q.length)}
      </>
    );
  }

  const handleMenuClick: MenuProps["onClick"] = useCallback(
    (e) => {
      if (e.key.startsWith("doc-")) {
        const docId = parseInt(e.key.replace("doc-", ""), 10);
        setSelectedDocumentId(docId);
        setMobileMenuOpen(false);
        contentRef.current?.scrollTo({ top: 0, behavior: "smooth" });
      }
    },
    [],
  );

  const selectFirstDocument = useCallback(() => {
    if (!treeData || treeData.length === 0 || selectedDocumentId) return;

    const findFirstPublishedDoc = (chapters: DocumentChapterTreeItem[]): Document | null => {
      for (const chapter of chapters) {
        const publishedDoc = chapter.documents?.find((doc) => doc.status === "published");
        if (publishedDoc) return publishedDoc;

        if (chapter.children) {
          const childDoc = findFirstPublishedDoc(chapter.children);
          if (childDoc) return childDoc;
        }
      }
      return null;
    };

    const firstDoc = findFirstPublishedDoc(treeData);
    if (firstDoc) {
      setSelectedDocumentId(firstDoc.id);
    }
  }, [treeData, selectedDocumentId]);

  useEffect(() => {
    selectFirstDocument();
  }, [selectFirstDocument]);

  const handleCopyCode = async (code: string, blockId: string) => {
    try {
      await navigator.clipboard.writeText(code);
      setCopiedCodeBlockId(blockId);
      setTimeout(() => setCopiedCodeBlockId(null), 2000);
    } catch {
      // silent
    }
  };

  if (!user || !canRead) {
    return (
      <div className="flex min-h-0 flex-1 flex-col">
        <AntCard className="admin-docs-view-page-card" title="操作文档">
          <div className="flex items-center justify-center" style={{ minHeight: 300 }}>
            <Empty description="暂无权限访问" />
          </div>
        </AntCard>
      </div>
    );
  }

  const skeletonMenu = (
    <div className="admin-docs-view-skeleton-menu">
      {[0, 1, 2, 3, 4, 5].map((i) => (
        <div
          key={i}
          className="admin-docs-view-skeleton-item"
          style={i % 3 === 0 ? {} : { paddingLeft: 20 }}
        >
          <Skeleton.Input active size="small" block style={{ width: `${50 + (i % 3) * 15}%` }} />
        </div>
      ))}
    </div>
  );

  const menuContent = (
    <>
      <div className="admin-docs-view-sider-header">
        {!siderCollapsed && (
          <>
            <Title level={4} style={{ margin: 0, fontSize: "16px", fontWeight: 600 }}>
              操作文档
            </Title>
            {!treeLoading && treeData && treeData.length > 0 && (
              <div className="admin-docs-view-search-wrapper">
                <Input
                  className="admin-docs-view-search-input"
                  placeholder="搜索文档..."
                  prefix={<SearchOutlined />}
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  allowClear
                  size="small"
                />
              </div>
            )}
          </>
        )}
      </div>
      {treeLoading ? (
        skeletonMenu
      ) : treeData && treeData.length > 0 ? (
        <>
          {searchQuery && (
            <div className="admin-docs-view-search-results-count">
              {`找到 ${documentIndex.filter((d) => d.title.toLowerCase().includes(searchQuery.toLowerCase())).length} 个结果`}
            </div>
          )}
          <div className="admin-docs-view-sider-menu">
            <Menu
              mode="inline"
              items={filteredMenuItems}
              onClick={handleMenuClick}
              selectedKeys={selectedDocumentId ? [`doc-${selectedDocumentId}`] : []}
              style={{ borderRight: 0, background: "transparent" }}
              inlineCollapsed={siderCollapsed && !isMobile}
            />
          </div>
        </>
      ) : (
        <div className="admin-docs-view-sider-empty">
          <Empty description="暂无文档" image={Empty.PRESENTED_IMAGE_SIMPLE} />
        </div>
      )}
      {!isMobile && (
        <div className="admin-docs-view-sider-footer">
          <Tooltip title={siderCollapsed ? "展开菜单" : "收起菜单"}>
            <Button
              aria-label={siderCollapsed ? "展开菜单" : "收起菜单"}
              icon={siderCollapsed ? <MenuUnfoldOutlined /> : <MenuFoldOutlined />}
              type="text"
              onClick={() => setSiderCollapsed((prev) => !prev)}
            />
          </Tooltip>
        </div>
      )}
    </>
  );

  const skeletonContent = (
    <div className="admin-docs-view-skeleton-content">
      <Skeleton active paragraph={{ rows: 1 }} title={{ width: "60%" }} />
      <div style={{ marginTop: 24 }}>
        <Skeleton active paragraph={{ rows: 3 }} />
      </div>
      <div style={{ marginTop: 24 }}>
        <Skeleton active paragraph={{ rows: 5 }} />
      </div>
      <div style={{ marginTop: 24 }}>
        <Skeleton active paragraph={{ rows: 4 }} />
      </div>
    </div>
  );

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <AntCard
        className="admin-docs-view-page-card"
        extra={
          isMobile ? (
            <Button icon={<MenuOutlined />} onClick={() => setMobileMenuOpen(true)}>
              目录
            </Button>
          ) : null
        }
      >
        <div className="admin-docs-view-layout">
          {!isMobile && (
            <div className={`admin-docs-view-sider${siderCollapsed ? " collapsed" : ""}`}>
              {menuContent}
            </div>
          )}

          <div className="admin-docs-view-content" ref={contentRef}>
            {documentLoading ? (
              skeletonContent
            ) : selectedDocument ? (
              <AntCard className="admin-docs-view-document-card" variant="borderless">
                <div className="admin-docs-view-document-header">
                  <Title level={2} style={{ marginBottom: 8 }}>
                    {selectedDocument.title}
                  </Title>
                </div>
                <div className="admin-docs-view-markdown-content">
                  <ReactMarkdown
                    rehypePlugins={[rehypeSlug, rehypeHighlight]}
                    components={{
                      h1: ({ children, id }) => (
                        <Title level={2} className="admin-docs-view-heading-anchor" id={id}>
                          <a href={`#${id}`} className="admin-docs-view-heading-link" aria-label="Heading anchor">
                            <LinkOutlined />
                          </a>
                          {children}
                        </Title>
                      ),
                      h2: ({ children, id }) => (
                        <Title level={3} className="admin-docs-view-heading-anchor" id={id}>
                          <a href={`#${id}`} className="admin-docs-view-heading-link" aria-label="Heading anchor">
                            <LinkOutlined />
                          </a>
                          {children}
                        </Title>
                      ),
                      h3: ({ children, id }) => (
                        <Title level={4} className="admin-docs-view-heading-anchor" id={id}>
                          <a href={`#${id}`} className="admin-docs-view-heading-link" aria-label="Heading anchor">
                            <LinkOutlined />
                          </a>
                          {children}
                        </Title>
                      ),
                      h4: ({ children, id }) => (
                        <Title level={5} className="admin-docs-view-heading-anchor" id={id}>
                          <a href={`#${id}`} className="admin-docs-view-heading-link" aria-label="Heading anchor">
                            <LinkOutlined />
                          </a>
                          {children}
                        </Title>
                      ),
                      p: ({ children }) => (
                        <Paragraph style={{ marginBottom: 16, lineHeight: 1.8 }}>{children}</Paragraph>
                      ),
                      ul: ({ children }) => (
                        <ul style={{ marginBottom: 16, paddingLeft: 24, lineHeight: 1.8 }}>{children}</ul>
                      ),
                      ol: ({ children }) => (
                        <ol style={{ marginBottom: 16, paddingLeft: 24, lineHeight: 1.8 }}>{children}</ol>
                      ),
                      li: ({ children }) => <li style={{ marginBottom: 8 }}>{children}</li>,
                      blockquote: ({ children }) => (
                        <blockquote className="admin-docs-view-blockquote">{children}</blockquote>
                      ),
                      code: ({ children, className }) => {
                        const isBlock = className?.includes("language-");
                        const codeText = String(children).replace(/\n$/, "");
                        const blockId = `code-${Math.random().toString(36).slice(2, 8)}`;
                        return isBlock ? (
                          <div className="admin-docs-view-code-block-wrapper">
                            <div className="admin-docs-view-code-block-header">
                              <span className="admin-docs-view-code-lang">
                                {className?.replace("language-", "") || "code"}
                              </span>
                              <Button
                                type="text"
                                size="small"
                                className="admin-docs-view-copy-btn"
                                icon={<CopyOutlined />}
                                onClick={() => handleCopyCode(codeText, blockId)}
                              >
                                {copiedCodeBlockId === blockId ? "已复制" : "复制"}
                              </Button>
                            </div>
                            <pre className="admin-docs-view-code-block">
                              <code className={className}>{children}</code>
                            </pre>
                          </div>
                        ) : (
                          <code className="admin-docs-view-inline-code">{children}</code>
                        );
                      },
                      table: ({ children }) => (
                        <div className="admin-docs-view-table-wrapper">
                          <table className="admin-docs-view-table">{children}</table>
                        </div>
                      ),
                      img: ({ src, alt }) => (
                        <div className="admin-docs-view-image-wrapper">
                          <Image
                            src={src as string}
                            alt={alt || ""}
                            className="admin-docs-view-content-image"
                            placeholder={
                              <div className="admin-docs-view-image-placeholder">
                                <Skeleton.Image active />
                              </div>
                            }
                            preview={{
                              mask: <div className="admin-docs-view-image-preview-mask">点击预览</div>,
                            }}
                          />
                          {alt && (
                            <Text type="secondary" className="admin-docs-view-image-caption">
                              {alt}
                            </Text>
                          )}
                        </div>
                      ),
                    }}
                  >
                    {selectedDocument.content}
                  </ReactMarkdown>
                </div>
              </AntCard>
            ) : (
              <div className="admin-docs-view-empty">
                <Empty
                  description="请从左侧目录选择要查看的文档"
                  image={Empty.PRESENTED_IMAGE_SIMPLE}
                />
              </div>
            )}
          </div>
        </div>
      </AntCard>

      <Drawer
        title="文档目录"
        placement="left"
        open={isMobile && mobileMenuOpen}
        width={300}
        onClose={() => setMobileMenuOpen(false)}
        styles={{ body: { padding: 0 } }}
      >
        <div className="admin-docs-view-mobile-drawer-content">
          {!treeLoading && treeData && treeData.length > 0 && (
            <div className="admin-docs-view-search-wrapper" style={{ padding: "12px 16px" }}>
              <Input
                placeholder="搜索文档..."
                prefix={<SearchOutlined />}
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                allowClear
              />
            </div>
          )}
          <Menu
            mode="inline"
            items={filteredMenuItems}
            onClick={handleMenuClick}
            selectedKeys={selectedDocumentId ? [`doc-${selectedDocumentId}`] : []}
            style={{ borderRight: 0 }}
          />
        </div>
      </Drawer>
    </div>
  );
}
