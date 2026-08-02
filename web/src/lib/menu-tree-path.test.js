import assert from "node:assert/strict";
import test from "node:test";

import { findFirstMenuPath } from "./menu-tree-path.ts";

function menuItem(overrides = {}) {
  return {
    id: "id",
    code: "code",
    name: "name",
    path: null,
    icon: null,
    parent_id: null,
    type: "menu",
    sort_order: 0,
    status: "1",
    visible: true,
    cacheable: false,
    component: null,
    permission_code: null,
    children: [],
    ...overrides,
  };
}

test("findFirstMenuPath returns the first leaf path in display order", () => {
  const items = [
    menuItem({ id: "a", path: "/users" }),
    menuItem({ id: "b", path: "/roles" }),
  ];
  assert.equal(findFirstMenuPath(items), "/users");
});

test("findFirstMenuPath descends into directory items with a null path", () => {
  const items = [
    menuItem({
      id: "dir",
      children: [
        menuItem({ id: "child-a", path: null }),
        menuItem({ id: "child-b", path: "/ai-chat" }),
      ],
    }),
    menuItem({ id: "leaf", path: "/users" }),
  ];
  assert.equal(findFirstMenuPath(items), "/ai-chat");
});

test("findFirstMenuPath traverses nested directories depth-first", () => {
  const items = [
    menuItem({
      id: "dir-a",
      children: [
        menuItem({
          id: "dir-b",
          children: [menuItem({ id: "deep", path: "/tower-models" })],
        }),
      ],
    }),
  ];
  assert.equal(findFirstMenuPath(items), "/tower-models");
});

test("findFirstMenuPath returns null for an empty tree", () => {
  assert.equal(findFirstMenuPath([]), null);
});

test("findFirstMenuPath returns null when no item has a navigable path", () => {
  const items = [
    menuItem({
      id: "dir",
      children: [menuItem({ id: "child", children: [] })],
    }),
  ];
  assert.equal(findFirstMenuPath(items), null);
});
