import {
  fetchWithAuth,
  getJson,
  postJson,
  readApiError,
} from "@/lib/api";
import type {
  CreateMatlabModulePayload,
  MatlabModule,
  MatlabModuleFilesResponse,
  MatlabModuleVersionsResponse,
  MatlabSyncResponse,
  MatlabVersion,
} from "@/types/matlab-engine";

export async function fetchMatlabModules(): Promise<MatlabModule[]> {
  const response = await getJson<{ items: MatlabModule[] }>("/api/v1/fault-matlab/modules");
  return response.items ?? [];
}

export async function createMatlabModule(
  payload: CreateMatlabModulePayload,
): Promise<MatlabModule> {
  return postJson<MatlabModule>("/api/v1/fault-matlab/modules", payload);
}

export async function updateMatlabModule(
  slug: string,
  payload: Partial<CreateMatlabModulePayload>,
): Promise<MatlabModule> {
  const response = await fetchWithAuth(`/api/v1/fault-matlab/modules/${encodeURIComponent(slug)}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) throw new Error(await readApiError(response));
  return (await response.json()) as MatlabModule;
}

export async function deleteMatlabModule(slug: string): Promise<void> {
  const response = await fetchWithAuth(`/api/v1/fault-matlab/modules/${encodeURIComponent(slug)}`, {
    method: "DELETE",
  });
  if (!response.ok) throw new Error(await readApiError(response));
}

export async function fetchMatlabModuleVersions(
  slug: string,
): Promise<MatlabModuleVersionsResponse> {
  return getJson<MatlabModuleVersionsResponse>(
    `/api/v1/fault-matlab/modules/${encodeURIComponent(slug)}/versions`,
  );
}

export async function uploadMatlabRelease(
  slug: string,
  file: File,
  payload: { version_tag: string; changelog: string },
): Promise<MatlabVersion> {
  const formData = new FormData();
  formData.append("file", file);
  formData.append("version_tag", payload.version_tag);
  formData.append("changelog", payload.changelog);
  const response = await fetchWithAuth(
    `/api/v1/fault-matlab/modules/${encodeURIComponent(slug)}/upload`,
    { method: "POST", body: formData },
  );
  if (!response.ok) throw new Error(await readApiError(response));
  return (await response.json()) as MatlabVersion;
}

export async function deleteMatlabVersion(slug: string, versionHash: string): Promise<void> {
  const response = await fetchWithAuth(
    `/api/v1/fault-matlab/modules/${encodeURIComponent(slug)}/versions/${encodeURIComponent(versionHash)}`,
    { method: "DELETE" },
  );
  if (!response.ok) throw new Error(await readApiError(response));
}

export async function fetchMatlabVersionFiles(
  slug: string,
  versionHash: string,
): Promise<MatlabModuleFilesResponse> {
  return getJson<MatlabModuleFilesResponse>(
    `/api/v1/fault-matlab/modules/${encodeURIComponent(slug)}/versions/${encodeURIComponent(versionHash)}/files`,
  );
}

export async function syncMatlabVersion(slug: string, versionHash: string): Promise<MatlabSyncResponse> {
  return postJson<MatlabSyncResponse>(
    `/api/v1/fault-matlab/modules/${encodeURIComponent(slug)}/versions/${encodeURIComponent(versionHash)}/sync`,
    {},
  );
}

/**
 * 下载指定版本（草稿或已发布）上传的 engine.zip 原始包。
 * 通过携带鉴权请求拉取 blob，再触发浏览器下载。
 */
export async function downloadMatlabPackage(slug: string, versionHash: string): Promise<void> {
  const response = await fetchWithAuth(
    `/api/v1/fault-matlab/modules/${encodeURIComponent(slug)}/versions/${encodeURIComponent(versionHash)}/download`,
  );
  if (!response.ok) {
    throw new Error(await readApiError(response));
  }
  const blob = await response.blob();
  const disposition = response.headers.get("Content-Disposition") ?? "";

  // 优先从 Content-Disposition 的 filename*（UTF-8 编码）解析文件名，其次取默认名。
  const utf8Match = disposition.match(/filename\*=(?:UTF-8'')?([^;]+)/i);
  const plainMatch = disposition.match(/filename="([^"]+)"/i);
  const rawName = (utf8Match?.[1] ?? plainMatch?.[1] ?? "").trim().replace(/"/g, "");
  const fileName = rawName ? decodeURIComponent(rawName) : "engine.zip";

  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = fileName;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(url);
}
