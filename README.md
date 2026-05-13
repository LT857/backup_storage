# 📦 AstrBot 本地文件备份储存插件 v2.0

一个强大的本地文件备份管理插件，支持手动备份、定时备份、多路径监控和自动转发到群聊。

## ✨ 功能特性

- 💾 **手动备份** - 将本地文件保存到备份目录
- ⏰ **定时备份** - 按设定间隔自动备份监控目录中的新文件
- 📁 **多路径监控** - 支持配置多个监控路径，自动扫描备份
- 🚀 **自动转发** - 新备份的文件自动转发到群聊
- 📜 **备份历史** - 记录所有备份操作，方便追溯
- 🔢 **序号操作** - 通过序号快速操作文件，方便快捷
- 🔄 **自动清理** - 自动清理过期备份文件
- 🛡️ **权限控制** - 可限制只有指定用户能使用

## 📁 支持的文件类型

| 类型 | 格式 | 转发方式 |
|------|------|----------|
| 🖼️ 图片 | png, jpg, jpeg, webp, gif, bmp | 直接发送图片 |
| 🎬 视频 | mp4, avi, mov, mkv | 作为视频发送 |
| 🔊 音频 | mp3, wav, ogg, aac, flac | 作为语音发送 |
| 📄 文档 | pdf, doc, docx, txt 等 | 作为文件发送 |

## 🚀 快速开始

### 1. 安装插件

将 `backup_storage` 文件夹复制到AstrBot的插件目录：

```
AstrBot插件目录/backup_storage/
├── main.py              # 主代码文件
├── metadata.yaml        # 插件元数据
├── _conf_schema.json    # 配置架构
└── README.md            # 使用说明
```

### 2. 配置插件

在AstrBot管理界面中配置以下参数：

#### 基础配置

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| `backup_dir` | 备份文件存储目录 | ./backup-storage |
| `max_file_size_mb` | 单个文件最大大小（MB） | 100 |
| `auto_cleanup_days` | 自动清理天数（0=不清理） | 30 |
| `allowed_users` | 允许使用的用户ID列表 | 全部用户 |
| `keep_backup_history` | 保留备份历史天数 | 7 |

#### 高级配置

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| `enable_timed_backup` | 启用定时备份 | false |
| `timed_backup_interval_minutes` | 定时备份间隔（分钟） | 30 |
| `monitor_paths` | 监控路径列表（多个路径用换行分隔） | [] |
| `monitor_file_types` | 监控文件类型（如 mp4,jpg,png） | [] |
| `enable_auto_forward` | 启用自动转发 | false |
| `auto_forward_delay_seconds` | 自动转发延迟（秒） | 10 |

### 3. 使用命令

#### 手动备份
```
/备份文件 [文件路径] [自定义名称?]
```

示例：
```
/备份文件 ./my_video.mp4
/备份文件 ./photo.jpg 我的照片
```

#### 查看备份
```
/查看备份
```

#### 删除备份（使用序号）
```
/删除备份 [序号]
```

示例：
```
/删除备份 1
/删除备份 3
```

#### 转发备份（使用序号）
```
/转发备份 [序号]
```

示例：
```
/转发备份 1
/转发备份 2
```

#### 查看备份历史
```
/备份历史 [条数?]
```

示例：
```
/备份历史
/备份历史 20
```

#### 查看备份状态
```
/备份状态
```

## ⏰ 定时备份功能

### 功能说明

定时备份功能可以按设定的时间间隔自动扫描配置的监控目录，并将新文件备份到备份目录。

### 配置步骤

1. **启用定时备份**：在配置中设置 `enable_timed_backup = true`

2. **设置备份间隔**：配置 `timed_backup_interval_minutes`（最小5分钟）
   ```json
   {
       "timed_backup_interval_minutes": 30
   }
   ```

3. **配置监控路径**：添加要监控的源路径
   ```json
   {
       "monitor_paths": [
           "C:/Users/Admin/Videos",
           "C:/Users/Admin/Downloads",
           "D:/MyPhotos"
       ]
   }
   ```

4. **（可选）限制文件类型**：只备份特定类型的文件
   ```json
   {
       "monitor_file_types": ["mp4", "jpg", "png", "pdf"]
   }
   ```

### 工作原理

