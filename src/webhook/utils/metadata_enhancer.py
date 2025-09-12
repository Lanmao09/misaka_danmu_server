"""
安全的元数据增强器 - 具有完善的错误处理和回退机制
"""

import logging
import asyncio
import httpx
from typing import Optional, Dict, Any
from urllib.parse import urljoin
import os

logger = logging.getLogger(__name__)


class SafeMetadataEnhancer:
    """安全的元数据增强器"""

    def __init__(self):
        self.emby_url = os.getenv("EMBY_SERVER_URL")
        self.emby_api_key = os.getenv("EMBY_API_KEY")
        self.session = None
        self.user_id = None
        self.enabled = bool(self.emby_url)

        if self.enabled:
            logger.info(f"元数据增强器已启用 - Emby服务器: {self.emby_url}")
        else:
            logger.info("元数据增强器已禁用 - 未配置EMBY_SERVER_URL")
    
    async def _get_session(self) -> Optional[httpx.AsyncClient]:
        """获取HTTP会话"""
        if not self.enabled:
            return None

        if self.session is None or self.session.is_closed:
            timeout = httpx.Timeout(5.0)  # 短超时
            self.session = httpx.AsyncClient(timeout=timeout)
        return self.session

    async def _get_user_id(self) -> Optional[str]:
        """获取用户ID（缓存）"""
        if self.user_id:
            return self.user_id

        session = await self._get_session()
        if not session:
            return None

        try:
            url = self._build_url("Users")
            response = await session.get(url)
            if response.status_code == 200:
                users = response.json()
                if users:
                    # 优先选择管理员用户
                    for user in users:
                        if user.get("Policy", {}).get("IsAdministrator", False):
                            self.user_id = user["Id"]
                            logger.debug(f"选择管理员用户: {user.get('Name')} (ID: {self.user_id})")
                            return self.user_id

                    # 如果没有管理员，选择第一个用户
                    self.user_id = users[0]["Id"]
                    logger.debug(f"选择第一个用户: {users[0].get('Name')} (ID: {self.user_id})")
                    return self.user_id
            else:
                logger.warning(f"获取用户列表失败，状态码: {response.status_code}")
                return None
        except Exception as e:
            logger.warning(f"获取用户ID失败: {e}")
            return None
    
    async def enhance_metadata(self, item_id: str, series_id: Optional[str] = None) -> Dict[str, Optional[str]]:
        """
        安全地增强元数据
        
        Args:
            item_id: 媒体项ID
            series_id: 电视剧系列ID（可选）
            
        Returns:
            增强的元数据字典，失败时返回空值
        """
        # 默认返回值
        default_metadata = {
            "tmdb_id": None,
            "imdb_id": None,
            "tvdb_id": None,
            "douban_id": None,
            "bangumi_id": None
        }
        
        if not self.enabled:
            logger.debug("元数据增强器未启用，返回默认值")
            return default_metadata
        
        try:
            # 智能元数据获取策略：同时尝试获取系列和媒体项元数据，然后合并
            series_metadata = None
            item_metadata = None

            # 1. 尝试获取系列元数据（优先，包含完整的 TMDB ID 等）
            if series_id:
                logger.debug(f"获取系列 {series_id} 的元数据")
                series_metadata = await self._fetch_item_metadata(series_id)
                if series_metadata and any(series_metadata.values()):
                    logger.info(f"成功获取系列 {series_id} 的元数据: {self._summarize_metadata(series_metadata)}")

            # 2. 尝试获取媒体项元数据（可能包含特定的 Episode ID）
            logger.debug(f"获取媒体项 {item_id} 的元数据")
            item_metadata = await self._fetch_item_metadata(item_id)
            if item_metadata and any(item_metadata.values()):
                logger.info(f"成功获取媒体项 {item_id} 的元数据: {self._summarize_metadata(item_metadata)}")

            # 3. 智能合并元数据（系列优先，媒体项补充）
            merged_metadata = self._merge_metadata(series_metadata, item_metadata)

            if any(merged_metadata.values()):
                logger.info(f"合并后的增强元数据: {self._summarize_metadata(merged_metadata)}")
                return merged_metadata
            else:
                logger.warning(f"无法获取 {item_id} 和系列 {series_id} 的有效元数据")
                return default_metadata
            
        except Exception as e:
            logger.warning(f"获取增强元数据时出错: {e}，使用默认值")
            return default_metadata
    
    async def _fetch_item_metadata(self, item_id: str) -> Optional[Dict[str, Optional[str]]]:
        """获取单个媒体项的元数据"""
        session = await self._get_session()
        if not session:
            return None

        user_id = await self._get_user_id()
        if not user_id:
            logger.warning("无法获取用户ID，跳过元数据获取")
            return None

        try:
            # 使用用户上下文的端点格式
            url = self._build_url(f"Users/{user_id}/Items/{item_id}")

            response = await session.get(url)
            if response.status_code == 200:
                data = response.json()
                logger.debug(f"成功获取媒体项 {item_id} 的元数据")
                return self._extract_metadata_ids(data)
            else:
                logger.warning(f"Emby API 返回状态码 {response.status_code} (用户上下文)")
                return None

        except httpx.TimeoutException:
            logger.warning(f"获取媒体项 {item_id} 元数据超时")
            return None
        except Exception as e:
            logger.warning(f"获取媒体项 {item_id} 元数据失败: {e}")
            return None
    
    def _build_url(self, endpoint: str) -> str:
        """构建API URL"""
        url = urljoin(self.emby_url, f"/emby/{endpoint}")
        if self.emby_api_key:
            separator = "&" if "?" in url else "?"
            url += f"{separator}api_key={self.emby_api_key}"
        return url
    
    def _extract_metadata_ids(self, item_data: Dict[str, Any]) -> Dict[str, Optional[str]]:
        """从Emby数据中提取元数据ID"""
        provider_ids = item_data.get("ProviderIds", {})
        
        metadata_ids = {
            "tmdb_id": None,
            "imdb_id": None,
            "tvdb_id": None,
            "douban_id": None,
            "bangumi_id": None
        }
        
        # 提取各种ID，支持多种字段名变体
        id_mappings = [
            (["Tmdb", "TheMovieDb", "TMDB"], "tmdb_id"),
            (["Imdb", "IMDB", "IMDb"], "imdb_id"),
            (["Tvdb", "TheTVDB", "TVDB"], "tvdb_id"),
            (["DoubanID", "Douban", "douban"], "douban_id"),
            (["Bangumi", "bangumi", "BangumiID"], "bangumi_id")
        ]
        
        for field_names, target_key in id_mappings:
            for field_name in field_names:
                if field_name in provider_ids and provider_ids[field_name]:
                    metadata_ids[target_key] = str(provider_ids[field_name])
                    break
        
        # 记录找到的ID
        found_ids = {k: v for k, v in metadata_ids.items() if v is not None}
        if found_ids:
            logger.debug(f"提取到元数据ID: {found_ids}")
        
        return metadata_ids
    
    async def close(self):
        """关闭资源"""
        if self.session and not self.session.is_closed:
            await self.session.aclose()
    
    def get_metadata_summary(self, metadata: Dict[str, Optional[str]]) -> str:
        """获取元数据摘要"""
        return self._summarize_metadata(metadata)

    def _summarize_metadata(self, metadata: Optional[Dict[str, Optional[str]]]) -> str:
        """内部方法：获取元数据摘要"""
        if not metadata:
            return "无元数据"
        ids = []
        for key, value in metadata.items():
            if value:
                name = key.replace("_id", "").upper()
                ids.append(f"{name}:{value}")
        return ", ".join(ids) if ids else "无有效元数据"

    def _merge_metadata(self, series_metadata: Optional[Dict[str, Optional[str]]],
                       item_metadata: Optional[Dict[str, Optional[str]]]) -> Dict[str, Optional[str]]:
        """智能合并元数据：系列优先，媒体项补充"""
        merged = {
            "tmdb_id": None,
            "imdb_id": None,
            "tvdb_id": None,
            "douban_id": None,
            "bangumi_id": None
        }

        # 首先使用媒体项元数据作为基础
        if item_metadata:
            for key, value in item_metadata.items():
                if value:
                    merged[key] = value

        # 然后用系列元数据覆盖（系列优先，因为包含完整的 TMDB ID 等）
        if series_metadata:
            for key, value in series_metadata.items():
                if value:
                    merged[key] = value

        return merged


