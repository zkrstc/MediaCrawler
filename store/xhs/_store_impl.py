# -*- coding: utf-8 -*-
# @Author  : persist1@126.com
# @Time    : 2025/9/5 19:34
# @Desc    : 小红书存储实现类
import json
import os
from datetime import datetime
from typing import List, Dict, Any

from sqlalchemy import select, update, delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from base.base_crawler import AbstractStore
from database.db_session import get_session
from database.models import XhsNote, XhsNoteComment, XhsCreator

from tools.async_file_writer import AsyncFileWriter
from tools.time_util import get_current_timestamp
from var import crawler_type_var

class XhsCsvStoreImplement(AbstractStore):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.writer = AsyncFileWriter(platform="xhs", crawler_type=crawler_type_var.get())

    async def store_content(self, content_item: Dict):
        """
        store content data to csv file
        :param content_item:
        :return:
        """
        await self.writer.write_to_csv(item_type="contents", item=content_item)

    async def store_comment(self, comment_item: Dict):
        """
        store comment data to csv file
        :param comment_item:
        :return:
        """
        await self.writer.write_to_csv(item_type="comments", item=comment_item)


    async def store_creator(self, creator_item: Dict):
        pass

    def flush(self):
        pass


class XhsJsonStoreImplement(AbstractStore):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.writer = AsyncFileWriter(platform="xhs", crawler_type=crawler_type_var.get())

    async def store_content(self, content_item: Dict):
        """
        store content data to json file
        :param content_item:
        :return:
        """
        await self.writer.write_single_item_to_json(item_type="contents", item=content_item)

    async def store_comment(self, comment_item: Dict):
        """
        store comment data to json file
        :param comment_item:
        :return:
        """
        await self.writer.write_single_item_to_json(item_type="comments", item=comment_item)

    async def store_creator(self, creator_item: Dict):
        pass

    def flush(self):
        """
        flush data to json file
        :return:
        """
        pass



