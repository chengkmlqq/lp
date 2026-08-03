export type DimensionItem = {
  id: string;
  dimension_type: string;
  type_id: string | null;
  type_name: string | null;
  code: string;
  name: string;
  parent_id: string | null;
  description: string | null;
  is_enabled: boolean;
  sort_order: number;
  create_date: string;
  create_user: string | null;
  update_date: string;
  update_user: string | null;
};

export type DimensionItemTreeNode = DimensionItem & {
  children: DimensionItemTreeNode[];
};

export type DimensionItemListResponse = {
  items: DimensionItem[];
  total: number;
};