# 全局实例
_metadata_enhancer = None


def get_metadata_enhancer() -> SafeMetadataEnhancer:
    """获取全局元数据增强器实例"""
    global _metadata_enhancer
    if _metadata_enhancer is None:
        _metadata_enhancer = SafeMetadataEnhancer()
    return _metadata_enhancer


async def enhance_webhook_metadata(item_id: str, series_id: Optional[str] = None,
                                  webhook_data: Optional[Dict[str, Any]] = None) -> Dict[str, Optional[str]]:
    """
    便捷函数：增强webhook元数据

    这个函数提供了一个简单的接口来获取增强元数据，
    具有完善的错误处理，永远不会导致webhook失败。

    Args:
        item_id: 媒体项ID
        series_id: 系列ID（可选）
        webhook_data: Webhook原始数据（可选，作为备用数据源）
    """
    enhancer = get_metadata_enhancer()

    # 首先尝试从 Emby API 获取增强元数据
    enhanced_metadata = await enhancer.enhance_metadata(item_id, series_id)

    # 如果 API 获取失败且有 Webhook 原始数据，尝试从中提取
    if not any(enhanced_metadata.values()) and webhook_data:
        logger.info("API 获取失败，尝试从 Webhook 数据中提取元数据")
        webhook_metadata = _extract_metadata_from_webhook(webhook_data)
        if any(webhook_metadata.values()):
            logger.info(f"从 Webhook 数据提取到元数据: {enhancer._summarize_metadata(webhook_metadata)}")
            return webhook_metadata

    return enhanced_metadata


def _extract_metadata_from_webhook(webhook_data: Dict[str, Any]) -> Dict[str, Optional[str]]:
    """从 Webhook 原始数据中提取元数据"""
    metadata = {
        "tmdb_id": None,
        "imdb_id": None,
        "tvdb_id": None,
        "douban_id": None,
        "bangumi_id": None
    }

    # 从 Item 中提取 ProviderIds
    item = webhook_data.get("Item", {})
    provider_ids = item.get("ProviderIds", {})

    # 提取各种ID，支持多种字段名变体
    id_mappings = [
        (["Tmdb", "TheMovieDb", "TMDB"], "tmdb_id"),
        (["Imdb", "IMDB", "IMDb"], "imdb_id"),
        (["Tvdb", "TheTVDB", "TVDB"], "tvdb_id"),
        (["DoubanID", "Douban", "douban"], "douban_id"),
        (["Bangumi", "bangumi", "BangumiID"], "bangumi_id")
    ]

    for field_names, target_key in id_mappings:
        for field_name in field_names:
            if field_name in provider_ids and provider_ids[field_name]:
                metadata[target_key] = str(provider_ids[field_name])
                break

    return metadata


async def cleanup_metadata_enhancer():
    """清理元数据增强器资源"""
    global _metadata_enhancer
    if _metadata_enhancer:
        await _metadata_enhancer.close()
        _metadata_enhancer = None