```
时间线：
[备份1] --间隔30分钟--> [备份2] --间隔30分钟--> [备份3] --间隔30分钟--> [备份4]

每次备份：
1. 扫描配置的监控路径
2. 检测新文件（通过文件哈希判断）
3. 备份新文件到备份目录
4. 记录备份历史
```

### 示例场景

**场景：自动备份下载目录**

配置：
```json
{
    "enable_timed_backup": true,
    "timed_backup_interval_minutes": 15,
    "monitor_paths": [
        "C:/Users/Admin/Downloads"
    ],
    "monitor_file_types": ["mp4", "jpg", "png"]
}
```

效果：
- 每15分钟自动扫描 `C:/Users/Admin/Downloads`
- 只备份 mp4、jpg、png 格式的新文件
- 避免重复备份同一文件（通过哈希判断）

## 📁 多路径监控

### 功能说明

支持同时监控多个目录，插件会定期扫描所有配置的路径并备份新文件。

### 配置示例

```json
{
    "monitor_paths": [
        "C:/Users/Admin/Videos",
        "C:/Users/Admin/Photos/2024",
        "D:/Work/Documents",
        "E:/备份/重要文件"
    ]
}
```

### 路径类型支持

- **单个文件**：直接备份该文件
- **目录**：递归扫描目录下的所有文件
- **相对路径**：相对于AstrBot运行目录
- **绝对路径**：使用完整路径

## 🚀 自动转发功能

### 功能说明

启用自动转发后，新备份的文件会在延迟后自动发送到群聊。

### 配置步骤

1. **启用自动转发**：设置 `enable_auto_forward = true`

2. **设置转发延迟**：配置 `auto_forward_delay_seconds`（给用户留出取消时间）
   ```json
   {
       "enable_auto_forward": true,
       "auto_forward_delay_seconds": 10
   }
   ```

### 工作流程

```
新文件检测
    ↓
备份到目录
    ↓
延迟等待（可取消）
    ↓
自动转发到群聊
    ↓
发送成功通知
```

### 示例配置

```json
{
    "enable_timed_backup": true,
    "timed_backup_interval_minutes": 10,
    "monitor_paths": [
        "C:/Users/Admin/Downloads"
    ],
    "enable_auto_forward": true,
    "auto_forward_delay_seconds": 15
}
```

效果：
- 每10分钟扫描下载目录
- 新文件自动备份
- 备份后等待15秒
- 自动转发到群聊

## 📜 备份历史

### 功能说明

插件会记录所有备份操作，包括手动备份和自动备份，方便追溯。

### 查看历史

```
/备份历史 10
```

示例输出：
```
📜 备份历史记录：

1. ✋ 手动
   📁 video_20260513_143052_abc12345.mp4
   📂 来源：C:/Users/Admin/Videos/test.mp4
   🕐 05-13 14:30

2. 🔄 自动
   📁 photo_20260513_143000_def67890.jpg
   📂 来源：C:/Users/Admin/Downloads/photo.jpg
   🕐 05-13 14:30

📊 共 2 条记录
```

### 历史记录内容

- **备份时间**：精确到分钟
- **备份类型**：🔄 自动 / ✋ 手动
- **文件名**：备份后的文件名
- **来源路径**：原始文件路径

## 🔧 配置示例

### 场景1：基础手动备份

```json
{
    "backup_dir": "./backup-storage",
    "max_file_size_mb": 100,
    "auto_cleanup_days": 30
}
```

### 场景2：定时备份 + 自动转发

```json
{
    "backup_dir": "./backup-storage",
    "max_file_size_mb": 100,
    "auto_cleanup_days": 30,
    "enable_timed_backup": true,
    "timed_backup_interval_minutes": 15,
    "monitor_paths": [
        "C:/Users/Admin/Downloads",
        "C:/Users/Admin/Videos"
    ],
    "monitor_file_types": ["mp4", "jpg", "png"],
    "enable_auto_forward": true,
    "auto_forward_delay_seconds": 10
}
```

### 场景3：多路径监控 + 限制文件类型

```json
{
    "backup_dir": "D:/MyBackups",
    "max_file_size_mb": 500,
    "auto_cleanup_days": 60,
    "enable_timed_backup": true,
    "timed_backup_interval_minutes": 30,
    "monitor_paths": [
        "C:/Users/Admin/Documents",
        "D:/Work/Projects",
        "E:/Archive"
    ],
    "monitor_file_types": ["pdf", "docx", "xlsx", "zip"],
    "enable_auto_forward": false
}
```

