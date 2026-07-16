# 高程数据GDEM V2集成与gdal2tiles瓦片生成改造

## 改造概述

本次改造将高程数据管理系统升级以支持：
1. **GDEM V2/V3 30米数据集**的自动识别和标记
2. 使用 **gdal2tiles** 替代原有瓦片生成方案，生成Cesium heightmap-1.0格式的地形瓦片

## 数据库迁移

### 迁移文件
- `api/migrations/004_add_elevation_data_source_type.sql`

### 新增字段
- `elevation_dataset.data_source_type` (VARCHAR(32), 默认'generic')
- `elevation_file_record.data_source_type` (VARCHAR(32), 默认'generic')

### 数据源类型
- `generic`: 通用高程数据
- `gdemv2`: ASTER GDEM V2 (30米分辨率)
- `gdemv3`: ASTER GDEM V3 (30米分辨率)
- `srtm`: SRTM数据集（预留）

### 执行迁移
```bash
psql -U <username> -d <database> -f api/migrations/004_add_elevation_data_source_type.sql
```

## 后端改造

### 1. GDEM数据检测 (`elevation_service.py`)

#### 功能函数
```python
def _detect_gdem_dataset(filename: str) -> dict[str, Any] | None:
    """
    检测是否为GDEM数据集文件
    
    支持的文件名格式:
    - ASTGTMV003_N30E120_dem.tif (GDEM V3)
    - ASTGTM2_N30E120_dem.tif (GDEM V2)
    
    返回：
    - source_type: gdemv2 或 gdemv3
    - tile_lat/tile_lon: 瓦片纬度/经度
    - resolution_m: 30.0 (米)
    - bounds: 瓦片边界范围
    """
```

#### 自动检测时机
1. **创建数据集时** (`create_dataset`)
   - 检测文件名是否匹配GDEM模式
   - 自动设置 `data_source_type`
   - 自动设置 `resolution_m` 为30.0米
   - 自动设置 `source` 为"ASTER GDEM"

2. **导入数据文件时** (`_perform_dataset_data_import`)
   - 选择preferred文件后检测
   - 更新数据集的数据源类型和分辨率

3. **分析数据集时** (`_analyze_dataset_content`)
   - 分析主文件时检测GDEM信息
   - 更新数据集元数据

4. **分析文件记录时** (`execute_file_record_analysis_job`)
   - 分析单个文件时检测GDEM信息

### 2. 瓦片生成改造

#### 使用gdal2tiles工具
原有方案被替换为使用 `gdal2tiles.py` 命令行工具：

```python
def _build_dataset_terrain_tiles(db: Session, dataset: ElevationDataset):
    """使用gdal2tiles生成Cesium heightmap-1.0格式地形瓦片"""
    
    cmd = [
        "gdal2tiles.py",
        "--profile=raster",      # 栅格配置
        f"--zoom={min_zoom}-{max_zoom}",
        "--resampling=average",  # 平均重采样
        "--tilesize=65",         # Cesium标准尺寸
        "--processes=4",         # 并行处理
        "--xyz",                 # XYZ瓦片方案
        input_file,
        output_dir,
    ]
```

#### 瓦片格式转换
gdal2tiles生成PNG后，转换为Cesium heightmap-1.0格式：

```python
def _convert_png_to_heightmap(png_path: Path) -> bytes:
    """
    将PNG瓦片转换为Cesium heightmap-1.0格式
    
    格式规范:
    - 前8450字节: 65x65的16位小端无符号整数高程数据
    - 第8451字节: child mask (子瓦片可用性标记)
    - 第8452字节: water mask (水体掩码，0x00=全陆地)
    """
```

#### 瓦片存储结构
```
/elevation/datasets/{dataset_code}/terrain/
├── layer.json           # 图层配置
├── 0/
│   └── 0/
│       └── 0.terrain
├── 1/
│   ├── 0/
│   │   ├── 0.terrain
│   │   └── 1.terrain
│   └── 1/
│       ├── 0.terrain
│       └── 1.terrain
└── ...
```

