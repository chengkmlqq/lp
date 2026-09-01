import {
  fetchWithAuth,
  getJson,
  postJson,
  readApiError,
  uploadFileWithAuth,
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

export async function uploadMatlabDraft(slug: string, file: File): Promise<MatlabVersion> {
  const response = await uploadFileWithAuth(
    `/api/v1/fault-matlab/modules/${encodeURIComponent(slug)}/upload`,
    file,
  );
  if (!response.ok) throw new Error(await readApiError(response));
  return (await response.json()) as MatlabVersion;
}

export async function publishMatlabDraft(
  slug: string,
  payload: { version_tag: string; changelog: string },
): Promise<MatlabVersion> {
  return postJson<MatlabVersion>(
    `/api/v1/fault-matlab/modules/${encodeURIComponent(slug)}/publish`,
    payload,
  );
}

export async function rollbackMatlabVersion(slug: string, versionHash: string): Promise<MatlabVersion> {
  return postJson<MatlabVersion>(
    `/api/v1/fault-matlab/modules/${encodeURIComponent(slug)}/rollback`,
    { version_hash: versionHash },
  );
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

export async function syncMatlabModule(slug: string): Promise<MatlabSyncResponse> {
  return postJson<MatlabSyncResponse>(
    `/api/v1/fault-matlab/modules/${encodeURIComponent(slug)}/sync`,
    {},
  );
}
