import type { MenuTreeItem } from "@/types/auth";

/**
 * Returns the path of the first navigable menu item in the menu tree,
 * in menu display order (depth-first). Directory items with a null `path`
 * are descended into; the first item whose `path` is non-null wins.
 * Returns null when no navigable path is found (empty/error menu data).
 */
export function findFirstMenuPath(items: MenuTreeItem[]): string | null {
  for (const item of items) {
    if (item.path) {
      return item.path;
    }
    if (item.children.length > 0) {
      const childPath = findFirstMenuPath(item.children);
      if (childPath) {
        return childPath;
      }
    }
  }
  return null;
}
