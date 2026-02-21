# PathLab 部署文档

## 前置要求

- Ubuntu 20.04+ / Debian 11+
- Python 3.10+ (推荐使用 Conda)
- Node.js 18+
- Redis 6+
- Nginx
- 开放端口: 80 (HTTP), 443 (HTTPS)
- 可选: CrowdSec (安全防护)

## 架构

```
                        用户
                         │
                         ▼
                   your-domain:80/443
                         │
                         ▼
                    ┌─────────┐
                    │  Nginx  │  (反向代理 + 静态文件)
                    └────┬────┘
                         │
        ┌────────────────┼────────────────┐
        ▼                ▼                ▼
   /              /api/*           /preprocessing/*
   (静态文件)         │                    │
                     ▼                    ▼
              localhost:6100       localhost:6101
              (Gateway)            (Preprocessing)
                     │                    │
                     ▼                    ▼
              localhost:6379       localhost:6102
              (Redis)             (AI Service)
```

## 文件结构

```
pathlab-client/
├── deploy/
│   ├── README.md              # 本文档
│   ├── start.sh               # 后端启动脚本
│   ├── deploy.sh              # 构建脚本
│   ├── nginx/
│   │   ├── pathlab.conf           # HTTPS 配置模板
│   │   └── pathlab-http-only.conf # HTTP 配置模板
│   └── systemd/
│       └── pathlab.service    # systemd 服务文件模板
├── src/renderer/
│   ├── dist/                  # 前端构建产物
│   └── .env.production        # 生产环境变量
├── server/                    # Python 后端
│   └── main.py                # 后端入口
└── logs/                      # 运行日志
    ├── backend.log
    └── backend.pid
```

## 快速命令

```bash
cd /path/to/pathlab-client

# 查看服务状态
./deploy/start.sh status

# 启动后端
./deploy/start.sh start

# 停止后端
./deploy/start.sh stop

# 重启后端
./deploy/start.sh restart

# 查看日志
./deploy/start.sh logs

# 重新构建前端
./deploy/deploy.sh build
```

## 首次部署步骤

### 1. 安装依赖

```bash
# Python 依赖
pip install -r server/requirements.txt
pip install nystrom-attention  # 额外依赖

# Node 依赖
npm install
```

### 2. 构建前端

```bash
./deploy/deploy.sh build
```

### 3. 配置 Nginx (需要 sudo)

```bash
# 复制并编辑配置 (需要修改域名和路径)
sudo cp deploy/nginx/pathlab-http-only.conf /etc/nginx/sites-available/pathlab
sudo vim /etc/nginx/sites-available/pathlab
# 修改:
#   - server_name your-domain.com;
#   - root /path/to/pathlab-client/src/renderer/dist;

# 启用站点
sudo ln -sf /etc/nginx/sites-available/pathlab /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default

# 设置目录权限 (让 nginx 能读取前端文件)
# 需要给从根目录到 dist 的所有父目录添加 o+x 权限
chmod o+x /path/to/parent/directories...
chmod -R o+r /path/to/pathlab-client/src/renderer/dist

# 测试并重载
sudo nginx -t
sudo systemctl reload nginx
```

### 4. 配置并启动后端

**方式 A: 使用启动脚本 (推荐日常使用)**

先编辑 `deploy/start.sh`，修改 Python 路径:
```bash
# 找到这一行，改成你的 Python 路径
ExecStart=/path/to/python3 main.py
```

然后启动:
```bash
./deploy/start.sh start
```

**方式 B: 使用 systemd (推荐生产环境)**

先编辑 `deploy/systemd/pathlab.service`，修改:
- `User` 和 `Group`
- `WorkingDirectory`
- `ExecStart` 中的 Python 路径
- `PATHLAB_UPLOADS_DIR` 环境变量

然后:
```bash
sudo cp deploy/systemd/pathlab.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable pathlab
sudo systemctl start pathlab
```

### 5. 验证

```bash
# 检查后端
curl http://127.0.0.1:6100/health

# 检查公网访问
curl http://your-domain.com/api/health
```

## 服务端口

| 服务 | 端口 | 说明 |
|------|------|------|
| Nginx | 80 | HTTP 入口 |
| Gateway | 6100 | API 网关 |
| Preprocessing | 6101 | WSI 处理、瓦片服务 |
| AI | 6102 | 模型训练、推理 |
| Redis | 6379 | 缓存层（训练日志、任务进度、分析状态） |

## 日志位置

| 日志 | 位置 |
|------|------|
| 后端日志 | `logs/backend.log` |
| Nginx 访问日志 | `/var/log/nginx/access.log` |
| Nginx 错误日志 | `/var/log/nginx/error.log` |
| systemd 日志 | `journalctl -u pathlab -f` |

