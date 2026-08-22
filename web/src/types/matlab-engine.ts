export type MatlabModule = {
  slug: string;
  name: string;
  description: string;
  required_files: string[];
  worker_deploy_path: string;
  created_at?: string;
  updated_at?: string;
};

export type MatlabVersion = {
  version_hash: string;
  version_tag: string;
  changelog: string;
  uploaded_by: string;
  uploaded_by_name: string;
  upload_time: string;
  size_bytes: number;
  file_list: string[];
  is_active?: boolean;
};

export type MatlabModuleVersionsResponse = {
  slug: string;
  draft: MatlabVersion | null;
  releases: MatlabVersion[];
};

export type MatlabModuleFilesResponse = {
  slug: string;
  version_hash: string;
  scope: "draft" | "release";
  version_tag: string;
  file_list: string[];
};

export type MatlabSyncResponse = {
  task_id: string;
  status: string;
};

export type CreateMatlabModulePayload = {
  slug?: string;
  name: string;
  description?: string;
  required_files?: string[];
  worker_deploy_path?: string;
};
