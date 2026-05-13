import os
import shutil
import hashlib
import time
import json
import asyncio
from pathlib import Path
from typing import Optional, List, Dict, Any
from datetime import datetime

import astrbot.api.star as star
from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter as astrbot_filter
import astrbot.api.message_components as Comp


class Main(star.Star):
    """
    本地文件备份储存插件
    支持备份文件到本地并可直接转发到群聊
    支持定时备份、多路径监控、自动转发
    """

    def __init__(self, context: star.Context, config=None) -> None:
        self.context = context
        self.config = config or {}
        backup_dir = self.config.get("backup_dir", "./backup-storage")
        self.backup_dir = Path(backup_dir).resolve()
        self.max_file_size = self.config.get("max_file_size_mb", 100) * 1024 * 1024

        self.enable_timed_backup = self.config.get("enable_timed_backup", False)
        self.timed_backup_interval = max(5, self.config.get("timed_backup_interval_minutes", 30))
        self.monitor_paths = self.config.get("monitor_paths", [])
        self.monitor_file_types = self.config.get("monitor_file_types", [])
        self.enable_auto_forward = self.config.get("enable_auto_forward", False)
        self.auto_forward_target_type = self.config.get("auto_forward_target_type", "group")
        self.auto_forward_group_ids = self.config.get("auto_forward_group_ids", [])
        self.auto_forward_user_ids = self.config.get("auto_forward_user_ids", [])
        self.auto_forward_delay = self.config.get("auto_forward_delay_seconds", 10)
        self.keep_backup_history_days = self.config.get("keep_backup_history", 7)

        self.backup_history_file = self.backup_dir / ".backup_history.json"
        self.file_hash_file = self.backup_dir / ".file_hashes.json"
        self._backup_history: List[Dict[str, Any]] = []
        self._file_hashes: Dict[str, str] = {}
        self._last_backup_time = time.time()
        self._timed_task_running = False
        self._pending_forwards: List[Dict[str, Any]] = []

    def _check_user_permission(self, event: AstrMessageEvent) -> Optional[str]:
        """检查用户是否有权限使用插件"""
        allowed_users = self.config.get("allowed_users", [])
        if not allowed_users:
            return None

        user_id = self._get_user_id(event)
        if not user_id:
            logger.warning("[backup_storage] 无法获取用户ID，跳过权限检查")
            return None

        logger.info(f"[backup_storage] 当前用户ID: {user_id}, 允许列表: {allowed_users}")
        if str(user_id) not in [str(u) for u in allowed_users]:
            denied_messages = [
                "哎呀，这个功能目前只对特定小伙伴开放呢~想使用的话可以联系管理员开通权限哦",
                "抱歉呀，这个功能目前只对管理员开放，我暂时没法帮你解锁这个技能呢",
                "诶，这个功能需要特殊权限才能使用哦，你可以问问管理员能不能给你开个通行证",
            ]
            import random
            return random.choice(denied_messages)
        return None

    def _get_user_id(self, event: AstrMessageEvent) -> Optional[str]:
        """从AstrMessageEvent对象中获取用户ID"""
        try:
            if hasattr(event, 'message_obj') and event.message_obj:
                sender = event.message_obj.sender
                if hasattr(sender, 'user_id') and sender.user_id:
                    return str(sender.user_id)
                if hasattr(sender, 'id') and sender.id:
                    return str(sender.id)

            if hasattr(event, 'session_id'):
                parts = event.session_id.split('_')
                if len(parts) >= 2:
                    return parts[-1]

            if hasattr(event, 'user_id'):
                return str(event.user_id)

            if hasattr(event, 'sender'):
                sender = event.sender
                if isinstance(sender, dict):
                    return str(sender.get('user_id', sender.get('id', '')))
                if hasattr(sender, 'user_id'):
                    return str(sender.user_id)
                if hasattr(sender, 'id'):
                    return str(sender.id)

        except Exception as e:
            logger.error(f"[backup_storage] 获取用户ID失败: {e}")

        return None

    def _get_file_hash(self, file_path: str) -> str:
        """获取文件内容的MD5哈希"""
        hash_md5 = hashlib.md5()
        try:
            with open(file_path, "rb") as f:
                for chunk in iter(lambda: f.read(4096), b""):
                    hash_md5.update(chunk)
            return hash_md5.hexdigest()[:12]
        except Exception as e:
            logger.error(f"[backup_storage] 计算文件哈希失败: {e}")
            return str(int(time.time()))

    def _ensure_backup_dir(self):
        """确保备份目录存在"""
        self.backup_dir.mkdir(parents=True, exist_ok=True)

    def _load_backup_history(self):
        """加载备份历史记录"""
        try:
            if self.backup_history_file.exists():
                with open(self.backup_history_file, 'r', encoding='utf-8') as f:
                    self._backup_history = json.load(f)
        except Exception as e:
            logger.error(f"[backup_storage] 加载备份历史失败: {e}")
            self._backup_history = []

    def _save_backup_history(self):
        """保存备份历史记录"""
        try:
            self._cleanup_old_history()
            with open(self.backup_history_file, 'w', encoding='utf-8') as f:
                json.dump(self._backup_history[-100:], f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"[backup_storage] 保存备份历史失败: {e}")

    def _cleanup_old_history(self):
        """清理过期的历史记录"""
        if self.keep_backup_history_days <= 0:
            self._backup_history = []
            return

        cutoff_time = time.time() - (self.keep_backup_history_days * 86400)
        self._backup_history = [
            h for h in self._backup_history
            if h.get('timestamp', 0) >= cutoff_time
        ]

    def _load_file_hashes(self):
        """加载已备份文件的哈希记录"""
        try:
            if self.file_hash_file.exists():
                with open(self.file_hash_file, 'r', encoding='utf-8') as f:
                    self._file_hashes = json.load(f)
        except Exception as e:
            logger.error(f"[backup_storage] 加载文件哈希记录失败: {e}")
            self._file_hashes = {}

    def _save_file_hashes(self):
        """保存文件哈希记录"""
        try:
            with open(self.file_hash_file, 'w', encoding='utf-8') as f:
                json.dump(self._file_hashes, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"[backup_storage] 保存文件哈希记录失败: {e}")

    def _auto_cleanup(self):
        """自动清理过期文件"""
        auto_cleanup_days = self.config.get("auto_cleanup_days", 30)
        if auto_cleanup_days <= 0:
            return

        if not self.backup_dir.exists():
            return

        now = time.time()
        cutoff_time = now - (auto_cleanup_days * 86400)
        deleted_count = 0

        try:
            for file_path in self.backup_dir.iterdir():
                if file_path.is_file() and file_path.suffix not in ['.json']:
                    if file_path.stat().st_mtime < cutoff_time:
                        file_path.unlink()
                        deleted_count += 1
                        logger.info(f"[backup_storage] 已自动清理过期文件: {file_path.name}")

            if deleted_count > 0:
                logger.info(f"[backup_storage] 自动清理完成，删除了 {deleted_count} 个过期文件")
        except Exception as e:
            logger.error(f"[backup_storage] 自动清理失败: {e}")

    def _get_backup_files(self) -> List[Path]:
        """获取备份文件列表（按时间倒序）"""
        self._ensure_backup_dir()
        files = list(self.backup_dir.iterdir())
        files = [f for f in files if f.is_file() and f.suffix not in ['.json']]
        files.sort(key=lambda x: x.stat().st_mtime, reverse=True)
        return files

    def _get_file_type(self, file_path: Path) -> str:
        """获取文件类型"""
        suffix = file_path.suffix.lower()
        if suffix in ['.png', '.jpg', '.jpeg', '.webp', '.gif', '.bmp']:
            return 'image'
        elif suffix in ['.mp4', '.avi', '.mov', '.mkv']:
            return 'video'
        elif suffix in ['.mp3', '.wav', '.ogg', '.aac', '.flac']:
            return 'audio'
        else:
            return 'file'

    async def initialize(self):
        """初始化插件"""
        self._ensure_backup_dir()
        self._load_backup_history()
        self._load_file_hashes()
        self._auto_cleanup()

        logger.info("[backup_storage] 本地文件备份储存插件已初始化")

        if self.enable_timed_backup and self.monitor_paths:
            self._timed_task_running = True
            asyncio.create_task(self._timed_backup_task())
            logger.info(f"[backup_storage] 定时备份已启用，间隔 {self.timed_backup_interval} 分钟")

        if self.enable_auto_forward:
            logger.info(f"[backup_storage] 🚀 自动转发已启用")
            logger.info(f"[backup_storage]    备份延迟: {self.auto_forward_delay} 秒")
            logger.info(f"[backup_storage]    备份完成后文件将加入待转发队列")

    async def _timed_backup_task(self):
        """定时备份任务"""
        check_interval = 60
        while self._timed_task_running:
            try:
                current_time = time.time()
                next_backup_time = self._last_backup_time + (self.timed_backup_interval * 60)
                time_until_next = next_backup_time - current_time
                
                if time_until_next <= 0:
                    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    logger.info(f"[backup_storage] ═══════════════════════════════════════════")
                    logger.info(f"[backup_storage] ⏰ [{timestamp}] 定时备份开始执行...")
                    logger.info(f"[backup_storage] 📁 监控路径数量: {len(self.monitor_paths)}")
                    
                    backup_results = await self._scan_and_backup_monitor_paths()
                    
                    if backup_results:
                        logger.info(f"[backup_storage] ✅ 备份完成！共备份 {len(backup_results)} 个文件:")
                        for i, file_info in enumerate(backup_results, 1):
                            logger.info(f"[backup_storage]    {i}. {file_info['file_name']}")
                        
                        self._last_backup_time = current_time
                        
                        if self.enable_auto_forward:
                            logger.info(f"[backup_storage] 📋 正在将 {len(backup_results)} 个文件加入待转发队列...")
                            await asyncio.sleep(self.auto_forward_delay)
                            for file_info in backup_results:
                                self._queue_auto_forward(file_info)
                            logger.info(f"[backup_storage] ✅ 所有文件已加入待转发队列")
                        
                        next_time = datetime.fromtimestamp(self._last_backup_time + self.timed_backup_interval * 60)
                        logger.info(f"[backup_storage] 📅 下次备份时间: {next_time.strftime('%Y-%m-%d %H:%M:%S')}")
                    else:
                        logger.info(f"[backup_storage] ℹ️  本次扫描未发现新文件，跳过备份")
                        self._last_backup_time = current_time
                    logger.info(f"[backup_storage] ═══════════════════════════════════════════")
                await asyncio.sleep(check_interval)
            except Exception as e:
                logger.error(f"[backup_storage] 定时备份任务异常: {e}")
                await asyncio.sleep(check_interval)

    def _queue_auto_forward(self, file_info: Dict[str, Any]):
        """将文件加入待转发队列"""
        self._pending_forwards.append({
            'file_path': file_info['file_path'],
            'file_name': file_info['file_name'],
            'file_type': self._get_file_type(Path(file_info['file_path'])),
            'timestamp': time.time()
        })
        logger.info(f"[backup_storage] 已加入待转发队列: {file_info['file_name']}")

    async def _scan_and_backup_monitor_paths(self) -> List[Dict[str, Any]]:
        """扫描监控路径并备份新文件"""
        results = []

        if not self.monitor_paths:
            return results

        for monitor_path in self.monitor_paths:
            try:
                path = Path(monitor_path)
                if not path.exists():
                    logger.warning(f"[backup_storage] 监控路径不存在: {monitor_path}")
                    continue

                if path.is_file():
                    result = await self._backup_single_file(path)
                    if result:
                        results.append(result)
                else:
                    for file_path in path.rglob('*'):
                        if file_path.is_file():
                            result = await self._backup_single_file(file_path)
                            if result:
                                results.append(result)

            except Exception as e:
                logger.error(f"[backup_storage] 扫描路径失败 {monitor_path}: {e}")

        return results

    async def _backup_single_file(self, source_path: Path) -> Optional[Dict[str, Any]]:
        """备份单个文件（内部方法）"""
        try:
            if not source_path.exists():
                return None

            file_size = source_path.stat().st_size
            if file_size > self.max_file_size:
                logger.warning(f"[backup_storage] 文件太大，跳过: {source_path.name}")
                return None

            if self.monitor_file_types:
                if source_path.suffix.lower().lstrip('.') not in self.monitor_file_types:
                    return None

            file_hash = self._get_file_hash(str(source_path))

            if str(source_path) in self._file_hashes and self._file_hashes[str(source_path)] == file_hash:
                return None

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            dest_name = f"{source_path.stem}_{timestamp}_{file_hash[:8]}{source_path.suffix}"
            dest_path = self.backup_dir / dest_name

            shutil.copy2(str(source_path), str(dest_path))

            self._file_hashes[str(source_path)] = file_hash
            self._save_file_hashes()

            files = self._get_backup_files()
            file_index = next((i for i, f in enumerate(files, 1) if f.name == dest_name), len(files))

            history_entry = {
                'timestamp': time.time(),
                'source_path': str(source_path),
                'dest_name': dest_name,
                'file_size': file_size,
                'file_hash': file_hash,
                'index': file_index
            }
            self._backup_history.append(history_entry)
            self._save_backup_history()

            logger.info(f"[backup_storage] 自动备份: {source_path.name} -> {dest_name}")

            return {
                'file_path': str(dest_path),
                'file_name': dest_name,
                'index': file_index
            }

        except Exception as e:
            logger.error(f"[backup_storage] 自动备份文件失败: {e}")
            return None

    async def check_pending_forwards(self, event: AstrMessageEvent):
        """检查待转发的文件队列并在当前群聊/用户发送"""
        if not self._pending_forwards:
            return

        pending = self._pending_forwards.copy()
        self._pending_forwards.clear()

        for forward_info in pending:
            try:
                file_path = Path(forward_info['file_path'])
                if not file_path.exists():
                    logger.warning(f"[backup_storage] 待转发文件不存在: {forward_info['file_name']}")
                    continue

                file_type = forward_info['file_type']
                logger.info(f"[backup_storage] 自动转发 {file_type}: {forward_info['file_name']}")

                if file_type == 'image':
                    yield event.image_result(str(file_path))
                    yield event.plain_result(f"🚀 自动转发 {forward_info['file_name']}")
                elif file_type == 'video':
                    yield event.chain_result([Comp.Video.fromFileSystem(str(file_path))])
                    yield event.plain_result(f"🚀 自动转发 {forward_info['file_name']}")
                elif file_type == 'audio':
                    yield event.chain_result([Comp.Record(file=str(file_path), url=str(file_path))])
                    yield event.plain_result(f"🚀 自动转发 {forward_info['file_name']}")
                else:
                    yield event.chain_result([Comp.File.fromFileSystem(str(file_path))])
                    yield event.plain_result(f"🚀 自动转发 {forward_info['file_name']}")

            except Exception as e:
                logger.error(f"[backup_storage] 自动转发失败: {e}")

    async def backup_file(self, event: AstrMessageEvent, file_path: str, custom_name: str = "") -> str:
        """备份文件工具。将文件保存到本地备份目录。

        Args:
            file_path(string): 要备份的文件路径
            custom_name(string): 自定义文件名

        Returns:
            str: 备份结果
        """
        denied_msg = self._check_user_permission(event)
        if denied_msg:
            return denied_msg

        self._ensure_backup_dir()

        try:
            source_path = Path(file_path)

            if not source_path.exists():
                return f"❌ 文件不存在：{file_path}"

            file_size = source_path.stat().st_size
            if file_size > self.max_file_size:
                return f"❌ 文件太大：{source_path.name} ({file_size / (1024*1024):.2f} MB)，最大支持 {self.max_file_size / (1024*1024):.0f} MB"

            if custom_name:
                dest_name = custom_name
            else:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                file_hash = self._get_file_hash(str(source_path))
                suffix = source_path.suffix
                dest_name = f"{source_path.stem}_{timestamp}_{file_hash[:8]}{suffix}"

            dest_path = self.backup_dir / dest_name

            shutil.copy2(str(source_path), str(dest_path))

            files = self._get_backup_files()
            file_index = next((i for i, f in enumerate(files, 1) if f.name == dest_name), len(files))

            self._file_hashes[str(source_path)] = self._get_file_hash(str(source_path))
            self._save_file_hashes()

            history_entry = {
                'timestamp': time.time(),
                'source_path': str(source_path),
                'dest_name': dest_name,
                'file_size': file_size,
                'manual': True
            }
            self._backup_history.append(history_entry)
            self._save_backup_history()

            logger.info(f"[backup_storage] 文件已备份: {source_path.name} -> {dest_name}")

            return (f"✅ 文件备份成功！\n\n"
                    f"📁 原文件名：{source_path.name}\n"
                    f"📦 保存文件名：{dest_name}\n"
                    f"💾 文件大小：{self._format_size(file_size)}\n"
                    f"🔢 文件序号：{file_index}")

        except Exception as e:
            logger.error(f"[backup_storage] 备份文件失败: {e}")
            return f"❌ 备份文件失败：{str(e)}"

    def _format_size(self, size: int) -> str:
        """格式化文件大小"""
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size < 1024:
                return f"{size:.2f} {unit}"
            size /= 1024
        return f"{size:.2f} TB"

    async def list_backup_files(self, event: AstrMessageEvent) -> str:
        """查看备份文件列表

        Returns:
            str: 文件列表
        """
        denied_msg = self._check_user_permission(event)
        if denied_msg:
            return denied_msg

        files = self._get_backup_files()

        if not files:
            return "📂 备份目录为空，还没有备份任何文件哦～"

        lines = ["📂 备份文件列表：\n"]

        for i, file_path in enumerate(files[:20], 1):
            size = file_path.stat().st_size
            mtime = datetime.fromtimestamp(file_path.stat().st_mtime)
            age_days = (time.time() - file_path.stat().st_mtime) / 86400

            icon = "🖼️"
            suffix = file_path.suffix.lower()
            if suffix in ['.mp4', '.avi', '.mov', '.mkv']:
                icon = "🎬"
            elif suffix in ['.mp3', '.wav', '.ogg', '.aac']:
                icon = "🔊"
            elif suffix in ['.pdf', '.doc', '.docx', '.txt']:
                icon = "📄"
            elif suffix in ['.zip', '.rar', '.7z']:
                icon = "📦"

            age_str = ""
            if age_days < 1:
                age_str = "今天"
            elif age_days < 7:
                age_str = f"{int(age_days)}天前"
            else:
                age_str = mtime.strftime("%m-%d")

            lines.append(f"{i}. {icon} {file_path.name}")
            lines.append(f"   大小：{self._format_size(size)} | 时间：{age_str}")

        total_size = sum(f.stat().st_size for f in files)
        lines.append(f"\n📊 共 {len(files)} 个文件，总计 {self._format_size(total_size)}")

        if self._pending_forwards:
            lines.append(f"\n🚀 待转发文件：{len(self._pending_forwards)} 个")
            lines.append(f"💡 使用 /查看待转发 查看队列")

        lines.append(f"\n💡 使用 /删除备份 [序号] 或 /转发备份 [序号] 操作文件")

        return "\n".join(lines)

    async def delete_backup_file(self, event: AstrMessageEvent, index: int) -> str:
        """删除备份文件

        Args:
            index(int): 要删除的文件序号

        Returns:
            str: 删除结果
        """
        denied_msg = self._check_user_permission(event)
        if denied_msg:
            return denied_msg

        files = self._get_backup_files()

        if not files:
            return "📂 备份目录为空，没有可删除的文件哦～"

        if index < 1 or index > len(files):
            return f"❌ 无效序号：{index}，有效范围是 1 ~ {len(files)}\n\n请先使用 /查看备份 查看文件列表"

        file_path = files[index - 1]
        file_name = file_path.name
        file_size = file_path.stat().st_size

        try:
            file_path.unlink()
            logger.info(f"[backup_storage] 已删除备份文件: {file_name}")

            for source_path in list(self._file_hashes.keys()):
                if self._file_hashes[source_path] == self._get_file_hash(str(file_path)):
                    del self._file_hashes[source_path]
                    self._save_file_hashes()
                    break

            return (f"🗑️ 备份文件已删除！\n\n"
                    f"🔢 序号：{index}\n"
                    f"📁 文件名：{file_name}\n"
                    f"💾 文件大小：{self._format_size(file_size)}")

        except Exception as e:
            logger.error(f"[backup_storage] 删除备份文件失败: {e}")
            return f"❌ 删除备份文件失败：{str(e)}"

    async def forward_backup_file(self, event: AstrMessageEvent, index: int):
        """转发备份文件。将备份的文件直接发送到群聊。

        Args:
            index(int): 要转发的文件序号
        """
        denied_msg = self._check_user_permission(event)
        if denied_msg:
            yield event.plain_result(denied_msg)
            return

        files = self._get_backup_files()

        if not files:
            yield event.plain_result("📂 备份目录为空，没有可转发的文件哦～")
            return

        if index < 1 or index > len(files):
            yield event.plain_result(f"❌ 无效序号：{index}，有效范围是 1 ~ {len(files)}\n\n请先使用 /查看备份 查看文件列表")
            return

        file_path = files[index - 1]
        file_name = file_path.name

        try:
            suffix = file_path.suffix.lower()

            if suffix in ['.png', '.jpg', '.jpeg', '.webp', '.gif', '.bmp']:
                yield event.image_result(str(file_path))
                yield event.plain_result(f"✅ 图片已发送！\n\n🔢 序号：{index}\n📁 文件名：{file_name}")
                return

            elif suffix in ['.mp4', '.avi', '.mov', '.mkv']:
                yield event.chain_result([Comp.Video.fromFileSystem(str(file_path))])
                yield event.plain_result(f"✅ 视频已发送！\n\n🔢 序号：{index}\n📁 文件名：{file_name}")
                return

            elif suffix in ['.mp3', '.wav', '.ogg', '.aac', '.flac']:
                yield event.chain_result([Comp.Record(file=str(file_path), url=str(file_path))])
                yield event.plain_result(f"✅ 音频已发送！\n\n🔢 序号：{index}\n📁 文件名：{file_name}")
                return

            else:
                yield event.chain_result([Comp.File.fromFileSystem(str(file_path))])
                yield event.plain_result(f"✅ 文件已发送！\n\n🔢 序号：{index}\n📁 文件名：{file_name}")
                return

        except Exception as e:
            logger.error(f"[backup_storage] 转发备份文件失败: {e}")
            yield event.plain_result(f"❌ 转发备份文件失败：{str(e)}")
            return

    async def show_pending_forwards(self, event: AstrMessageEvent) -> str:
        """查看待转发的文件列表"""
        denied_msg = self._check_user_permission(event)
        if denied_msg:
            return denied_msg

        if not self._pending_forwards:
            return "📋 待转发队列为空，没有待转发的文件～"

        lines = ["📋 待转发文件队列：\n"]

        for i, forward_info in enumerate(self._pending_forwards, 1):
            timestamp = datetime.fromtimestamp(forward_info.get('timestamp', 0))
            lines.append(f"{i}. {forward_info['file_type'].upper()} {forward_info['file_name']}")
            lines.append(f"   🕐 加入时间：{timestamp.strftime('%H:%M:%S')}")

        lines.append(f"\n💡 使用 /执行转发 将队列中的文件发送到当前群聊")

        return "\n".join(lines)

    async def execute_pending_forwards(self, event: AstrMessageEvent):
        """执行待转发的文件队列"""
        denied_msg = self._check_user_permission(event)
        if denied_msg:
            yield event.plain_result(denied_msg)
            return

        if not self._pending_forwards:
            yield event.plain_result("📋 待转发队列为空，没有需要转发的文件～")
            return

        yield event.plain_result(f"🚀 开始转发 {len(self._pending_forwards)} 个文件...")

        async for result in self.check_pending_forwards(event):
            yield result

        yield event.plain_result("✅ 转发完成！")

    async def show_backup_history(self, event: AstrMessageEvent, limit: int = 10) -> str:
        """查看备份历史

        Args:
            limit(int): 显示条数

        Returns:
            str: 历史记录
        """
        denied_msg = self._check_user_permission(event)
        if denied_msg:
            return denied_msg

        if not self._backup_history:
            return "📜 暂无备份历史记录～"

        entries = self._backup_history[-limit:][::-1]

        lines = ["📜 备份历史记录：\n"]

        for i, entry in enumerate(entries, 1):
            timestamp = datetime.fromtimestamp(entry.get('timestamp', 0))
            source_path = entry.get('source_path', '')
            dest_name = entry.get('dest_name', '')
            manual = entry.get('manual', False)

            is_auto = "🔄 自动" if not manual else "✋ 手动"

            lines.append(f"{i}. {is_auto}")
            lines.append(f"   📁 {dest_name}")
            lines.append(f"   📂 来源：{source_path}")
            lines.append(f"   🕐 {timestamp.strftime('%m-%d %H:%M')}")

        lines.append(f"\n📊 共 {len(self._backup_history)} 条记录")

        return "\n".join(lines)

    async def show_backup_status(self, event: AstrMessageEvent) -> str:
        """查看备份状态

        Returns:
            str: 状态信息
        """
        denied_msg = self._check_user_permission(event)
        if denied_msg:
            return denied_msg

        files = self._get_backup_files()
        total_size = sum(f.stat().st_size for f in files)

        lines = ["📊 备份状态：\n"]
        lines.append(f"📂 备份目录：{self.backup_dir}")
        lines.append(f"📦 文件数量：{len(files)} 个")
        lines.append(f"💾 总大小：{self._format_size(total_size)}")

        if self.enable_timed_backup:
            lines.append(f"⏰ 定时备份：已启用（每 {self.timed_backup_interval} 分钟）")
        else:
            lines.append(f"⏰ 定时备份：未启用")

        if self.monitor_paths:
            lines.append(f"\n📁 监控路径：")
            for path in self.monitor_paths:
                lines.append(f"   • {path}")
        else:
            lines.append(f"\n📁 监控路径：未配置")

        if self.enable_auto_forward:
            lines.append(f"\n🚀 自动转发：已启用")
            lines.append(f"   目标类型：{self.auto_forward_target_type}")
            lines.append(f"   延迟：{self.auto_forward_delay} 秒")
        else:
            lines.append(f"\n🚀 自动转发：未启用")

        if self._pending_forwards:
            lines.append(f"\n📋 待转发队列：{len(self._pending_forwards)} 个文件")
            lines.append(f"💡 使用 /执行转发 将文件发送到当前群聊")

        lines.append(f"\n📜 备份历史：{len(self._backup_history)} 条记录")

        return "\n".join(lines)

    @astrbot_filter.command("备份文件")
    async def cmd_backup_file(self, event: AstrMessageEvent, file_path: str, custom_name: str = ""):
        """备份文件命令"""
        result = await self.backup_file(event, file_path, custom_name)
        yield event.plain_result(result)

    @astrbot_filter.command("查看备份")
    async def cmd_list_backup_files(self, event: AstrMessageEvent):
        """查看备份文件列表命令"""
        result = await self.list_backup_files(event)
        yield event.plain_result(result)

    @astrbot_filter.command("删除备份")
    async def cmd_delete_backup_file(self, event: AstrMessageEvent, index: int):
        """删除备份文件命令"""
        result = await self.delete_backup_file(event, index)
        yield event.plain_result(result)

    @astrbot_filter.command("转发备份")
    async def cmd_forward_backup_file(self, event: AstrMessageEvent, index: int):
        """转发备份文件命令"""
        async for result in self.forward_backup_file(event, index):
            yield result

    @astrbot_filter.command("查看待转发")
    async def cmd_show_pending_forwards(self, event: AstrMessageEvent):
        """查看待转发文件队列命令"""
        result = await self.show_pending_forwards(event)
        yield event.plain_result(result)

    @astrbot_filter.command("执行转发")
    async def cmd_execute_pending_forwards(self, event: AstrMessageEvent):
        """执行待转发队列命令"""
        async for result in self.execute_pending_forwards(event):
            yield result

    @astrbot_filter.command("备份历史")
    async def cmd_show_backup_history(self, event: AstrMessageEvent, limit: int = 10):
        """查看备份历史命令"""
        result = await self.show_backup_history(event, limit)
        yield event.plain_result(result)

    @astrbot_filter.command("备份状态")
    async def cmd_show_backup_status(self, event: AstrMessageEvent):
        """查看备份状态命令"""
        result = await self.show_backup_status(event)
        yield event.plain_result(result)