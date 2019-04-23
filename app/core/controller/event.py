import app.core.dao as dao
from app.utils import CustomError, db
from flask_login import current_user
from datetime import datetime
from app.utils.Error import CustomError


class EventController(object):
    @classmethod
    def formatter(cls, event: dict):
        return event

    @classmethod
    def reformatter_insert(cls, data: dict):
        return data

    @classmethod
    def reformatter_update(cls, data: dict):
        return data

    @classmethod
    def reformatter_query(cls, data: dict):
        return data

    @classmethod
    def get_event(cls, id: int, unscoped: bool = False):
        event = dao.Event.get_event(id=id, unscoped=unscoped)
        return cls.formatter(event)

    @classmethod
    def query_events(cls, query_dict: dict, unscoped: bool = False):
        (events, num) = dao.Event.query_events(query_dict=query_dict, unscoped=unscoped)
        return [cls.formatter(event) for event in events], num

    @classmethod
    def query_user_events(cls, username: str, query_dict: dict, unscoped=False):
        query_dict['username'] = [username]
        (events, num) = dao.Event.query_events(query_dict=query_dict, unscoped=unscoped)
        return [cls.formatter(event) for event in events], num

    @classmethod
    def insert_event(cls, ctx: bool = True, data: dict = None):
        if data is None:
            data = {}
        data = cls.reformatter_insert(data=data)
        try:
            dao.Event.insert_event(ctx=False, data=data)
            if ctx:
                db.session.commit()
        except Exception as e:
            if ctx:
                db.session.rollback()
            if isinstance(e, CustomError) == CustomError:
                raise e
            else:
                raise CustomError(500, 500, str(e))
        return True

    @classmethod
    def update_event(cls, ctx: bool = True, id: int = 0, data: dict = None):
        if data is None:
            data = {}
        data = cls.reformatter_update(data)
        dao.Event.get_event(id=id, unscoped=False)
        try:
            dao.Event.update_event(ctx=False, query_dict={'id': [id]}, data=data)
            if ctx:
                db.session.commit()
        except Exception as e:
            if ctx:
                db.session.rollback()
            if isinstance(e, CustomError) == CustomError:
                raise e
            else:
                raise CustomError(500, 500, str(e))
        return True

    @classmethod
    def delete_event(cls, ctx: bool = True, id: int = 0):
        dao.Event.get_event(id=id, unscoped=False)
        try:
            dao.Event.delete_event(ctx=False, query_dict={'id': [id]})
            if ctx:
                db.session.commit()
        except Exception as e:
            if ctx:
                db.session.rollback()
            if isinstance(e, CustomError) == CustomError:
                raise e
            else:
                raise CustomError(500, 500, str(e))
        return True
