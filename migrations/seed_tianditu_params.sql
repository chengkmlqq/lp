-- Seed: 天地图（Tianditu）底图参数 → 系统参数（system_params）
-- 目标：线路管理页 Cesium 地图改用天地图瓦片数据作为底图（LP-244）。
--       所有参数配置到系统参数管理页面，前端不硬编码（Key / URL / 图层 / 子域 / 层级等）。
-- 幂等：param_key 唯一约束，ON CONFLICT DO NOTHING，可重复执行。
-- 备注：tianditu.tk 需管理员在系统参数管理页面填写官方 Key（留空则前端回退深色背景，不报错）。
-- 注：is_encrypted 为 NOT NULL（add_system_params_is_encrypted.sql 引入），必须显式给值。

INSERT INTO system_params (param_key, param_name, param_value, description, status, is_encrypted, created_at, updated_at)
VALUES
  ('tianditu.enabled', '天地图底图启用', 'true',
    '是否启用天地图底图（true=加载天地图；false=维持现状深色背景）', 'enabled', false,
    NOW() AT TIME ZONE 'UTC', NOW() AT TIME ZONE 'UTC'),
  ('tianditu.tk', '天地图官方Key', '',
    '天地图官方接口 Key（需申请；为空时前端回退深色背景，不加载底图）', 'enabled', false,
    NOW() AT TIME ZONE 'UTC', NOW() AT TIME ZONE 'UTC'),
  ('tianditu.base_layer', '底图类型', 'vec',
    '底图图层类型：vec（矢量）/ img（影像）/ ter（地形）', 'enabled', false,
    NOW() AT TIME ZONE 'UTC', NOW() AT TIME ZONE 'UTC'),
  ('tianditu.annotation_layer', '注记图层', 'cva',
    '注记层：cva（矢量注记）/ cia（影像注记）/ cta（地形注记）；留空=不叠加注记', 'enabled', false,
    NOW() AT TIME ZONE 'UTC', NOW() AT TIME ZONE 'UTC'),
  ('tianditu.url_template', '瓦片URL模板',
    'https://t{s}.tianditu.gov.cn/{layer}_w/wmts?SERVICE=WMTS&REQUEST=GetTile&VERSION=1.0.0&LAYER={layer}&STYLE=default&TILEMATRIXSET=w&FORMAT=tiles&TILEMATRIX={z}&TILEROW={y}&TILECOL={x}&tk={tk}',
    '瓦片 URL 模板；{s}/{z}/{y}/{x} 由 Cesium 替换，{layer}/{tk} 由前端替换。留空时前端使用内置同构默认模板', 'enabled', false,
    NOW() AT TIME ZONE 'UTC', NOW() AT TIME ZONE 'UTC'),
  ('tianditu.subdomains', '子域列表', '0,1,2,3,4,5,6,7',
    '天地图瓦片子域（逗号分隔）', 'enabled', false,
    NOW() AT TIME ZONE 'UTC', NOW() AT TIME ZONE 'UTC'),
  ('tianditu.max_level', '最大缩放层级', '18',
    '最大缩放层级（瓦片 maximumLevel）', 'enabled', false,
    NOW() AT TIME ZONE 'UTC', NOW() AT TIME ZONE 'UTC'),
  ('tianditu.coord_transform', '坐标转换', 'false',
    '是否做 GCJ-02 → WGS-84 坐标转换（天地图为 GCJ-02，业务杆塔为 WGS-84；取值 true/false，需实测偏移后决定）', 'enabled', false,
    NOW() AT TIME ZONE 'UTC', NOW() AT TIME ZONE 'UTC')
ON CONFLICT (param_key) DO NOTHING;
