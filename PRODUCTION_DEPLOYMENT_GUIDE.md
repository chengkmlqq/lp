# 生产环境部署导出功能指南

## 问题说明
导出功能的代码已经提交到git仓库，但生产环境（http://223.109.142.84:3002）还在运行旧版本的代码，需要重新构建和部署。

## 部署步骤

### 方式一：如果有独立的生产服务器

如果生产环境是在另一台服务器上，需要在**生产服务器**上执行：

```bash
# 1. 进入项目目录
cd /path/to/production/lp

# 2. 拉取最新代码
git pull origin dev

# 3. 进入web目录
cd web

# 4. 安装新的依赖包
npm install

# 5. 构建生产版本
npm run build

# 6. 重启生产服务
# 方式根据你的部署方式而定：
pm2 restart lp-web
# 或
systemctl restart lp-web
# 或停止旧进程并启动新进程
```

### 方式二：如果当前服务器就是生产环境

当前服务器（10.19.196.20）可能通过Nginx反向代理到3002端口。

#### 步骤1：确认生产服务的位置和启动方式

```bash
# 检查是否使用PM2管理
pm2 list

# 检查是否使用systemd管理
systemctl list-units | grep lp

# 检查Nginx配置
cat /etc/nginx/sites-enabled/* | grep 3002

# 或
cat /etc/nginx/conf.d/*.conf | grep 3002
```

#### 步骤2：拉取最新代码并安装依赖

```bash
cd /home/jenkins/chengkai/lp/web

# 确保在正确的分支
git status

# 如果有本地修改，先提交或暂存
git stash  # 可选

# 拉取最新代码（如果需要）
git pull origin dev

# 安装依赖（关键！包含新的导出库）
npm install
```

#### 步骤3：构建生产版本

```bash
# 在 /home/jenkins/chengkai/lp/web 目录下
npm run build
```

#### 步骤4：重启生产服务

根据你的部署方式选择：

**如果使用PM2：**
```bash
pm2 restart all
# 或指定应用名称
pm2 restart lp-web
```

**如果使用systemd：**
```bash
sudo systemctl restart lp-web
```

**如果手动运行：**
```bash
# 找到生产进程
ps aux | grep "next start"

# 停止旧进程（替换<PID>为实际进程ID）
kill <PID>

# 启动新进程
cd /home/jenkins/chengkai/lp/web
npm run start
```

### 方式三：如果无法确定部署方式

请运行以下诊断命令，并把结果告诉我：

```bash
# 1. 检查PM2
pm2 list

# 2. 检查systemd服务
systemctl list-units | grep -E "lp|web"

# 3. 检查所有Node进程
ps aux | grep node

# 4. 检查Nginx配置
sudo cat /etc/nginx/sites-enabled/default | grep -A 10 "3002"

# 5. 检查端口占用
sudo netstat -tlnp | grep -E "3000|3001|3002"
```

## 验证部署成功

部署完成后，验证功能：

1. **清除浏览器缓存**：
   - 按 `Ctrl + Shift + Delete`
   - 选择"清除缓存的图像和文件"
   - 或直接强制刷新：`Ctrl + Shift + R`

2. **访问页面**：
   - 打开 http://223.109.142.84:3002/fault-analysis/[任意ID]
   
3. **测试导出**：
   - 点击"导出报告"按钮
   - 应该看到下拉菜单，显示"导出为 PDF"和"导出为 Word"

4. **检查浏览器控制台**：
   - 按F12打开开发者工具
   - 在Console中不应有错误

## 常见问题

### Q1: npm install 时报错
```bash
# 清除缓存重试
npm cache clean --force
npm install
```

### Q2: npm run build 失败
```bash
# 查看详细错误
npm run build 2>&1 | tee build.log

# 检查Node版本（需要18+）
node --version
```

### Q3: 构建成功但功能还是不工作
- 确认已重启服务
- 清除浏览器缓存（Ctrl + Shift + Delete）
- 检查是否访问了正确的URL

### Q4: 找不到生产服务进程
可能是通过Docker运行，检查：
```bash
docker ps
docker-compose ps
```

## 需要帮助？

如果遇到问题，请提供：
1. 执行的命令和输出
2. 错误信息截图
3. `pm2 list` 或 `ps aux | grep node` 的输出
