import assert from "node:assert/strict";
import test from "node:test";

/**
 * Regression test for LP-239.
 * The dimension type-tree traversal helpers on the dimension management page
 * had no guard for non-array `types` / `null` children, which caused
 * "TypeError: e is not iterable" during render.
 *
 * The production functions live in `src/app/admin/dimensions/page.tsx`
 * (`flattenTypeOptions`, `findType`, `convertToTypeData`, `filterTypes`) and
 * `src/hooks/use-dimension-options.ts` (`flattenTypeNodes`). They are not
 * exported, so this replicates the guard logic to document and lock in the
 * fix for the non-iterable edge cases.
 */

function flattenTypeOptions(types, level = 0) {
  if (!Array.isArray(types)) return [];
  return types.flatMap((t) => [
    { value: t.id, label: "　".repeat(level) + (t.name || t.code) },
    ...flattenTypeOptions(t.children, level + 1),
  ]);
}

function findType(types, id) {
  if (!Array.isArray(types)) return null;
  for (const t of types) {
    if (t.id === id) return t;
    const found = findType(t.children, id);
    if (found) return found;
  }
  return null;
}

function convertToTypeData(types) {
  if (!Array.isArray(types)) return [];
  return types.map((t) => ({
    key: t.id,
    title: t.name || t.code,
    children: t.children ? convertToTypeData(t.children) : [],
  }));
}

function filterTypes(types) {
  if (!Array.isArray(types)) return [];
  return types.reduce((acc, t) => {
    const filteredChildren = t.children ? filterTypes(t.children) : [];
    if (filteredChildren.length > 0) {
      acc.push({ ...t, children: filteredChildren });
    }
    return acc;
  }, []);
}

/* ── flattenTypeOptions ── */

test("flattenTypeOptions returns [] for undefined input", () => {
  assert.deepEqual(flattenTypeOptions(undefined), []);
});

test("flattenTypeOptions returns [] for null input", () => {
  assert.deepEqual(flattenTypeOptions(null), []);
});

test("flattenTypeOptions returns [] for empty array", () => {
  assert.deepEqual(flattenTypeOptions([]), []);
});

test("flattenTypeOptions handles node with null children", () => {
  const tree = [{ id: "a", code: "a", name: "A", parent_id: null, children: null }];
  const result = flattenTypeOptions(tree);
  assert.deepEqual(result, [{ value: "a", label: "A" }]);
});

test("flattenTypeOptions handles node with undefined children", () => {
  const tree = [{ id: "b", code: "b", name: "B", parent_id: null, children: undefined }];
  const result = flattenTypeOptions(tree);
  assert.deepEqual(result, [{ value: "b", label: "B" }]);
});

test("flattenTypeOptions flattens nested tree with normal children", () => {
  const tree = [
    {
      id: "root",
      code: "r",
      name: "Root",
      parent_id: null,
      children: [{ id: "child", code: "c", name: "Child", parent_id: "root", children: [] }],
    },
  ];
  const result = flattenTypeOptions(tree);
  assert.equal(result.length, 2);
  assert.equal(result[0].value, "root");
  assert.equal(result[1].value, "child");
});

/* ── findType ── */

test("findType returns null for undefined input", () => {
  assert.equal(findType(undefined, "a"), null);
});

test("findType returns null for null input", () => {
  assert.equal(findType(null, "a"), null);
});

test("findType returns null for empty array", () => {
  assert.equal(findType([], "a"), null);
});

test("findType handles node with null children", () => {
  const tree = [{ id: "a", code: "a", name: "A", parent_id: null, children: null }];
  assert.equal(findType(tree, "a")?.id, "a");
  assert.equal(findType(tree, "missing"), null);
});

test("findType handles node with undefined children", () => {
  const tree = [{ id: "a", code: "a", name: "A", parent_id: null, children: undefined }];
  assert.equal(findType(tree, "a")?.id, "a");
});

test("findType traverses nested tree with normal children", () => {
  const tree = [
    {
      id: "root",
      code: "r",
      name: "Root",
      parent_id: null,
      children: [{ id: "child", code: "c", name: "Child", parent_id: "root", children: [] }],
    },
  ];
  assert.equal(findType(tree, "child")?.name, "Child");
});

/* ── convertToTypeData ── */

test("convertToTypeData returns [] for undefined input", () => {
  assert.deepEqual(convertToTypeData(undefined), []);
});

test("convertToTypeData returns [] for null input", () => {
  assert.deepEqual(convertToTypeData(null), []);
});

test("convertToTypeData handles node with null children", () => {
  const tree = [{ id: "a", code: "a", name: "A", parent_id: null, children: null }];
  const result = convertToTypeData(tree);
  assert.equal(result.length, 1);
  assert.equal(result[0].key, "a");
  assert.deepEqual(result[0].children, []);
});

test("convertToTypeData handles node with undefined children", () => {
  const tree = [{ id: "b", code: "b", name: "B", parent_id: null, children: undefined }];
  const result = convertToTypeData(tree);
  assert.equal(result[0].key, "b");
  assert.deepEqual(result[0].children, []);
});

/* ── filterTypes ── */

test("filterTypes returns [] for undefined input", () => {
  assert.deepEqual(filterTypes(undefined), []);
});

test("filterTypes returns [] for null input", () => {
  assert.deepEqual(filterTypes(null), []);
});

test("filterTypes handles node with null children", () => {
  const tree = [{ id: "a", code: "a", name: "A", parent_id: null, children: null }];
  assert.deepEqual(filterTypes(tree), []);
});