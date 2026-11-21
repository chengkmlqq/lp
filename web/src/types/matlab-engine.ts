export type MatlabModule = {
  slug: string;
  name: string;
  description: string;
  required_files: string[];
  worker_deploy_path: string;
  /** 同步任务目标队列；历史模块无该字段时后端按 matlab-diagnostics 归一化。 */
  worker_queue?: string;
  created_at?: string;
  updated_at?: string;
};

/** 版本最近一次同步（部署）任务的状态，由后端随版本列表下发。 */
export type MatlabVersionSyncState = {
  status: "pending" | "running" | "completed" | "failed";
  task_id?: string;
  queue?: string;
  /** 执行该任务的 celery 节点名，如 matlab-wind@ctyun-local。 */
  worker?: string;
  error?: string;
  requested_at?: string;
  started_at?: string;
  finished_at?: string;
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
  deployed_at?: string;
  /** 实际部署到哪台 worker（celery 节点名），同步成功时写入。 */
  deployed_worker?: string;
  sync_state?: MatlabVersionSyncState;
};

export type MatlabModuleListResponse = {
  items: MatlabModule[];
  total: number;
};

export type MatlabModuleVersionsResponse = {
  slug: string;
  releases: MatlabVersion[];
  total: number;
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

/** 某队列的在线 worker 快照（来自 Flower，按队列聚合）。 */
export type MatlabQueueWorkerItem = {
  queue: string;
  online: number;
  workers: string[];
};

export type MatlabQueueWorkersResponse = {
  available: boolean;
  generated_at?: string | null;
  error?: string | null;
  queues: MatlabQueueWorkerItem[];
};

export type CreateMatlabModulePayload = {
  slug?: string;
  name: string;
  description?: string;
  required_files?: string[];
  worker_deploy_path?: string;
  worker_queue?: string;
};

export type MatlabUploadPayload = {
  version_tag: string;
  changelog?: string;
};