## 常见问题

### 502 Bad Gateway
后端服务未运行，执行 `./deploy/start.sh start`

### 500 Internal Server Error
Nginx 无权限读取文件，检查目录权限

### 白屏
检查浏览器 Console (F12)，可能是 API 路径问题或缓存

### ModuleNotFoundError
缺少 Python 依赖，检查是否使用了正确的 Python 环境

## HTTPS 配置

使用 Let's Encrypt 获取免费 SSL 证书:

```bash
# 1. 确保 80/443 端口对外网开放 (Let's Encrypt 需要验证域名)

# 2. 安装 certbot
sudo apt install certbot python3-certbot-nginx

# 3. 获取证书 (使用 webroot 方式，不中断服务)
sudo certbot certonly --webroot -w /path/to/pathlab-client/src/renderer/dist -d your-domain.com

# 4. 证书获取成功后，切换到 HTTPS 配置
sudo cp deploy/nginx/pathlab.conf /etc/nginx/sites-available/pathlab
sudo nginx -t
sudo systemctl reload nginx

# 5. 证书自动续期 (certbot 已自动配置定时任务)
sudo certbot renew --dry-run  # 测试续期
```

证书位置: `/etc/letsencrypt/live/your-domain.com/`

## 安全防护 (CrowdSec)

CrowdSec 是一个现代化的安全引擎，可以分析 Nginx 日志检测攻击并自动封禁恶意 IP。

### 安装 CrowdSec

```bash
# 1. 添加 CrowdSec 仓库并安装
curl -s https://install.crowdsec.net | sudo sh
sudo apt install crowdsec

# 2. 安装 Firewall Bouncer (通过 iptables 封禁 IP)
sudo apt install crowdsec-firewall-bouncer-iptables

# 3. 安装 Nginx 日志分析规则
sudo cscli collections install crowdsecurity/nginx

# 4. 重启服务
sudo systemctl restart crowdsec
sudo systemctl restart crowdsec-firewall-bouncer
```

### 验证安装

```bash
# 检查 CrowdSec 状态
sudo systemctl status crowdsec

# 检查 Bouncer 状态
sudo systemctl status crowdsec-firewall-bouncer

# 查看已注册的 Bouncer
sudo cscli bouncers list

# 查看已安装的规则集
sudo cscli collections list
```

### 手动管理 IP 封禁

```bash
# 封禁单个 IP（默认 4 小时）
sudo cscli decisions add --ip 1.2.3.4

# 封禁 IP 并指定时长
sudo cscli decisions add --ip 1.2.3.4 --duration 24h

# 永久封禁
sudo cscli decisions add --ip 1.2.3.4 --duration 8760h  # 1年

# 封禁 IP 段
sudo cscli decisions add --range 1.2.3.0/24

# 封禁并添加原因
sudo cscli decisions add --ip 1.2.3.4 --reason "manual ban - suspicious activity"

# 查看所有封禁
sudo cscli decisions list

# 解封特定 IP
sudo cscli decisions delete --ip 1.2.3.4

# 解封所有
sudo cscli decisions delete --all

# 确认 iptables 规则已生效
sudo iptables -L -n | grep DROP
```

### 配置白名单

编辑 `/etc/crowdsec/parsers/s02-enrich/my-whitelist.yaml`:

```yaml
name: my_whitelist
description: "Trusted IPs that should never be banned"
whitelist:
  reason: "trusted IPs"
  ip:
    - "127.0.0.1"
    - "10.0.0.0/8"
    - "192.168.0.0/16"
    # 添加你信任的 IP
```

然后重启 CrowdSec:
```bash
sudo systemctl restart crowdsec
```

### 查看攻击日志

```bash
# 查看检测到的攻击
sudo cscli alerts list

# 查看详细信息
sudo cscli alerts inspect <alert_id>

# 实时监控
sudo tail -f /var/log/crowdsec.log
```

### CrowdSec 常用命令速查

| 命令 | 说明 |
|------|------|
| `sudo cscli decisions list` | 查看当前封禁列表 |
| `sudo cscli decisions add --ip X.X.X.X` | 手动封禁 IP |
| `sudo cscli decisions delete --ip X.X.X.X` | 解封 IP |
| `sudo cscli alerts list` | 查看攻击告警 |
| `sudo cscli bouncers list` | 查看 Bouncer 状态 |
| `sudo cscli metrics` | 查看统计指标 |
| `sudo cscli hub update` | 更新规则库 |

## 更新部署

```bash
# 1. 拉取最新代码
git pull

# 2. 重新构建前端 (如有前端更新)
./deploy/deploy.sh build

# 3. 重启后端 (如有后端更新)
./deploy/start.sh restart
# 或
sudo systemctl restart pathlab
```