## 💡 使用场景

### 场景1：手动备份重要文件

```
用户: /备份文件 ./my_video.mp4

机器人: ✅ 文件备份成功！

       📁 原文件名：my_video.mp4
       📦 保存文件名：my_video_20260513_143052_abc12345.mp4
       💾 文件大小：25.32 MB
       🔢 文件序号：1
```

### 场景2：定时备份下载目录

**配置：**
```json
{
    "enable_timed_backup": true,
    "timed_backup_interval_minutes": 10,
    "monitor_paths": ["C:/Users/Admin/Downloads"],
    "monitor_file_types": ["mp4", "jpg"]
}
```

**效果：**
- 每10分钟自动扫描下载目录
- 新下载的 mp4、jpg 文件自动备份
- 避免重复备份同一文件

### 场景3：自动转发新备份到群聊

```
机器人: ⏰ 定时备份完成

       🔄 自动备份了 2 个新文件：
       1. 🎬 video_20260513_143052_abc12345.mp4
       2. 🖼️ photo_20260513_143050_def67890.jpg

       🚀 将在 10 秒后自动转发到群聊...
       💡 如需取消，请输入 /取消转发
```

### 场景4：使用序号快速操作

```
用户: /查看备份

机器人: 📂 备份文件列表：

       1. 🎬 video_20260513_143052_abc12345.mp4
          大小：25.32 MB | 时间：今天
       2. 🖼️ photo_20260513_143050_def67890.jpg
          大小：3.15 MB | 时间：今天
       3. 🔊 audio_20260512_120000_ghi11111.mp3
          大小：1.28 MB | 时间：昨天

       📊 共 3 个文件，总计 29.75 MB

       💡 使用 /删除备份 [序号] 或 /转发备份 [序号] 操作文件

用户: /转发备份 1

机器人: ✅ 视频已发送！

       🔢 序号：1
       📁 文件名：video_20260513_143052_abc12345.mp4
```

### 场景5：查看备份状态

```
用户: /备份状态

机器人: 📊 备份状态：

       📂 备份目录：C:/Users/Admin/backup-storage
       📦 文件数量：5 个
       💾 总大小：128.45 MB
       ⏰ 定时备份：已启用（每 15 分钟）

       📁 监控路径：
          • C:/Users/Admin/Downloads
          • C:/Users/Admin/Videos

       🚀 自动转发：已启用（延迟 10 秒）

       📜 备份历史：12 条记录
```

## 📝 注意事项

1. **序号时效性**：序号基于当前文件列表，删除文件后序号会重新排列
2. **文件路径**：支持绝对路径和相对路径
3. **文件大小**：默认最大100MB，超过会被拒绝
4. **自动清理**：默认30天自动清理，可设置为0禁用
5. **备份目录**：会自动创建，不存在时会自动创建
6. **文件名**：自动生成带时间戳的唯一文件名，避免冲突
7. **定时间隔**：最小支持5分钟一次
8. **哈希去重**：通过文件哈希判断是否已备份，避免重复备份

## 🔧 故障排除

### Q: 定时备份没有执行？
A: 检查：
- 是否设置了 `enable_timed_backup = true`
- 是否配置了 `monitor_paths`
- 查看 AstrBot 日志中的 `[backup_storage]` 信息

### Q: 文件没有被自动备份？
A: 检查：
- 文件是否在监控路径中
- 文件类型是否在 `monitor_file_types` 中（如果配置了）
- 文件大小是否超过限制

### Q: 提示"无效序号"？
A: 检查：
- 序号是否在有效范围内（1 ~ 文件总数）
- 是否使用了阿拉伯数字（不是中文数字）
- 先使用 /查看备份 查看当前文件列表

### Q: 自动转发失败？
A: 检查：
- 文件是否存在于备份目录
- 文件大小是否超过平台限制
- 网络连接是否正常

## 📄 许可证

本插件采用 MIT 许可证。

## 🤝 贡献

欢迎提交Issue和Pull Request！

## 📞 支持

如有问题，请查看AstrBot官方文档或联系插件作者。