### 3. API Schema更新

#### ElevationDatasetSummary
```python
class ElevationDatasetSummary(BaseModel):
    # ... 其他字段
    data_source_type: str = "generic"  # 新增
```

#### ElevationFileRecordSummary
```python
class ElevationFileRecordSummary(BaseModel):
    # ... 其他字段
    data_source_type: str = "generic"  # 新增
```

## 依赖更新

### requirements.txt
```txt
rasterio==1.4.3
GDAL>=3.6.0           # gdal2tiles.py随GDAL安装
Pillow>=10.0.0        # PNG处理
numpy>=1.24.0         # 数组处理
```

### Docker镜像要求
需要在API镜像中安装GDAL工具：
```dockerfile
RUN apt-get update && apt-get install -y \
    gdal-bin \
    python3-gdal \
    && rm -rf /var/lib/apt/lists/*
```

## 使用示例

### 1. 导入GDEM数据
```bash
# 上传GDEM V2文件: ASTGTM2_N30E120_dem.tif
# 系统自动识别为gdemv2数据源，分辨率30m
```

### 2. 生成地形瓦片
```bash
# API会自动使用gdal2tiles生成瓦片
# 瓦片级别根据分辨率自动计算（30m数据通常6-8级）
```

### 3. Cesium加载
```javascript
const terrainProvider = new Cesium.CesiumTerrainProvider({
  url: '/api/v1/elevation/datasets/{dataset_id}/terrain',
});

viewer.terrainProvider = terrainProvider;
```

## 测试验证

### 1. 数据检测测试
```python
# 测试GDEM V2文件名识别
result = _detect_gdem_dataset("ASTGTM2_N30E120_dem.tif")
assert result["source_type"] == "gdemv2"
assert result["resolution_m"] == 30.0
assert result["bounds"]["west"] == 120.0
assert result["bounds"]["north"] == 31.0
```

### 2. 瓦片生成测试
```bash
# 上传GDEM文件后，触发地形生成任务
# 检查生成的瓦片：
ls -lh /elevation/datasets/{code}/terrain/

# 验证layer.json
curl http://localhost/api/v1/elevation/datasets/{id}/terrain/layer.json
```

## 注意事项

1. **GDAL版本要求**: 需要GDAL >= 3.6.0，确保gdal2tiles.py可用
2. **内存使用**: 大文件生成瓦片时会占用较多内存，建议4GB以上
3. **生成时间**: 30m数据生成6级瓦片约需1-5分钟
4. **存储空间**: 每个数据集的瓦片约占10-100MB
5. **坐标系统**: 输入数据建议使用WGS84 (EPSG:4326)

## 后续优化建议

1. **瓦片压缩**: 考虑使用gzip压缩瓦片文件
2. **增量更新**: 支持只更新变化区域的瓦片
3. **多数据源融合**: 支持多个GDEM瓦片自动拼接
4. **CDN加速**: 将瓦片推送到CDN提高访问速度
5. **缓存策略**: 在API层增加瓦片缓存

## 相关文件

### 后端
- `api/app/models/elevation.py` - 数据模型
- `api/app/services/elevation_service.py` - 核心服务逻辑
- `api/app/schemas/elevation.py` - API Schema
- `api/migrations/004_add_elevation_data_source_type.sql` - 数据库迁移

### 前端
- `web/src/app/admin/elevation-records/page.tsx` - 文件记录管理页面
- `web/src/components/elevation-preview-cesium-map.tsx` - Cesium地图组件

### 配置
- `api/requirements.txt` - Python依赖
- `docker-compose.yml` - Docker配置（需要更新API镜像）

---

**改造完成日期**: 2026-07-04  
**改造负责人**: Claude Code  
**版本**: v1.0
