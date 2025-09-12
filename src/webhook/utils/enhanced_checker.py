"""
增强的弹幕检测器 - 支持元数据ID优先匹配，具有完善的回退机制
"""

import logging
from typing import Optional, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from ... import crud
from ...orm_models import Anime, AnimeMetadata, Episode, AnimeSource

logger = logging.getLogger(__name__)


class EnhancedDanmakuChecker:
    """增强的弹幕检测器"""
    
    @staticmethod
    async def check_anime_has_danmaku(
        session: AsyncSession, 
        title: str, 
        season: int, 
        episode_index: Optional[int] = None,
        metadata: Optional[Dict[str, Optional[str]]] = None
    ) -> bool:
        """
        增强的弹幕检测，支持元数据ID优先匹配
        
        Args:
            session: 数据库会话
            title: 动漫标题
            season: 季度
            episode_index: 集数（可选）
            metadata: 增强元数据（可选）
            
        Returns:
            是否有弹幕
        """
        logger.info(f"增强弹幕检测: 标题='{title}', 季度={season}, 集数={episode_index}")
        
        # 如果有元数据，优先使用元数据ID匹配
        if metadata and any(metadata.values()):
            logger.info(f"使用元数据ID进行匹配: {EnhancedDanmakuChecker._get_metadata_summary(metadata)}")
            
            # 按优先级尝试元数据ID匹配
            for id_type, id_value in EnhancedDanmakuChecker._get_metadata_priority_order(metadata):
                if id_value:
                    logger.debug(f"尝试使用 {id_type} ID ({id_value}) 进行匹配")
                    try:
                        anime = await EnhancedDanmakuChecker._find_anime_by_metadata_id(session, id_type, id_value)
                        if anime:
                            logger.info(f"通过 {id_type} ID 找到动漫: '{anime['title']}' (ID: {anime['id']})")
                            has_danmaku = await EnhancedDanmakuChecker._check_anime_danmaku_by_id(
                                session, anime['id'], episode_index
                            )
                            if has_danmaku:
                                logger.info(f"通过 {id_type} ID 匹配成功，找到弹幕")
                                return True
                            else:
                                logger.debug(f"通过 {id_type} ID 找到动漫但无弹幕")
                        else:
                            logger.debug(f"通过 {id_type} ID 未找到动漫")
                    except Exception as e:
                        logger.warning(f"使用 {id_type} ID 检查时出错: {e}")
                        continue
        
        # 回退到标题匹配
        logger.info("元数据ID匹配失败或无元数据，回退到标题匹配")
        try:
            has_danmaku = await crud.check_anime_has_danmaku(session, title, season, episode_index)
            logger.info(f"标题匹配结果: {'有弹幕' if has_danmaku else '无弹幕'}")
            return has_danmaku
        except Exception as e:
            logger.error(f"标题匹配时出错: {e}")
            return False
    
    @staticmethod
    async def _find_anime_by_metadata_id(session: AsyncSession, id_type: str, id_value: str) -> Optional[Dict[str, Any]]:
        """通过元数据ID查找动漫"""
        id_field_map = {
            "TMDB": AnimeMetadata.tmdbId,
            "Douban": AnimeMetadata.doubanId,
            "IMDb": AnimeMetadata.imdbId,
            "TVDB": AnimeMetadata.tvdbId,
            "Bangumi": AnimeMetadata.bangumiId
        }
        
        if id_type not in id_field_map:
            logger.warning(f"不支持的元数据ID类型: {id_type}")
            return None
        
        id_field = id_field_map[id_type]
        
        stmt = (
            select(Anime.id, Anime.title, Anime.season)
            .join(AnimeMetadata, Anime.id == AnimeMetadata.animeId)
            .where(id_field == id_value)
            .limit(1)
        )
        
        result = await session.execute(stmt)
        row = result.mappings().first()
        return dict(row) if row else None
    
    @staticmethod
    async def _check_anime_danmaku_by_id(session: AsyncSession, anime_id: int, episode_index: Optional[int]) -> bool:
        """通过动漫ID检查弹幕"""
        stmt = (
            select(Episode.commentCount, Episode.danmakuFilePath)
            .join(AnimeSource, Episode.sourceId == AnimeSource.id)
            .where(AnimeSource.animeId == anime_id)
        )
        
        if episode_index is not None:
            # 检查特定集数
            stmt = stmt.where(Episode.episodeIndex == episode_index)
            result = await session.execute(stmt)
            episode_data = result.first()
            
            if not episode_data or episode_data.commentCount <= 0:
                return False
            
            # 验证文件存在
            if episode_data.danmakuFilePath:
                fs_path = crud._get_fs_path_from_web_path(episode_data.danmakuFilePath)
                return fs_path and fs_path.is_file()
        else:
            # 检查整部剧
            result = await session.execute(stmt)
            episodes = result.all()
            
            for episode_data in episodes:
                if episode_data.commentCount > 0 and episode_data.danmakuFilePath:
                    fs_path = crud._get_fs_path_from_web_path(episode_data.danmakuFilePath)
                    if fs_path and fs_path.is_file():
                        return True
        
        return False
    
    @staticmethod
    def _get_metadata_priority_order(metadata: Dict[str, Optional[str]]) -> list:
        """获取元数据ID的优先级顺序"""
        priority_order = ["TMDB", "Douban", "IMDb", "TVDB", "Bangumi"]
        key_mapping = {
            "TMDB": "tmdb_id",
            "Douban": "douban_id", 
            "IMDb": "imdb_id",
            "TVDB": "tvdb_id",
            "Bangumi": "bangumi_id"
        }
        
        return [(id_type, metadata.get(key_mapping[id_type])) for id_type in priority_order]
    
    @staticmethod
    def _get_metadata_summary(metadata: Dict[str, Optional[str]]) -> str:
        """获取元数据摘要"""
        ids = []
        for key, value in metadata.items():
            if value:
                name = key.replace("_id", "").upper()
                ids.append(f"{name}:{value}")
        return ", ".join(ids) if ids else "无元数据ID"


# 便捷函数
async def check_danmaku_enhanced(
    session: AsyncSession, 
    title: str, 
    season: int, 
    episode_index: Optional[int] = None,
    metadata: Optional[Dict[str, Optional[str]]] = None
) -> bool:
    """
    便捷的增强弹幕检测函数
    
    这个函数提供了一个简单的接口，具有完善的错误处理，
    永远不会导致调用失败。
    """
    try:
        return await EnhancedDanmakuChecker.check_anime_has_danmaku(
            session, title, season, episode_index, metadata
        )
    except Exception as e:
        logger.error(f"增强弹幕检测时出错: {e}，回退到基本检测")
        try:
            return await crud.check_anime_has_danmaku(session, title, season, episode_index)
        except Exception as e2:
            logger.error(f"基本弹幕检测也失败: {e2}，返回False")
            return False


def has_useful_metadata(metadata: Optional[Dict[str, Optional[str]]]) -> bool:
    """检查是否有有用的元数据"""
    if not metadata:
        return False
    return any(metadata.values())