class XhsDbStoreImplement(AbstractStore):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    async def store_content(self, content_item: Dict):
        note_id = content_item.get("note_id")
        if not note_id:
            return
        async with get_session() as session:
            if await self.content_is_exist(session, note_id):
                await self.update_content(session, content_item)
            else:
                await self.add_content(session, content_item)

    async def add_content(self, session: AsyncSession, content_item: Dict):
        add_ts = int(get_current_timestamp())
        last_modify_ts = int(get_current_timestamp())
        note = XhsNote(
            user_id=content_item.get("user_id"),
            nickname=content_item.get("nickname"),
            avatar=content_item.get("avatar"),
            ip_location=content_item.get("ip_location"),
            add_ts=add_ts,
            last_modify_ts=last_modify_ts,
            note_id=content_item.get("note_id"),
            type=content_item.get("type"),
            title=content_item.get("title"),
            desc=content_item.get("desc"),
            video_url=content_item.get("video_url"),
            time=content_item.get("time"),
            last_update_time=content_item.get("last_update_time"),
            liked_count=str(content_item.get("liked_count")),
            collected_count=str(content_item.get("collected_count")),
            comment_count=str(content_item.get("comment_count")),
            share_count=str(content_item.get("share_count")),
            image_list=json.dumps(content_item.get("image_list")),
            tag_list=json.dumps(content_item.get("tag_list")),
            note_url=content_item.get("note_url"),
            source_keyword=content_item.get("source_keyword", ""),
            xsec_token=content_item.get("xsec_token", "")
        )
        session.add(note)

    async def update_content(self, session: AsyncSession, content_item: Dict):
        note_id = content_item.get("note_id")
        last_modify_ts = int(get_current_timestamp())
        update_data = {
            "last_modify_ts": last_modify_ts,
            "liked_count": str(content_item.get("liked_count")),
            "collected_count": str(content_item.get("collected_count")),
            "comment_count": str(content_item.get("comment_count")),
            "share_count": str(content_item.get("share_count")),
            "last_update_time": content_item.get("last_update_time"),
        }
        stmt = update(XhsNote).where(XhsNote.note_id == note_id).values(**update_data)
        await session.execute(stmt)

    async def content_is_exist(self, session: AsyncSession, note_id: str) -> bool:
        stmt = select(XhsNote).where(XhsNote.note_id == note_id)
        result = await session.execute(stmt)
        return result.first() is not None

    async def store_comment(self, comment_item: Dict):
        if not comment_item:
            return
        async with get_session() as session:
            comment_id = comment_item.get("comment_id")
            if not comment_id:
                return
            if await self.comment_is_exist(session, comment_id):
                await self.update_comment(session, comment_item)
            else:
                await self.add_comment(session, comment_item)

    async def add_comment(self, session: AsyncSession, comment_item: Dict):
        add_ts = int(get_current_timestamp())
        last_modify_ts = int(get_current_timestamp())
        comment = XhsNoteComment(
            user_id=comment_item.get("user_id"),
            nickname=comment_item.get("nickname"),
            avatar=comment_item.get("avatar"),
            ip_location=comment_item.get("ip_location"),
            add_ts=add_ts,
            last_modify_ts=last_modify_ts,
            comment_id=comment_item.get("comment_id"),
            create_time=comment_item.get("create_time"),
            note_id=comment_item.get("note_id"),
            content=comment_item.get("content"),
            sub_comment_count=comment_item.get("sub_comment_count"),
            pictures=json.dumps(comment_item.get("pictures")),
            parent_comment_id=comment_item.get("parent_comment_id"),
            like_count=str(comment_item.get("like_count"))
        )
        session.add(comment)

    async def update_comment(self, session: AsyncSession, comment_item: Dict):
        comment_id = comment_item.get("comment_id")
        last_modify_ts = int(get_current_timestamp())
        update_data = {
            "last_modify_ts": last_modify_ts,
            "like_count": str(comment_item.get("like_count")),
            "sub_comment_count": comment_item.get("sub_comment_count"),
        }
        stmt = update(XhsNoteComment).where(XhsNoteComment.comment_id == comment_id).values(**update_data)
        await session.execute(stmt)

    async def comment_is_exist(self, session: AsyncSession, comment_id: str) -> bool:
        stmt = select(XhsNoteComment).where(XhsNoteComment.comment_id == comment_id)
        result = await session.execute(stmt)
        return result.first() is not None

    async def store_creator(self, creator_item: Dict):
        user_id = creator_item.get("user_id")
        if not user_id:
            return
        async with get_session() as session:
            if await self.creator_is_exist(session, user_id):
                await self.update_creator(session, creator_item)
            else:
                await self.add_creator(session, creator_item)

    async def add_creator(self, session: AsyncSession, creator_item: Dict):
        add_ts = int(get_current_timestamp())
        last_modify_ts = int(get_current_timestamp())
        creator = XhsCreator(
            user_id=creator_item.get("user_id"),
            nickname=creator_item.get("nickname"),
            avatar=creator_item.get("avatar"),
            ip_location=creator_item.get("ip_location"),
            add_ts=add_ts,
            last_modify_ts=last_modify_ts,
            desc=creator_item.get("desc"),
            gender=creator_item.get("gender"),
            follows=str(creator_item.get("follows")),
            fans=str(creator_item.get("fans")),
            interaction=str(creator_item.get("interaction")),
            tag_list=json.dumps(creator_item.get("tag_list"))
        )
        session.add(creator)

    async def update_creator(self, session: AsyncSession, creator_item: Dict):
        user_id = creator_item.get("user_id")
        last_modify_ts = int(get_current_timestamp())
        update_data = {
            "last_modify_ts": last_modify_ts,
            "nickname": creator_item.get("nickname"),
            "avatar": creator_item.get("avatar"),
            "desc": creator_item.get("desc"),
            "follows": str(creator_item.get("follows")),
            "fans": str(creator_item.get("fans")),
            "interaction": str(creator_item.get("interaction")),
            "tag_list": json.dumps(creator_item.get("tag_list"))
        }
        stmt = update(XhsCreator).where(XhsCreator.user_id == user_id).values(**update_data)
        await session.execute(stmt)

    async def creator_is_exist(self, session: AsyncSession, user_id: str) -> bool:
        stmt = select(XhsCreator).where(XhsCreator.user_id == user_id)
        result = await session.execute(stmt)
        return result.first() is not None

    async def get_all_content(self) -> List[Dict]:
        async with get_session() as session:
            stmt = select(XhsNote)
            result = await session.execute(stmt)
            return [item.__dict__ for item in result.scalars().all()]

    async def get_all_comments(self) -> List[Dict]:
        async with get_session() as session:
            stmt = select(XhsNoteComment)
            result = await session.execute(stmt)
            return [item.__dict__ for item in result.scalars().all()]


class XhsSqliteStoreImplement(XhsDbStoreImplement):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
