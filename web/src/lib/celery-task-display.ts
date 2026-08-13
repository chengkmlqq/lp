const TASK_NAME_LABELS: Record<string, string> = {
  "app.tasks.atp_asset_tasks.execute_atp_asset_run_job": "ATP 模型运行",
  "app.tasks.atp_asset_tasks.process_release_archive_upload": "ATP 版本归档处理",
  "app.tasks.elevation_tasks.analyze_elevation_file_record_job": "高程文件记录分析",
  "app.tasks.elevation_tasks.build_elevation_file_record_terrain_job": "高程文件记录地形生成",
  "app.tasks.elevation_tasks.report_ctb_task_state": "高程地形构建状态回执",
  "app.tasks.elevation_tasks.apply_elevation_for_line_job": "线路高程回填",
  "app.tasks.fl_analysis_tasks.execute_fl_analysis_job": "防雷分析计算",
  "app.tasks.fault_diagnosis_tasks.run_fault_diagnosis_task": "故障综合判别",
  "app.tasks.lightning_tasks.import_lightning_distribution_job": "地闪分布数据导入",
  "app.tasks.lightning_tasks.import_lightning_amplitude_job": "雷电流幅值数据导入",
  "app.tasks.lightning_tasks.render_lp_density_job": "LP 分区密度图绘制",
  "app.tasks.log_cleanup_tasks.cleanup_expired_task_logs": "过期任务日志清理",
  "app.tasks.scheduled_task_tasks.dispatch_due_scheduled_tasks": "到期定时任务派发",
  "app.tasks.scheduled_task_tasks.execute_scheduled_task_job": "定时任务执行",
  "app.tasks.wine_tasks.execute_wine_run_job": "Wine 程序执行",
  "app.tasks.worker_registry_tasks.sweep_worker_registry_offline": "执行节点离线巡检",
  "app.tasks.worker_registry_tasks.flush_task_log_buffers": "任务日志缓冲落库",
};

export function getTaskDisplayName(taskName: string | null | undefined): string {
  const normalized = (taskName || "").trim();
  if (!normalized) {
    return "-";
  }
  const label = TASK_NAME_LABELS[normalized];
  if (!label) {
    if (normalized.startsWith("app.tasks.")) {
      return "未识别任务";
    }
    return normalized;
  }
  return label;
}
